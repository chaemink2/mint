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


# 2026-06-17: dashboard 추천 시그널 탭 현재가 표시용. KR(KIS)과 시그니처 통일.
# Note: annotation 없이 dict — Streamlit Cloud python 3.8 호환 (PEP 585 회피).
_PRICE_CACHE = {}  # ticker -> (ts, price)
_PRICE_CACHE_TTL_SEC = 60


def get_current_price(ticker: str) -> Optional[float]:
    """NASDAQ 현재가 (정규장 마감 후엔 종가). yfinance 1분봉 last 또는 fast_info.
    실패 시 None — 호출자는 graceful skip. 60초 캐시.
    """
    import time as _t
    now = _t.time()
    cached = _PRICE_CACHE.get(ticker)
    if cached and now - cached[0] < _PRICE_CACHE_TTL_SEC:
        return cached[1]
    try:
        import yfinance as yf
        tk = yf.Ticker(ticker)
        # 1순위: fast_info (빠름, 일부 종목 누락 가능)
        try:
            fi = tk.fast_info
            p = float(fi.get("last_price") or 0)
            if p > 0:
                _PRICE_CACHE[ticker] = (now, p)
                return p
        except Exception:
            pass
        # 2순위: 1분봉 last (정규장 후엔 일봉 last close)
        hist = tk.history(period="1d", interval="1m", auto_adjust=False)
        if hist is not None and not hist.empty:
            p = float(hist["Close"].iloc[-1])
            if p > 0:
                _PRICE_CACHE[ticker] = (now, p)
                return p
    except Exception as e:
        log.debug("yfinance current price fetch failed (%s): %s", ticker, e)
    return None


def get_minute_bars(
    ticker: str, interval: str = "5m", period: str = "5d"
) -> Optional[pd.DataFrame]:
    """yfinance 분봉 → KIS get_minute_bars와 동일한 컬럼 시그니처.

    interval: '1m'/'2m'/'5m'/'15m'/'30m'/'60m'. yfinance 1m=7d 한도, 5m=60d.
    period: '1d'/'5d'/'1mo' 등.

    반환: DataFrame[ts, open, high, low, close, volume] (시간 정순) 또는 None.

    KIS 분봉(get_minute_bars)와 동일 인터페이스 — minute_rule.py가 시장 무관
    동일 평가 함수 (evaluate_minute_first_discovery)를 호출할 수 있게 함.
    """
    try:
        import yfinance as yf
    except ImportError:
        log.warning("yfinance not installed — get_minute_bars 불가")
        return None

    try:
        raw = yf.download(
            ticker, interval=interval, period=period,
            progress=False, auto_adjust=True,
        )
    except Exception as e:
        log.debug("yfinance minute fetch failed for %s: %s", ticker, e)
        return None

    if raw is None or raw.empty:
        return None

    if isinstance(raw.columns, pd.MultiIndex):
        raw.columns = raw.columns.get_level_values(0)

    rename_map = {"Open": "open", "High": "high", "Low": "low",
                  "Close": "close", "Volume": "volume"}
    raw = raw.rename(columns=rename_map)
    for col in ("open", "high", "low", "close", "volume"):
        if col not in raw.columns:
            return None

    rows = []
    for ts, row in raw.iterrows():
        try:
            o = float(row["open"])
            h = float(row["high"])
            l = float(row["low"])
            c = float(row["close"])
            v = float(row["volume"]) if pd.notna(row["volume"]) else 0.0
        except (TypeError, ValueError):
            continue
        if c <= 0:
            continue
        rows.append({"ts": str(ts), "open": o, "high": h,
                     "low": l, "close": c, "volume": v})

    if not rows:
        return None

    df = pd.DataFrame(rows)
    return df.reset_index(drop=True)
