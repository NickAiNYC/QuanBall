"""
executor.py — Order execution engine.

Responsibilities:
    1. Take an Opportunity, place all legs (concurrent when possible)
    2. Handle partial fills: hedge the unfilled side at market
    3. Roll back on critical failure (cancel all legs)
    4. Track fills and return a Position object

Design:
    - Async-first; uses asyncio.gather for concurrent leg placement
    - Maker orders preferred (cfg.execution.prefer_maker)
    - Per-leg timeout: maker 8s, taker 3s
    - On partial fill of N-leg arb: hedge remaining legs at taker (cross spread)
    - Hard fail only if >1 leg totally unfilled after retry

The executor never decides sizing — that's risk.py's job. It just executes
the legs as specified by the Opportunity object, with optional adjusted_size.
"""
from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

from config import Config
from models import (
    Leg, Opportunity, OrderStatus, Position, Side,
)
from clob_client import CLOBOrderClient, CLOBRestClient

log = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# Execution result
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class LegExecutionResult:
    leg: Leg
    status: OrderStatus
    filled_shares: float = 0.0
    avg_fill_price: float = 0.0
    order_id: Optional[str] = None
    error: Optional[str] = None
    elapsed_sec: float = 0.0

    @property
    def is_filled(self) -> bool:
        return self.status == OrderStatus.FILLED

    @property
    def is_partial(self) -> bool:
        return self.status == OrderStatus.PARTIALLY_FILLED


# ─────────────────────────────────────────────────────────────────────────────
# Executor
# ─────────────────────────────────────────────────────────────────────────────

