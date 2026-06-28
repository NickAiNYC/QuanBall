"""
gamma_client.py — Polymarket Gamma API client.

Gamma is the public metadata API: events, markets, slugs, descriptions.
It does NOT have order book data — use clob_client for that.

Docs: https://docs.polymarket.com/developers/CLOB/markets/api

Key endpoints used:
    GET /events              — list events (sports filter)
    GET /events/{slug}       — one event with all its markets
    GET /markets             — list markets (with filters)

This client is async-first (httpx.AsyncClient) because we want to
fan out across many events in parallel.
"""
from __future__ import annotations

import asyncio
import logging
import re
from typing import Any, Dict, List, Optional

import httpx

from models import (
    Event, Market, MarketCategory, MarketType, Sport,
)
from config import Config

log = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# Sport detection — Polymarket tags events, but the tagging is inconsistent.
# We fall back to regex on the event title.
# ─────────────────────────────────────────────────────────────────────────────

_SPORT_PATTERNS: Dict[Sport, re.Pattern] = {
    Sport.NBA: re.compile(
        r"\b(NBA|Lakers|Celtics|Warriors|Nuggets|Bucks|Suns|Knicks|"
        r"76ers|Heat|Mavericks|Clippers|Kings|Hawks|Pacers|Bulls|"
        r"Cavaliers|Magic|Pistons|Raptors|Grizzlies|Pelicans|"
        r"Timberwolves|Spurs|Rockets|Thunder|Trail Blazers|Blazers|Jazz|Nets)\b",
        re.IGNORECASE,
    ),
    Sport.NFL: re.compile(
        r"\b(NFL|Chiefs|Eagles|49ers|Bills|Cowboys|Ravens|Bengals|"
        r"Packers|Lions|Dolphins|Jets|Patriots|Steelers|Browns|"
        r"Texans|Colts|Jaguars|Titans|Broncos|Raiders|Chargers|"
        r"Seahawks|Rams|Cardinals|Falcons|Panthers|Saints|Buccaneers|"
        r"Vikings|Bears|Commanders|Football Team|Giants)\b",
        re.IGNORECASE,
    ),
    Sport.MLB: re.compile(r"\b(MLB|Yankees|Red Sox|Dodgers|Astros|Braves|Mets|Phillies|Padres|Guardians|Orioles|Rays|Blue Jays|Twins|White Sox|Tigers|Royals|Angels|Rangers|Athletics|A's|Mariners|Giants|Cardinals|Cubs|Brewers|Pirates|Reds|Nationals|Marlins|Rockies|Diamondbacks)\b", re.IGNORECASE),
    Sport.NHL: re.compile(r"\b(NHL|Rangers|Bruins|Lightning|Maple Leafs|Panthers|Hurricanes|Devils|Islanders|Capitals|Penguins|Flyers|Sabres|Senators|Red Wings|Canadiens|Canucks|Flames|Oilers|Avalanche|Wild|Stars|Jets|Predators|Blackhawks|Blue Jackets|Golden Knights|Kraken|Sharks|Ducks|Coyotes)\b", re.IGNORECASE),
    Sport.SOCCER: re.compile(r"\b(EPL|Premier League|La Liga|Bundesliga|Serie A|Ligue 1|UCL|Champions League|Europa League|World Cup|MLS|Man City|Man United|Liverpool|Chelsea|Arsenal|Tottenham|Real Madrid|Barcelona|Bayern|PSG|Juventus|Inter|AC Milan|Napoli|Atletico)\b", re.IGNORECASE),
    Sport.TENNIS: re.compile(r"\b(ATP|WTA|Grand Slam|Australian Open|French Open|Wimbledon|US Open|Djokovic|Alcaraz|Sinner|Medvedev|Rublev|Fritz|Tsitsipas|Zverev|Ruud|Hurkacz|Shelton|Dimitrov|Rune|Tiafoe|Khachanov|Cerundolo|Swiatek|Sabalenka|Gauff|Rybakina|Pegula|Jabeur|Vondrousova|Kasatkina|Krejcikova)\b", re.IGNORECASE),
    Sport.MMA: re.compile(r"\b(UFC|MMA|Jones|Adesanya|Ngannou|Gane|Volkov|Rozenstruik|Tuivasa|Spivac|Ismagulov|Krylov|Cutelaba|Bukauskas|Pedro|Ulanbekov|Erceg|Hadley|Shayilan|Lopes|Mokaev|Kape|Almabayev|Bontorin|Royval|Pantoja|Moreno|Figueredo|Perez|Taira|Asakura|Kairat|Cummings|Harris|Bessette|Scoggins|Bui|Barcelos|Jourdain|Wood|Allen|Dawson|Chikadze|Emmett|Ortega|Yair|Volkanovski|Holloway|Topuria|Evloev|Lopes|L Lerone|Allen|Erosa|Dawson)\b", re.IGNORECASE),
}


