"""
clob_client.py — Polymarket CLOB (Central Limit Order Book) client.

CLOB is where prices live. It exposes:
    - Order books (top-of-book + depth)
    - Last trade prices
    - WebSocket subscription for real-time updates
    - Order placement (requires auth via py-clob-client)

We use two transports:
    1. httpx for REST polling (order book, prices)
    2. websockets for real-time book deltas (in-play mode)

Auth: Order placement uses py-clob-client (Polymarket's official Python SDK).
We wrap it because py-clob-client is synchronous and we want async.
"""
from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, AsyncIterator, Dict, List, Optional

import httpx

from config import Config
from models import Market, OrderBook, OrderBookLevel

log = logging.getLogger(__name__)

# py-clob-client is the official SDK — installed via `pip install py-clob-client`
try:
    from py_clob_client.client import ClobClient
    from py_clob_client.clob_types import OrderArgs, OrderType
    from py_clob_client.constants import POLYGON
    HAS_CLOB_SDK = True
except ImportError:
    HAS_CLOB_SDK = False
    log.warning("py-clob-client not installed; order placement disabled (read-only mode)")


# ─────────────────────────────────────────────────────────────────────────────
# REST CLOB client (read-only)
# ─────────────────────────────────────────────────────────────────────────────

class CLOBRestClient:
    """Async REST client for order book data."""

    def __init__(self, cfg: Config):
        self.cfg = cfg
        self.base_url = cfg.api.clob_base_url
        self.client: Optional[httpx.AsyncClient] = None

    async def __aenter__(self):
        self.client = httpx.AsyncClient(
            base_url=self.base_url,
            timeout=httpx.Timeout(8.0, connect=3.0),
            limits=httpx.Limits(
                max_connections=self.cfg.api.max_concurrent_requests,
                max_keepalive_connections=8,
            ),
        )
        return self

    async def __aexit__(self, *args):
        if self.client:
            await self.client.aclose()
            self.client = None

    async def _get(self, path: str, params: Optional[Dict] = None) -> Any:
        assert self.client
        for attempt in range(3):
            try:
                r = await self.client.get(path, params=params)
                r.raise_for_status()
                return r.json()
            except (httpx.HTTPError, httpx.RequestError) as e:
                log.warning(f"CLOB GET {path} attempt {attempt+1} failed: {e}")
                await asyncio.sleep(0.5 * (2 ** attempt))
        raise

    # ───────────────────────────────────────────────────────────────────────
    # Order book
    # ───────────────────────────────────────────────────────────────────────

    async def get_order_book(self, token_id: str) -> OrderBook:
        """Fetch the full order book for a token (YES side).

        Polymarket CLOB returns bids/asks for YES tokens. NO side is implicit:
            NO_bid = 1 - YES_ask
            NO_ask = 1 - YES_bid
        """
        raw = await self._get(f"/book?token_id={token_id}")
        return self._parse_book(raw)

    async def get_price(self, token_id: str, side: str = "mid") -> Optional[float]:
        """Get the current price for a token. side ∈ {mid, buy, sell}."""
        try:
            data = await self._get(f"/price?token_id={token_id}&side={side}")
            return float(data.get("price", 0)) if data else None
        except Exception:
            return None

    async def get_prices(self, token_id: str) -> Dict[str, float]:
        """Get bid, ask, mid for a token in one call."""
        prices = {}
        for side in ("buy", "sell"):
            try:
                data = await self._get(f"/price?token_id={token_id}&side={side}")
                prices[side] = float(data.get("price", 0)) if data else 0.0
            except Exception:
                prices[side] = 0.0
        prices["mid"] = (prices.get("buy", 0) + prices.get("sell", 0)) / 2
        return prices

    async def get_books_for_markets(
        self, markets: List[Market], concurrency: int = 16
    ) -> Dict[str, OrderBook]:
        """Fetch order books for many markets in parallel.

        Returns: {condition_id: OrderBook}
        """
        sem = asyncio.Semaphore(concurrency)

        async def fetch_one(m: Market) -> tuple[str, Optional[OrderBook]]:
            async with sem:
                try:
                    book = await self.get_order_book(m.token_id_yes)
                    return m.condition_id, book
                except Exception as e:
                    log.warning(f"Failed to fetch book for {m.condition_id}: {e}")
                    return m.condition_id, None

        results = await asyncio.gather(*[fetch_one(m) for m in markets])
        return {cid: book for cid, book in results if book is not None}

    @staticmethod
    def _parse_book(raw: Dict) -> OrderBook:
        """Parse CLOB book response into OrderBook dataclass.

        CLOB returns:
            {
                "market": "...",
                "asset_id": "...",
                "bids": [{"price": "0.45", "size": "100"}, ...],
                "asks": [{"price": "0.46", "size": "200"}, ...],
                "timestamp": "..."
            }
        """
        def parse_levels(raw_list: List[Dict]) -> List[OrderBookLevel]:
            levels = []
            for entry in raw_list or []:
                try:
                    levels.append(OrderBookLevel(
                        price=float(entry["price"]),
                        size=float(entry["size"]),
                    ))
                except (KeyError, ValueError, TypeError):
                    continue
            # bids: descending by price; asks: ascending
            levels.sort(key=lambda l: l.price, reverse=True)  # we'll fix per-side below
            return levels

        bids = parse_levels(raw.get("bids", []))
        asks = parse_levels(raw.get("asks", []))

        # bids should be descending, asks ascending
        bids.sort(key=lambda l: l.price, reverse=True)
        asks.sort(key=lambda l: l.price, reverse=False)

        return OrderBook(
            bids=bids,
            asks=asks,
            timestamp=float(raw.get("timestamp", 0)),
        )