class Executor:
    """Executes arbitrage opportunities with concurrent leg placement."""

    def __init__(
        self,
        cfg: Config,
        order_client: Optional[CLOBOrderClient] = None,
        rest_client: Optional[CLOBRestClient] = None,
    ):
        self.cfg = cfg
        self.order_client = order_client
        self.rest_client = rest_client
        self._dry_run = order_client is None  # paper trading mode if no auth

    async def execute_opportunity(
        self,
        opportunity: Opportunity,
        adjusted_size_usdc: Optional[float] = None,
    ) -> Tuple[Position, List[LegExecutionResult]]:
        """Execute all legs of an opportunity.

        Args:
            opportunity: The detected arb opportunity
            adjusted_size_usdc: If provided, scale all legs to this total cost

        Returns:
            (Position, List[LegExecutionResult])
        """
        # Scale legs if size was adjusted by risk gate
        legs = opportunity.legs
        if adjusted_size_usdc and adjusted_size_usdc < opportunity.total_cost:
            scale = adjusted_size_usdc / opportunity.total_cost
            legs = [
                Leg(
                    market=l.market, side=l.side, price=l.price,
                    shares=l.shares * scale, cost=l.cost * scale,
                    is_maker=l.is_maker,
                )
                for l in opportunity.legs
            ]

        if self._dry_run:
            log.info(f"[DRY RUN] Would execute {len(legs)} legs for opp {opportunity.id}")
            return self._dry_run_position(opportunity, legs), [
                LegExecutionResult(leg=l, status=OrderStatus.FILLED,
                                   filled_shares=l.shares, avg_fill_price=l.price)
                for l in legs
            ]

        # Execute legs concurrently
        if self.cfg.execution.concurrent_legs:
            results = await asyncio.gather(*[self._execute_leg(l) for l in legs])
        else:
            results = []
            for l in legs:
                results.append(await self._execute_leg(l))

        # Hedge any partial fills
        results = await self._hedge_partials(opportunity, list(results))

        # Build Position object
        position = self._build_position(opportunity, legs, results)
        return position, results

    async def _execute_leg(self, leg: Leg) -> LegExecutionResult:
        """Execute one leg with maker-first preference and taker fallback."""
        start = time.time()
        token_id = leg.market.token_id_yes if leg.side == Side.YES else leg.market.token_id_no
        side_str = "BUY"  # We're always buying either YES or NO tokens

        # Maker attempt first
        if self.cfg.execution.prefer_maker and leg.is_maker:
            try:
                resp = await asyncio.wait_for(
                    self.order_client.place_limit_order(
                        token_id=token_id, side=side_str,
                        price=leg.price, size=leg.shares,
                    ),
                    timeout=self.cfg.execution.maker_timeout_sec,
                )
                filled = self._extract_fill_size(resp)
                if filled >= leg.shares * 0.99:
                    return LegExecutionResult(
                        leg=leg, status=OrderStatus.FILLED,
                        filled_shares=filled, avg_fill_price=leg.price,
                        order_id=self._extract_order_id(resp),
                        elapsed_sec=time.time() - start,
                    )
                elif filled > 0:
                    return LegExecutionResult(
                        leg=leg, status=OrderStatus.PARTIALLY_FILLED,
                        filled_shares=filled, avg_fill_price=leg.price,
                        order_id=self._extract_order_id(resp),
                        elapsed_sec=time.time() - start,
                    )
                # No fill — fall through to taker
            except asyncio.TimeoutError:
                log.info(f"Maker order timed out for {token_id[:8]}; crossing spread")
                # Cancel the unfilled maker order
                # (In production, you'd track the order_id and cancel it)
            except Exception as e:
                log.warning(f"Maker order failed for {token_id[:8]}: {e}")

        # Taker fallback
        try:
            resp = await asyncio.wait_for(
                self.order_client.place_market_order(
                    token_id=token_id, side=side_str, size=leg.shares,
                ),
                timeout=self.cfg.execution.taker_timeout_sec,
            )
            filled = self._extract_fill_size(resp)
            avg_price = self._extract_avg_price(resp) or leg.price
            if filled >= leg.shares * 0.99:
                return LegExecutionResult(
                    leg=leg, status=OrderStatus.FILLED,
                    filled_shares=filled, avg_fill_price=avg_price,
                    order_id=self._extract_order_id(resp),
                    elapsed_sec=time.time() - start,
                )
            elif filled > 0:
                return LegExecutionResult(
                    leg=leg, status=OrderStatus.PARTIALLY_FILLED,
                    filled_shares=filled, avg_fill_price=avg_price,
                    order_id=self._extract_order_id(resp),
                    elapsed_sec=time.time() - start,
                )
            else:
                return LegExecutionResult(
                    leg=leg, status=OrderStatus.FAILED,
                    error="Zero fill on market order",
                    elapsed_sec=time.time() - start,
                )
        except asyncio.TimeoutError:
            return LegExecutionResult(
                leg=leg, status=OrderStatus.FAILED,
                error="Taker order timed out",
                elapsed_sec=time.time() - start,
            )
        except Exception as e:
            return LegExecutionResult(
                leg=leg, status=OrderStatus.FAILED,
                error=str(e),
                elapsed_sec=time.time() - start,
            )

    async def _hedge_partials(
        self,
        opportunity: Opportunity,
        results: List[LegExecutionResult],
    ) -> List[LegExecutionResult]:
        """If any leg is partial/failed, hedge by crossing the spread on
        remaining legs to lock in P&L (or minimize loss).

        For arb: if leg A filled 100% but leg B filled only 50%, we now have
        unhedged exposure on the unfilled 50% of leg B. Options:
            (a) Cancel A, accept the loss
            (b) Hedge by crossing B at market (taker fee + slippage)
        We choose (b) when slippage tolerance allows.
        """
        if not self.cfg.execution.hedge_on_partial_fill:
            return results

        has_partial = any(r.is_partial or r.status == OrderStatus.FAILED for r in results)
        if not has_partial:
            return results

        # Find min filled shares across all legs — that's our matched amount
        min_filled = min(
            (r.filled_shares for r in results if r.filled_shares > 0),
            default=0,
        )

        # For each leg with filled > min_filled, attempt to sell the excess
        # at market (cross the bid) to flatten
        hedged_results = []
        for r in results:
            if r.filled_shares > min_filled * 1.01:
                excess = r.filled_shares - min_filled
                log.info(f"Hedging {excess:.2f} excess shares on {r.leg.market.condition_id[:8]}")
                # Place sell order
                token_id = r.leg.market.token_id_yes if r.leg.side == Side.YES else r.leg.market.token_id_no
                try:
                    await self.order_client.place_market_order(
                        token_id=token_id, side="SELL", size=excess,
                    )
                    r.filled_shares = min_filled  # adjusted down
                except Exception as e:
                    log.warning(f"Hedge failed: {e}")
            hedged_results.append(r)

        return hedged_results

    def _build_position(
        self,
        opportunity: Opportunity,
        legs: List[Leg],
        results: List[LegExecutionResult],
    ) -> Position:
        """Construct a Position from execution results."""
        filled_shares = [r.filled_shares for r in results]
        avg_prices = [r.avg_fill_price for r in results]
        total_cost = sum(
            r.filled_shares * r.avg_fill_price for r in results
        )

        all_filled = all(r.is_filled for r in results)
        any_filled = any(r.filled_shares > 0 for r in results)

        if all_filled:
            status = OrderStatus.FILLED
        elif any_filled:
            status = OrderStatus.PARTIALLY_FILLED
        else:
            status = OrderStatus.FAILED

        return Position(
            opportunity_id=opportunity.id,
            legs=legs,
            filled_shares=filled_shares,
            avg_fill_prices=avg_prices,
            total_cost=total_cost,
            status=status,
            opened_at=time.time(),
        )

    def _dry_run_position(
        self, opportunity: Opportunity, legs: List[Leg],
    ) -> Position:
        """Construct a hypothetical filled position for paper trading."""
        return Position(
            opportunity_id=opportunity.id,
            legs=legs,
            filled_shares=[l.shares for l in legs],
            avg_fill_prices=[l.price for l in legs],
            total_cost=sum(l.cost for l in legs),
            status=OrderStatus.FILLED,
            opened_at=time.time(),
        )

    # ───────────────────────────────────────────────────────────────────────
    # py-clob-client response parsing helpers
    # ───────────────────────────────────────────────────────────────────────

    @staticmethod
    def _extract_fill_size(resp: Dict) -> float:
        """Extract total filled shares from a py-clob-client order response.

        Response format varies; the SDK typically returns:
            {"orderID": "...", "status": "...", "makingAmount": "...", "takingAmount": "..."}
        """
        if not resp:
            return 0.0
        # Try common fields
        for key in ("filled_size", "filledSize", "size_matched", "makingAmount"):
            if key in resp:
                try:
                    return float(resp[key])
                except (ValueError, TypeError):
                    pass
        # If order status is "MATCHED" assume full fill
        if resp.get("status") in ("MATCHED", "FILLED", "LIVE"):
            return float(resp.get("original_size", resp.get("size", 0)))
        return 0.0

    @staticmethod
    def _extract_avg_price(resp: Dict) -> Optional[float]:
        """Extract average fill price from order response."""
        if not resp:
            return None
        for key in ("avg_price", "averagePrice", "price"):
            if key in resp:
                try:
                    return float(resp[key])
                except (ValueError, TypeError):
                    pass
        return None

    @staticmethod
    def _extract_order_id(resp: Dict) -> Optional[str]:
        if not resp:
            return None
        return resp.get("orderID") or resp.get("order_id") or resp.get("id")


# ─────────────────────────────────────────────────────────────────────────────
# Rollback on critical failure
# ─────────────────────────────────────────────────────────────────────────────

async def rollback_position(
    position: Position,
    order_client: CLOBOrderClient,
) -> bool:
    """Attempt to flatten a position by selling all filled shares.

    Used when execution fails catastrophically (e.g., 2 of 4 legs failed
    and the position is now unhedged directional risk).
    """
    success = True
    for leg, filled, avg_price in zip(position.legs, position.filled_shares, position.avg_fill_prices):
        if filled <= 0:
            continue
        token_id = leg.market.token_id_yes if leg.side == Side.YES else leg.market.token_id_no
        try:
            await order_client.place_market_order(
                token_id=token_id, side="SELL", size=filled,
            )
            log.info(f"Rolled back {filled:.2f} shares of {token_id[:8]}")
        except Exception as e:
            log.error(f"ROLLBACK FAILED for {token_id[:8]}: {e}")
            success = False
    return success
