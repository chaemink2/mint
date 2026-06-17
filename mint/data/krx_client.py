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


_NAME_FILE_CACHE_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), ".stock_names.json"
)
_NAME_MEM_CACHE: dict[str, str] = {}


def _load_name_cache() -> dict[str, str]:
    if _NAME_MEM_CACHE:
        return _NAME_MEM_CACHE
    if not os.path.exists(_NAME_FILE_CACHE_PATH):
        return _NAME_MEM_CACHE
    try:
        import json
        with open(_NAME_FILE_CACHE_PATH, "r", encoding="utf-8") as f:
            _NAME_MEM_CACHE.update(json.load(f))
    except Exception:
        pass
    return _NAME_MEM_CACHE


def _save_name_cache() -> None:
    try:
        import json
        with open(_NAME_FILE_CACHE_PATH, "w", encoding="utf-8") as f:
            json.dump(_NAME_MEM_CACHE, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


def _fetch_name_naver(ticker: str) -> Optional[str]:
    """Naver Finance 종목 페이지에서 종목명 추출. KRX 인증 불필요."""
    try:
        import re
        import requests
        r = requests.get(
            f"https://finance.naver.com/item/main.naver?code={ticker}",
            headers={"User-Agent": "Mozilla/5.0"},
            timeout=5,
        )
        if r.status_code != 200:
            return None
        # <title>에스엠 - 네이버페이 증권</title> 또는 비슷한 패턴
        m = re.search(r"<title>\s*([^<:|\-]+?)\s*[-:|]", r.text)
        if m:
            name = m.group(1).strip()
            # "네이버페이 증권" 같은 헤더 페이지 방어
            if name and "증권" not in name and "네이버" not in name and len(name) <= 30:
                return name
        return None
    except Exception:
        return None


# 2026-06-17: dashboard 추천 시그널 탭 현재가 fallback. KIS 키 없는 환경
# (Streamlit Cloud / 사용자 PC 일부)에서 작동. Naver Finance 스크래핑.
_NAVER_PRICE_CACHE: dict[str, tuple[float, float]] = {}  # ticker -> (ts, price)
_NAVER_PRICE_TTL_SEC = 60


def get_current_price_naver(ticker: str) -> Optional[float]:
    """Naver Finance 모바일 API로 현재가 추출 (KIS 인증 불필요).

    엔드포인트: https://m.stock.naver.com/api/stock/{ticker}/basic
    응답 closePrice가 정규장 중에는 현재가, 마감 후엔 종가.
    market_index.py와 동일 패턴. 60초 캐시.
    """
    import time as _t
    now = _t.time()
    cached = _NAVER_PRICE_CACHE.get(ticker)
    if cached and now - cached[0] < _NAVER_PRICE_TTL_SEC:
        return cached[1]
    try:
        import requests
        r = requests.get(
            f"https://m.stock.naver.com/api/stock/{ticker}/basic",
            headers={"User-Agent": "Mozilla/5.0"},
            timeout=5,
        )
        if r.status_code != 200:
            return None
        d = r.json()
        raw = str(d.get("closePrice") or "").replace(",", "")
        if not raw:
            return None
        price = float(raw)
        if price > 0:
            _NAVER_PRICE_CACHE[ticker] = (now, price)
            return price
    except Exception as e:
        log.debug("Naver current price fetch failed (%s): %s", ticker, e)
    return None


def get_stock_name(ticker: str) -> str:
    """종목명 조회. 캐시 → pykrx → Naver Finance → ticker 폴백."""
    ticker = _normalize_ticker(ticker)

    cache = _load_name_cache()
    cached = cache.get(ticker)
    if cached:
        return cached

    # 1) pykrx (KRX 인증 있을 때만 의미)
    try:
        with _silence_pykrx():
            name = stock.get_market_ticker_name(ticker)
        if name and name != ticker:
            cache[ticker] = name
            _save_name_cache()
            return name
    except Exception:
        pass

    # 2) Naver Finance 폴백 (인증 불필요)
    name = _fetch_name_naver(ticker)
    if name:
        cache[ticker] = name
        _save_name_cache()
        return name

    return ticker