# ─────────────────────────────────────────────────────────────────────────────
# WebSocket CLOB client (real-time)
# ─────────────────────────────────────────────────────────────────────────────

class CLOBWSClient:
    """WebSocket client for real-time order book updates.

    Polymarket CLOB WS endpoint: wss://ws-subscriptions-clob.polymarket.com/ws
    Subscribe with: {"assets_ids": ["token1", "token2", ...], "type": "market"}

    Messages are deltas:
        {"event": "book", "asset_id": "...", "changes": [...]}
        {"event": "price_change", "asset_id": "...", "changes": [...]}
        {"event": "last_trade_price", "asset_id": "...", "price": "0.50"}
    """

    def __init__(self, cfg: Config):
        self.cfg = cfg
        self.url = cfg.api.ws_url
        self.ws: Optional[Any] = None
        self._books: Dict[str, OrderBook] = {}
        self._handlers: List[callable] = []
        self._running = False
        self._reconnect_attempts = 0

    def on_book_update(self, handler):
        """Register a callback: handler(token_id: str, book: OrderBook)."""
        self._handlers.append(handler)

    async def subscribe(self, token_ids: List[str]):
        """Subscribe to book updates for the given token IDs."""
        # 'websockets' package is the standard Python WS lib
        import websockets

        msg = json.dumps({
            "type": "market",
            "assets_ids": token_ids,
        })
        await self.ws.send(msg)
        log.info(f"Subscribed to {len(token_ids)} tokens on CLOB WS")

    async def run(self, token_ids: List[str]):
        """Connect, subscribe, and pump messages until stopped.

        Auto-reconnects with exponential backoff on disconnect.
        """
        import websockets

        self._running = True
        while self._running:
            try:
                async with websockets.connect(
                    self.url,
                    ping_interval=20,
                    ping_timeout=10,
                    close_timeout=5,
                ) as ws:
                    self.ws = ws
                    self._reconnect_attempts = 0
                    await self.subscribe(token_ids)
                    async for raw_msg in ws:
                        if not self._running:
                            break
                        await self._handle_message(raw_msg)
            except Exception as e:
                if not self._running:
                    break
                self._reconnect_attempts += 1
                backoff = self._backoff()
                log.warning(f"CLOB WS disconnected (attempt {self._reconnect_attempts}): {e}; reconnect in {backoff}s")
                await asyncio.sleep(backoff)

    def _backoff(self) -> float:
        backoffs = self.cfg.scanner.ws_reconnect_backoff
        idx = min(self._reconnect_attempts - 1, len(backoffs) - 1)
        return backoffs[idx]

    async def stop(self):
        self._running = False
        if self.ws:
            await self.ws.close()

    async def _handle_message(self, raw_msg: str):
        """Parse a WS message and update local book state."""
        try:
            # Polymarket sometimes sends arrays of messages
            data = json.loads(raw_msg)
            if isinstance(data, list):
                for item in data:
                    await self._process_one(item)
            else:
                await self._process_one(data)
        except json.JSONDecodeError:
            log.debug(f"Non-JSON WS message: {raw_msg[:200]}")
        except Exception as e:
            log.warning(f"Error processing WS message: {e}")

    async def _process_one(self, msg: Dict):
        """Handle one WS message."""
        event = msg.get("event")
        asset_id = msg.get("asset_id", "")

        if event in ("book", "price_change"):
            # Full book snapshot or delta
            changes = msg.get("changes", [])
            book = self._books.get(asset_id)
            if not book:
                book = OrderBook()
                self._books[asset_id] = book

            for change in changes:
                price = float(change.get("price", 0))
                size = float(change.get("size", 0))
                side = change.get("side", "buy")
                level = OrderBookLevel(price=price, size=size)

                if side == "buy":
                    # Update or insert bid
                    book.bids = [l for l in book.bids if l.price != price]
                    if size > 0:
                        book.bids.append(level)
                        book.bids.sort(key=lambda l: l.price, reverse=True)
                else:
                    book.asks = [l for l in book.asks if l.price != price]
                    if size > 0:
                        book.asks.append(level)
                        book.asks.sort(key=lambda l: l.price, reverse=False)

            book.timestamp = msg.get("timestamp", book.timestamp)

            # Notify handlers
            for handler in self._handlers:
                try:
                    handler(asset_id, book)
                except Exception as e:
                    log.warning(f"Handler error: {e}")

        elif event == "last_trade_price":
            log.debug(f"Last trade for {asset_id}: {msg.get('price')}")

    def get_book(self, token_id: str) -> Optional[OrderBook]:
        return self._books.get(token_id)


