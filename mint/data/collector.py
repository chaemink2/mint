"""
Unified data collector — routes by market to the appropriate client.
"""
from typing import List, Optional

import pandas as pd

from config.settings import config
from data import krx_client, us_client
from data.universe import get_watchlist

KR_MARKETS = {"KOSPI", "KOSDAQ"}


def fetch_bars(ticker: str, market: str, days: int = 60) -> pd.DataFrame:
    market = market.upper()
    if market in KR_MARKETS:
        return krx_client.fetch_daily_bars(ticker, market, days=days)
    if market == "NASDAQ":
        return us_client.fetch_daily_bars(ticker, market, days=days)
    raise ValueError(f"Unsupported market: {market}")


def _resolve_size(n: Optional[int]) -> Optional[int]:
    """명시값이 우선, 없으면 config.ops.watchlist_size."""
    return n if n is not None else config.ops.watchlist_size


def fetch_market_watchlist(
    market: str, days: int = 60, n: Optional[int] = None
) -> dict[str, pd.DataFrame]:
    market = market.upper()
    tickers = get_watchlist(market, n=_resolve_size(n))
    return {t: fetch_bars(t, market, days=days) for t in tickers}


def fetch_all_kr_watchlists(
    days: int = 60, n: Optional[int] = None
) -> dict[str, pd.DataFrame]:
    out = {}
    for market in ("KOSPI", "KOSDAQ"):
        out.update(fetch_market_watchlist(market, days=days, n=n))
    return out


def fetch_watchlists_by_markets(
    markets: List[str], days: int = 60, n: Optional[int] = None
) -> dict[str, pd.DataFrame]:
    """Generalized: KOSPI/KOSDAQ/NASDAQ 임의 조합."""
    out: dict[str, pd.DataFrame] = {}
    for m in markets:
        out.update(fetch_market_watchlist(m, days=days, n=n))
    return out
