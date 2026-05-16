"""
pykrx wrapper — KOSPI/KOSDAQ daily OHLCV → canonical bars.
"""
import contextlib
import io
import os
from datetime import datetime, timedelta
from typing import List, Optional

import pandas as pd
from pykrx import stock

from data.schema import BAR_COLUMNS, validate_bars


@contextlib.contextmanager
def _silence_pykrx():
    """pykrx 내부 dataframe_empty_handler가 print()로 직접 에러를 찍어 시끄러움.
    조용히 삼키고 None 폴백 처리."""
    with open(os.devnull, "w", encoding="utf-8") as devnull:
        with contextlib.redirect_stdout(devnull):
            yield


def _normalize_ticker(ticker: str) -> str:
    return str(ticker).strip().zfill(6)


def fetch_daily_bars(
    ticker: str,
    market: str,
    days: int = 60,
    end_date: Optional[datetime] = None,
) -> pd.DataFrame:
    """
    Fetch daily OHLCV for a Korean ticker.
    market: KOSPI | KOSDAQ (used for metadata only; pykrx uses ticker code)
    """
    ticker = _normalize_ticker(ticker)
    end = end_date or datetime.now()
    start = end - timedelta(days=days + 30)

    start_s = start.strftime("%Y%m%d")
    end_s = end.strftime("%Y%m%d")

    try:
        raw = stock.get_market_ohlcv_by_date(start_s, end_s, ticker)
    except Exception:
        return pd.DataFrame(columns=BAR_COLUMNS)

    if raw is None or raw.empty:
        return pd.DataFrame(columns=BAR_COLUMNS)

    raw = raw.tail(days).copy()
    raw = raw.rename(
        columns={
            "시가": "open",
            "고가": "high",
            "저가": "low",
            "종가": "close",
            "거래량": "volume",
        }
    )
    for col in ("open", "high", "low", "close", "volume"):
        if col not in raw.columns:
            return pd.DataFrame(columns=BAR_COLUMNS)

    rows = []
    for ts, row in raw.iterrows():
        ts_local = pd.Timestamp(ts).tz_localize("Asia/Seoul")
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
                "source": "pykrx",
                "is_adjusted": True,
                "currency": "KRW",
            }
        )

    return validate_bars(pd.DataFrame(rows))


def fetch_watchlist_bars(
    tickers: List[str],
    market: str,
    days: int = 60,
) -> dict[str, pd.DataFrame]:
    return {t: fetch_daily_bars(t, market, days=days) for t in tickers}


def get_stock_name(ticker: str) -> str:
    ticker = _normalize_ticker(ticker)
    try:
        with _silence_pykrx():
            name = stock.get_market_ticker_name(ticker)
        return name or ticker
    except Exception:
        return ticker