def detect_sport(title: str, tags: Optional[List[str]] = None) -> Sport:
    """Detect sport from event title and tags."""
    # First check explicit tags (Polymarket sometimes tags Sports → NBA etc.)
    if tags:
        for tag in tags:
            t = tag.lower()
            if "nba" in t:
                return Sport.NBA
            if "nfl" in t:
                return Sport.NFL
            if "mlb" in t:
                return Sport.MLB
            if "nhl" in t:
                return Sport.NHL
            if "soccer" in t or "football" in t and "nfl" not in t:
                return Sport.SOCCER
            if "tennis" in t:
                return Sport.TENNIS
            if "mma" in t or "ufc" in t:
                return Sport.MMA

    # Fallback: regex on title
    for sport, pattern in _SPORT_PATTERNS.items():
        if pattern.search(title):
            return sport

    return Sport.OTHER


# ─────────────────────────────────────────────────────────────────────────────
# Market category detection
# ─────────────────────────────────────────────────────────────────────────────

_MONEYLINE_RE = re.compile(
    r"\b(will\s+win|moneyline|match\s+winner|game\s+winner)\b", re.IGNORECASE
)
_SPREAD_RE = re.compile(
    r"([+-]?\d+\.?\d*)\s*(point|pt|run|puck|goal)\s*(spread|line|handicap)|"
    r"\b(spread|handicap|line)\b\s*([+-]?\d+\.?\d*)",
    re.IGNORECASE,
)
_TOTAL_RE = re.compile(
    r"(over|under|o/u)\s*(\d+\.?\d*)|"
    r"(total|totals)\s*(over|under|o/u)?\s*(\d+\.?\d*)",
    re.IGNORECASE,
)
_PLAYER_PROP_RE = re.compile(
    r"\b(points|rebounds|assists|steals|blocks|threes|3-pointers|"
    r"passing\s+yards|rushing\s+yards|receiving\s+yards|"
    r"touchdowns|hits|home\s+runs|strikeouts|"
    r"goals|assists|saves)\b.*\b(over|under|o/u)\b",
    re.IGNORECASE,
)
_QUARTER_RE = re.compile(r"\b(q[1-4]|1st\s+q|2nd\s+q|3rd\s+q|4th\s+q|first\s+quarter|second\s+quarter|third\s+quarter|fourth\s+quarter)\b", re.IGNORECASE)
_HALF_RE = re.compile(r"\b(1h|2h|first\s+half|second\s+half)\b", re.IGNORECASE)


def detect_category(question: str) -> MarketCategory:
    """Classify a Polymarket market by question text."""
    if _PLAYER_PROP_RE.search(question):
        return MarketCategory.PLAYER_PROP
    if _QUARTER_RE.search(question):
        return MarketCategory.QUARTER_LINE
    if _HALF_RE.search(question):
        return MarketCategory.HALF_LINE
    if _SPREAD_RE.search(question):
        return MarketCategory.SPREAD
    if _TOTAL_RE.search(question):
        return MarketCategory.TOTAL
    if _MONEYLINE_RE.search(question):
        return MarketCategory.MONEYLINE
    return MarketCategory.OTHER


