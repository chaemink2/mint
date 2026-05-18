"""
동적 워치리스트 — 시총 상위 N종목 추출.

데이터 소스 우선순위:
  1. KRX_ID/KRX_PW 환경변수 있으면 pykrx (인증 경로)
  2. Naver Finance HTML 스크래핑 (시가총액 랭킹 페이지, 인증 불필요)
  3. config.markets.py의 정적 리스트 폴백

캐시 위치: mint/data/.universe_cache.json (24h TTL)

배경:
  2026-05경 pykrx 1.2.8부터 data.krx.co.kr 로그인이 필수가 됨.
  KRX_ID/KRX_PW 없으면 시총 랭킹 API 실패 → Naver를 1차 소스로 사용.
"""
from __future__ import annotations

import json
import logging
import os
import re
from datetime import datetime, timedelta
from typing import List, Optional

log = logging.getLogger("mint.universe")

_NAVER_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
_NAVER_PAGE_SIZE = 50  # 시세 랭킹 페이지당 50개

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


def _fetch_top_n_pykrx(market: str, n: int) -> List[str]:
    """pykrx로 시총 상위 N개 ticker (KRX 로그인 필요)."""
    from data.krx_client import _silence_pykrx
    from pykrx import stock

    df = None
    for delta in range(0, 10):
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


def _fetch_top_n_naver(market: str, n: int) -> List[str]:
    """Naver Finance 시가총액 랭킹 페이지 스크래핑. 인증 불필요.

    KOSPI = sosok=0, KOSDAQ = sosok=1. 페이지당 50종목.
    """
    try:
        import requests
    except ImportError:
        log.warning("requests 미설치 — Naver fallback 불가")
        return []

    sosok = {"KOSPI": 0, "KOSDAQ": 1}.get(market)
    if sosok is None:
        return []

    pages_needed = (n + _NAVER_PAGE_SIZE - 1) // _NAVER_PAGE_SIZE
    tickers: List[str] = []
    seen = set()

    for page in range(1, pages_needed + 1):
        url = (
            f"https://finance.naver.com/sise/sise_market_sum.naver"
            f"?sosok={sosok}&page={page}"
        )
        try:
            r = requests.get(url, headers={"User-Agent": _NAVER_UA}, timeout=10)
            if r.status_code != 200:
                log.warning("Naver page %d %s status=%d", page, market, r.status_code)
                break
            codes = re.findall(r"/item/main\.naver\?code=(\d{6})", r.text)
            for c in codes:
                if c not in seen:
                    seen.add(c)
                    tickers.append(c)
            if not codes:
                break
        except Exception as e:
            log.warning("Naver fetch page %d failed: %s", page, e)
            break

    return tickers[:n]


def _fetch_top_n_kr(market: str, n: int) -> List[str]:
    """시총 상위 N개 ticker. KRX_ID 있으면 pykrx, 아니면 Naver."""
    if os.getenv("KRX_ID") and os.getenv("KRX_PW"):
        try:
            tickers = _fetch_top_n_pykrx(market, n)
            if tickers:
                log.info("Source: pykrx (authenticated)")
                return tickers
            log.warning("pykrx returned empty — falling back to Naver")
        except Exception as e:
            log.warning("pykrx failed (%s) — falling back to Naver", e)

    tickers = _fetch_top_n_naver(market, n)
    if tickers:
        log.info("Source: Naver Finance — %d %s tickers", len(tickers), market)
    return tickers


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