# ─────────────────────────────────────────────────────────────────────────────
# Authenticated order placement (wrapper around py-clob-client)
# ─────────────────────────────────────────────────────────────────────────────

class CLOBOrderClient:
    """Authenticated client for placing/cancelling orders.

    Wraps the synchronous py-clob-client in an async executor so we don't
    block the event loop.

    Requires POLY_PRIVATE_KEY and POLY_API_KEY set in env.
    """

    def __init__(self, cfg: Config):
        if not HAS_CLOB_SDK:
            raise RuntimeError("py-clob-client not installed")
        self.cfg = cfg
        self._client: Optional[ClobClient] = None

    def _ensure_client(self):
        if self._client:
            return
        if not self.cfg.api.private_key or not self.cfg.api.wallet_address:
            raise RuntimeError("Missing POLY_PRIVATE_KEY or POLY_WALLET_ADDRESS")
        self._client = ClobClient(
            host=self.cfg.api.clob_base_url,
            key=self.cfg.api.private_key,
            chain_id=POLYGON,
            signature_type=2,  # POLY_GNOSIS_SAFE style for proxy wallets
            funder=self.cfg.api.wallet_address,
        )
        # Derive API creds if not provided
        if not self.cfg.api.api_key:
            creds = self._client.create_or_derive_api_creds()
            self.cfg.api.api_key = creds.api_key
            self.cfg.api.api_secret = creds.api_secret
            self.cfg.api.api_passphrase = creds.api_passphrase
        self._client.set_api_creds(self._client.get_api_creds())

    async def place_limit_order(
        self,
        token_id: str,
        side: str,         # "BUY" or "SELL"
        price: float,      # 0..1
        size: float,       # shares
    ) -> Dict:
        """Place a limit (GTC) order. Maker fee = 0.

        Returns the order response from py-clob-client.
        """
        self._ensure_client()
        args = OrderArgs(token_id=token_id, price=price, size=size, side=side)
        loop = asyncio.get_running_loop()
        # Run sync SDK in threadpool
        resp = await loop.run_in_executor(
            None,
            lambda: self._client.create_order(args)
                    and self._client.post_order(self._client.create_order(args), OrderType.GTC)
        )
        log.info(f"Limit order placed: {side} {size} {token_id[:8]} @ {price}")
        return resp

    async def place_market_order(
        self,
        token_id: str,
        side: str,
        size: float,
    ) -> Dict:
        """Place a market (FOK) order. Taker fee = 0.75%."""
        self._ensure_client()
        args = OrderArgs(token_id=token_id, price=0.0, size=size, side=side)
        loop = asyncio.get_running_loop()
        order = await loop.run_in_executor(None, lambda: self._client.create_order(args))
        resp = await loop.run_in_executor(
            None, lambda: self._client.post_order(order, OrderType.FOK)
        )
        log.info(f"Market order placed: {side} {size} {token_id[:8]}")
        return resp

    async def cancel_order(self, order_id: str) -> bool:
        self._ensure_client()
        loop = asyncio.get_running_loop()
        try:
            await loop.run_in_executor(
                None, lambda: self._client.cancel(order_id)
            )
            return True
        except Exception as e:
            log.warning(f"Cancel failed for {order_id}: {e}")
            return False

    async def get_open_orders(self) -> List[Dict]:
        self._ensure_client()
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(
            None, lambda: self._client.get_orders()
        )