def parse_spread_value(question: str) -> Optional[float]:
    """Extract the spread number from a question like 'Lakers -3.5'."""
    m = _SPREAD_RE.search(question)
    if not m:
        return None
    for g in m.groups():
        if g and re.match(r"[+-]?\d+\.?\d*$", g):
            return float(g)
    return None


def parse_total_value(question: str) -> Optional[float]:
    """Extract the total points line from 'Over 220.5' style questions."""
    m = _TOTAL_RE.search(question)
    if not m:
        return None
    for g in m.groups():
        if g and re.match(r"\d+\.?\d*$", g):
            return float(g)
    return None


# ─────────────────────────────────────────────────────────────────────────────
# Gamma client
# ─────────────────────────────────────────────────────────────────────────────

class GammaClient:
    """Async client for Polymarket Gamma API."""

    def __init__(self, cfg: Config):
        self.cfg = cfg
        self.base_url = cfg.api.gamma_base_url
        self.client: Optional[httpx.AsyncClient] = None

    async def __aenter__(self):
        limits = httpx.Limits(
            max_connections=self.cfg.api.max_concurrent_requests,
            max_keepalive_connections=self.cfg.api.max_concurrent_requests // 2,
        )
        self.client = httpx.AsyncClient(
            base_url=self.base_url,
            timeout=httpx.Timeout(10.0, connect=5.0),
            limits=limits,
        )
        return self

    async def __aexit__(self, exc_type, exc, tb):
        if self.client:
            await self.client.aclose()
            self.client = None

    async def _get(self, path: str, params: Optional[Dict] = None) -> Any:
        """GET with simple retry/backoff."""
        assert self.client, "Use 'async with GammaClient(cfg) as g:'"
        last_exc = None
        for attempt in range(3):
            try:
                r = await self.client.get(path, params=params)
                r.raise_for_status()
                return r.json()
            except (httpx.HTTPError, httpx.RequestError) as e:
                last_exc = e
                wait = 0.5 * (2 ** attempt)
                log.warning(f"Gamma GET {path} attempt {attempt+1} failed: {e}; retry in {wait}s")
                await asyncio.sleep(wait)
        raise last_exc

    # ───────────────────────────────────────────────────────────────────────
    # Event / market fetching
    # ───────────────────────────────────────────────────────────────────────

    async def list_sports_events(
        self,
        active_only: bool = True,
        closed: bool = False,
        limit: int = 500,
        offset: int = 0,
    ) -> List[Dict]:
        """List sports-tagged events.

        Gamma API supports tag filtering. The 'Sports' parent tag ID is 1,
        but tag IDs change over time — we filter on the client side too.
        """
        params = {
            "active": str(active_only).lower(),
            "closed": str(closed).lower(),
            "limit": limit,
            "offset": offset,
            "order": "startDate",
            "ascending": "true",
        }
        data = await self._get("/events", params=params)
        events = data if isinstance(data, list) else data.get("data", data)

        # Client-side sport filter — Gamma's tag filter is unreliable
        sports_events = []
        for ev in events:
            tags = [t.get("label", "") for t in ev.get("tags", [])]
            title = ev.get("title", "")
            if detect_sport(title, tags) != Sport.OTHER:
                sports_events.append(ev)
        return sports_events

    async def get_event(self, slug: str) -> Optional[Dict]:
        """Fetch a single event by slug, with all its markets."""
        try:
            return await self._get(f"/events/{slug}")
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 404:
                return None
            raise

    async def list_markets(
        self,
        event_slug: Optional[str] = None,
        active_only: bool = True,
        limit: int = 500,
    ) -> List[Dict]:
        """List markets, optionally filtered by event."""
        params = {
            "active": str(active_only).lower(),
            "limit": limit,
        }
        if event_slug:
            params["event_slug"] = event_slug
        data = await self._get("/markets", params=params)
        return data if isinstance(data, list) else data.get("data", [])

    # ───────────────────────────────────────────────────────────────────────
    # Domain object parsing
    # ───────────────────────────────────────────────────────────────────────

    @staticmethod
    def parse_market(raw: Dict, event_slug: str = "") -> Market:
        """Convert a Gamma market JSON into a Market dataclass."""
        question = raw.get("question", "")
        category = detect_category(question)
        sport = Sport.OTHER  # set later from event

        # Token IDs — these are ERC1155 token IDs on the ConditionalTokens contract
        # For non-NegRisk markets: clobTokenIds is [yes_id, no_id]
        # For NegRisk markets: same but indexed differently
        clob_ids = raw.get("clobTokenIds", [])
        if isinstance(clob_ids, str):
            clob_ids = clob_ids.split(",")
        token_yes = clob_ids[0] if len(clob_ids) >= 1 else ""
        token_no = clob_ids[1] if len(clob_ids) >= 2 else ""

        return Market(
            condition_id=raw.get("conditionId", raw.get("condition_id", "")),
            question=question,
            slug=raw.get("slug", ""),
            event_slug=event_slug or raw.get("eventSlug", raw.get("event_slug", "")),
            token_id_yes=str(token_yes),
            token_id_no=str(token_no),
            market_type=MarketType.NEGRISK_MULTI if raw.get("negRisk") else MarketType.BINARY,
            sport=sport,
            category=category,
            end_date=raw.get("endDate"),
            neg_risk=bool(raw.get("negRisk")),
            neg_risk_request_id=raw.get("negRiskRequestId"),
            neg_risk_market_id=raw.get("negRiskMarketId"),
            spread_value=parse_spread_value(question) if category == MarketCategory.SPREAD else None,
            total_value=parse_total_value(question) if category == MarketCategory.TOTAL else None,
        )

    @staticmethod
    def parse_event(raw: Dict) -> Event:
        """Convert a Gamma event JSON into an Event dataclass."""
        title = raw.get("title", "")
        tags = [t.get("label", "") for t in raw.get("tags", [])]
        sport = detect_sport(title, tags)
        event_slug = raw.get("slug", "")

        markets = []
        for m_raw in raw.get("markets", []):
            try:
                m = GammaClient.parse_market(m_raw, event_slug=event_slug)
                m.sport = sport
                markets.append(m)
            except Exception as e:
                log.warning(f"Failed to parse market in event {event_slug}: {e}")

        return Event(
            slug=event_slug,
            title=title,
            sport=sport,
            start_time=raw.get("startDate"),
            markets=markets,
        )

    async def fetch_sports_events_with_markets(
        self,
        sports: Optional[List[Sport]] = None,
        max_events: int = 50,
    ) -> List[Event]:
        """Convenience: fetch and parse sports events in parallel.

        Args:
            sports: filter to these sports (None = all sports)
            max_events: cap on number of events fetched

        Returns:
            List of parsed Event objects with all markets populated.
        """
        raw_events = await self.list_sports_events(limit=max_events)
        if sports:
            sports_set = set(sports)
            raw_events = [
                ev for ev in raw_events
                if detect_sport(
                    ev.get("title", ""),
                    [t.get("label", "") for t in ev.get("tags", [])],
                ) in sports_set
            ]

        # Fetch full event details in parallel (list endpoint may not include markets)
        slugs = [ev.get("slug") for ev in raw_events if ev.get("slug")]
        detailed = await asyncio.gather(*[self.get_event(s) for s in slugs], return_exceptions=True)

        events = []
        for raw in detailed:
            if isinstance(raw, Exception) or raw is None:
                continue
            try:
                events.append(self.parse_event(raw))
            except Exception as e:
                log.warning(f"Failed to parse event: {e}")

        return events
