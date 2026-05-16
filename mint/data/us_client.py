"""
US / NASDAQ 일봉 클라이언트 — yfinance (백업/히스토리).

운영 결정 [[project-mint-decisions]]:
  - 실시간 시세는 Alpaca/Polygon (별도 발급 예정).
  - yfinance는 백업/히스토리 용도. 일봉 룰 스캔에는 충분.
  - 야간 자동 스캔 기본 OFF (MINT_US_SCAN=false).
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import List, Optional

import pandas as pd

from data.schema import BAR_COLUMNS, validate_bars

log = logging.getLogger("mint.us")


def _empty() -> pd.DataFrame:
    return pd.DataFrame(columns=BAR_COLUMNS)


def fetch_daily_bars(
    ticker: str,
    market: str = "NASDAQ",
    days: int = 60,
    end_date: Optional[datetime] = None,
) -> pd.DataFrame:
    """yfinance 일봉 → canonical bars."""
    try:
        import yfinance as yf
    except ImportError:
        log.warning("yfinance not installed — pip install yfinance")
        return _empty()

    end = end_date or datetime.now()
    start = end - timedelta(days=days + 30)

    try:
        raw = yf.download(
            ticker,
            start=start.strftime("%Y-%m-%d"),
            end=(end + timedelta(days=1)).strftime("%Y-%m-%d"),
            progress=False,
            auto_adjust=True,
        )
    except Exception as e:
        log.debug("yfinance fetch failed for %s: %s", ticker, e)
        return _empty()

    if raw is None or raw.empty:
        return _empty()

    # yfinance returns MultiIndex columns when called with a single ticker recently
    if isinstance(raw.columns, pd.MultiIndex):
        raw.columns = raw.columns.get_level_values(0)

    raw = raw.tail(days).copy()
    rename_map = {"Open": "open", "High": "high", "Low": "low", "Close": "close", "Volume": "volume"}
    raw = raw.rename(columns=rename_map)
    for col in ("open", "high", "low", "close", "volume"):
        if col not in raw.columns:
            return _empty()

    rows = []
    for ts, row in raw.iterrows():
        ts_local = pd.Timestamp(ts)
        if ts_local.tzinfo is None:
            ts_local = ts_local.tz_localize("America/New_York")
        ts_utc = ts_local.tz_convert("UTC")
        rows.append(
            {
                "ticker": ticker,
                "market": market,
                "ts_utc": ts_utc,
                "ts_local": ts_local,
                "open": float(row["open"]),
                "high": float(row["high"]),
                "low": float(row["low"]),
                "close": float(row["close"]),
                "volume": float(row["volume"]),
                "source": "yfinance",
                "is_adjusted": True,
                "currency": "USD",
            }
        )

    return validate_bars(pd.DataFrame(rows))


def fetch_watchlist_bars(
    tickers: List[str], market: str = "NASDAQ", days: int = 60
) -> dict[str, pd.DataFrame]:
    return {t: fetch_daily_bars(t, market, days=days) for t in tickers}


def get_stock_name(ticker: str) -> str:
    """yfinance info는 무겁고 흔히 실패함 — 일단 ticker 그대로 반환."""
    return ticker
