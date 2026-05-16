"""
동적 워치리스트 — pykrx로 시총 상위 N종목 추출.

설계:
  - n 미지정이면 config.markets.py의 정적 리스트 사용 (호환)
  - n 지정 시 pykrx 시총 상위 N개. JSON 캐시 24h TTL.
  - pykrx 실패 시 정적 리스트 폴백.

캐시 위치: mint/data/.universe_cache.json
"""
from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timedelta
from typing import List, Optional

log = logging.getLogger("mint.universe")

_CACHE_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), ".universe_cache.json"
)
_CACHE_TTL_HOURS = 24


def _load_cache() -> dict:
    if not os.path.exists(_CACHE_PATH):
        return {}
    try:
        with open(_CACHE_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _save_cache(cache: dict) -> None:
    try:
        with open(_CACHE_PATH, "w", encoding="utf-8") as f:
            json.dump(cache, f, ensure_ascii=False, indent=2)
    except Exception as e:
        log.debug("universe cache save failed: %s", e)


def _fetch_top_n_kr(market: str, n: int) -> List[str]:
    """pykrx로 시총 상위 N개 ticker. 최근 영업일 기준."""
    from data.krx_client import _silence_pykrx  # pykrx print 차단
    from pykrx import stock

    df = None
    for delta in range(0, 10):  # 최근 영업일 탐색
        d = (datetime.now() - timedelta(days=delta)).strftime("%Y%m%d")
        try:
            with _silence_pykrx():
                df = stock.get_market_cap_by_ticker(d, market=market)
            if df is not None and not df.empty:
                break
        except Exception:
            continue

    if df is None or df.empty:
        return []

    if "시가총액" not in df.columns:
        log.warning("Unexpected pykrx market_cap columns: %s", df.columns.tolist())
        return []

    df_sorted = df.sort_values("시가총액", ascending=False)
    return [str(t).zfill(6) for t in df_sorted.head(n).index.tolist()]


def get_watchlist(market: str, n: Optional[int] = None) -> List[str]:
    """
    market: KOSPI | KOSDAQ | NASDAQ
    n: None이면 정적 리스트. 숫자면 시총 상위 n개 (KR만 지원).
    """
    # 정적 리스트 (폴백·NASDAQ용)
    from config.markets import KOSDAQ_WATCHLIST, KOSPI_WATCHLIST, NASDAQ_WATCHLIST

    static = {
        "KOSPI": KOSPI_WATCHLIST,
        "KOSDAQ": KOSDAQ_WATCHLIST,
        "NASDAQ": NASDAQ_WATCHLIST,
    }.get(market, [])

    if n is None:
        return list(static)

    if market == "NASDAQ":
        # 동적 확장은 yfinance 비싸서 미지원 — static 그대로
        return list(static)[:n] if n <= len(static) else list(static)

    if n <= 0:
        return []

    # 캐시 hit?
    cache = _load_cache()
    key = f"{market}_top_{n}"
    entry = cache.get(key)
    if entry:
        try:
            ts = datetime.fromisoformat(entry["fetched_at"])
            if datetime.now() - ts < timedelta(hours=_CACHE_TTL_HOURS):
                return list(entry["tickers"])
        except Exception:
            pass

    log.info("Fetching top %d %s by market cap (pykrx)...", n, market)
    tickers = _fetch_top_n_kr(market, n)
    if not tickers:
        log.warning("Dynamic fetch failed — falling back to static (%d tickers)", len(static))
        return list(static)

    cache[key] = {"tickers": tickers, "fetched_at": datetime.now().isoformat()}
    _save_cache(cache)
    log.info("Got %d %s tickers, cached %dh", len(tickers), market, _CACHE_TTL_HOURS)
    return tickers


def clear_universe_cache() -> None:
    if os.path.exists(_CACHE_PATH):
        os.remove(_CACHE_PATH)
