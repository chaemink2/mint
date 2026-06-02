"""
동적 워치리스트 — 시총 상위 N종목 추출.

데이터 소스 우선순위:
  KR (KOSPI/KOSDAQ):
    1. KRX_ID/KRX_PW 환경변수 있으면 pykrx (인증 경로)
    2. Naver Finance HTML 스크래핑 (시가총액 랭킹 페이지, 인증 불필요)
    3. config.markets.py의 정적 리스트 폴백

  NASDAQ:
    1. Wikipedia NASDAQ-100 스크래핑 (인증 불필요, 100종목 cap)
    2. config.markets.py의 NASDAQ_WATCHLIST 정적 폴백

캐시 위치: mint/data/.universe_cache.json (24h TTL)

배경:
  2026-05경 pykrx 1.2.8부터 data.krx.co.kr 로그인이 필수가 됨.
  KRX_ID/KRX_PW 없으면 시총 랭킹 API 실패 → Naver를 1차 소스로 사용.

  NASDAQ은 yfinance Ticker.info 호출이 종목당 1~2초 (200 종목 = 5분+) →
  GHA 부담. Wikipedia NASDAQ-100 페이지 시드 그대로 사용 (시총 가중치
  기준 자체가 NASDAQ-100 indexing → 사실상 시총 상위 100).
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


_NASDAQ100_URL = "https://en.wikipedia.org/wiki/Nasdaq-100"
_SP500_URL = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"
_SP400_URL = "https://en.wikipedia.org/wiki/List_of_S%26P_400_companies"  # mid-cap
_SP600_URL = "https://en.wikipedia.org/wiki/List_of_S%26P_600_companies"  # small-cap
_NASDAQTRADER_URL = "https://www.nasdaqtrader.com/dynamic/SymDir/nasdaqlisted.txt"


def _fetch_sp_nasdaq_listed(url: str, label: str) -> List[str]:
    """S&P 500/400/600 Wikipedia 페이지에서 NASDAQ-listed 종목만 추출.

    표 구조 동일: <td><a href="https://www.nasdaq.com/...">TICKER</a></td>
    NASDAQ exchange URL 필터로 NASDAQ-listed만 골라냄.
    """
    try:
        import requests
    except ImportError:
        return []
    try:
        r = requests.get(url, headers={"User-Agent": _NAVER_UA}, timeout=15)
        if r.status_code != 200:
            log.warning("Wikipedia %s status=%d", label, r.status_code)
            return []
    except Exception as e:
        log.warning("Wikipedia %s fetch failed: %s", label, e)
        return []

    html = r.text
    table_idx = html.find('id="constituents"')
    if table_idx == -1:
        return []
    table_end = html.find('</table>', table_idx)
    table_html = html[table_idx:table_end] if table_end > 0 else html[table_idx:]

    candidates = re.findall(
        r'<a rel="nofollow" class="external text" href="https://www\.nasdaq\.com/[^"]+">([A-Z][A-Z\.\-]{0,5})</a>',
        table_html,
    )
    seen = set()
    tickers: List[str] = []
    for t in candidates:
        sym = t.replace(".", "-")
        if sym in seen:
            continue
        seen.add(sym)
        tickers.append(sym)
    return tickers


def _fetch_sp500_nasdaq_listed() -> List[str]:
    """S&P 500 NASDAQ-listed (역호환 wrapper)."""
    return _fetch_sp_nasdaq_listed(_SP500_URL, "S&P500")


# 파생 증권 / 우선주 / 채권 식별 키워드 (소문자 비교)
_NASDAQ_NAME_BLOCKLIST = (
    " - rights", " - unit", " - warrant", "- preferred", " depositary",
    " notes due", "subordinate", " debenture", "depositary share",
)


def _fetch_nasdaqlisted_common(market_categories: tuple = ("Q", "G")) -> List[str]:
    """nasdaqtrader.com 공식 nasdaqlisted.txt → 일반 보통주만 필터.

    필터:
      - Test Issue=N, ETF=N
      - Market Category in market_categories (기본 Q + G)
        · Q = NASDAQ Global Select Market (~1291 우량주)
        · G = NASDAQ Global Market (~676 중간)
        · S = NASDAQ Capital Market (소형/페니 — 기본 제외)
      - Security Name에 Rights/Units/Warrants/Preferred/Notes 등 파생 키워드 제외

    반환: ticker 리스트 (알파벳 순). 시총 정렬 X — 후속 필터(가격/거래량)는 운영 단에서.
    """
    try:
        import requests
    except ImportError:
        return []

    try:
        r = requests.get(
            _NASDAQTRADER_URL,
            headers={"User-Agent": _NAVER_UA},
            timeout=15,
        )
        if r.status_code != 200:
            log.warning("nasdaqtrader %s status=%d", _NASDAQTRADER_URL, r.status_code)
            return []
    except Exception as e:
        log.warning("nasdaqtrader fetch failed: %s", e)
        return []

    import csv
    import io

    reader = csv.DictReader(io.StringIO(r.text), delimiter="|")
    tickers: List[str] = []
    for row in reader:
        sym = (row.get("Symbol") or "").strip()
        if not sym or sym.startswith("File Creation"):
            continue
        if row.get("Test Issue") == "Y" or row.get("ETF") == "Y":
            continue
        if row.get("Market Category") not in market_categories:
            continue
        name = (row.get("Security Name") or "").lower()
        if any(bad in name for bad in _NASDAQ_NAME_BLOCKLIST):
            continue
        # yfinance 호환: '.' → '-' (e.g. BRK.B → BRK-B)
        tickers.append(sym.replace(".", "-"))
    return tickers


def _fetch_top_n_nasdaq_wikipedia(n: int) -> List[str]:
    """Wikipedia NASDAQ-100 + (n > 100 시) S&P 500 NASDAQ-listed 추출.

    1단계: NASDAQ-100 100종목 시드 (시총 가중 자체가 시총 상위 100).
    2단계: n > 100 시 S&P 500 ∩ NASDAQ-listed 추가 (dedup).

    결과: KR 200종목 워치리스트와 비교 가능한 규모 (~200~250).
    """
    try:
        import requests
    except ImportError:
        log.warning("requests 미설치 — NASDAQ Wikipedia fallback 불가")
        return []

    try:
        r = requests.get(_NASDAQ100_URL,
                         headers={"User-Agent": _NAVER_UA}, timeout=15)
        if r.status_code != 200:
            log.warning("Wikipedia NASDAQ-100 status=%d", r.status_code)
            return []
    except Exception as e:
        log.warning("Wikipedia NASDAQ-100 fetch failed: %s", e)
        return []

    html = r.text
    # Current_components 섹션부터 다음 섹션 전까지만 잘라 잘못된 매치 줄임
    section_anchors = [
        'id="Current_components"',
        'id="Components"',
        'id="Component_companies"',
    ]
    start = -1
    for anchor in section_anchors:
        idx = html.find(anchor)
        if idx != -1:
            start = idx
            break
    if start == -1:
        start = 0
    # 다음 섹션 헤더로 컷
    next_anchors = [
        'id="Component_changes"',
        'id="Historical_components"',
        'id="References"',
        'id="See_also"',
        'id="External_links"',
    ]
    cut_candidates = []
    for anchor in next_anchors:
        idx = html.find(anchor, start + 1)
        if idx > 0:
            cut_candidates.append(idx)
    end = min(cut_candidates) if cut_candidates else len(html)
    section = html[start:end] if start >= 0 else html

    # 표 자체 ID = "constituents". 그 안에서 각 row의 첫 td = ticker text.
    # 패턴: <td>TICKER</td>\s*<td><a href="/wiki/...">Company</a>...
    table_idx = section.find('id="constituents"')
    if table_idx == -1:
        table_idx = section.find('wikitable sortable')
    table_end = section.find('</table>', table_idx) if table_idx >= 0 else -1
    table_html = section[table_idx:table_end] if table_idx >= 0 and table_end > 0 else section

    candidates = re.findall(
        r'<td>([A-Z][A-Z\.\-]{0,5})</td>\s*<td><a href="/wiki/[^"]+"',
        table_html,
    )

    tickers: List[str] = []
    seen = set()
    for t in candidates:
        # BRK.B 같은 경우 yfinance는 BRK-B 형태 — NASDAQ-100엔 거의 없으나 안전 변환
        sym = t.replace(".", "-")
        if not sym.replace("-", "").isalpha():
            continue
        if len(sym) > 6:
            continue
        if sym in seen:
            continue
        seen.add(sym)
        tickers.append(sym)

    if not tickers:
        log.warning("Wikipedia NASDAQ-100 parse returned empty — pattern may have changed")
        return []

    # n <= 100이면 NASDAQ-100만으로 충분
    if n <= 100:
        return tickers[:n]

    # n > 100이면 S&P 500/400/600 + nasdaqlisted Q/G cascade (dedup)
    # 2026-06-02: S&P 500까지로 ~500 종목, nasdaqlisted Q/G까지로 1500+ 가능
    log.info("NASDAQ-100 %d + cascade (S&P 500/400/600 + nasdaqlisted Q/G) 목표 n=%d...",
             len(tickers), n)
    seen = set(tickers)

    # 1순위: S&P 시드 (지수 편입 검증된 우량주)
    for url, label in [
        (_SP500_URL, "S&P500"),
        (_SP400_URL, "S&P400"),
        (_SP600_URL, "S&P600"),
    ]:
        if len(tickers) >= n:
            break
        sp_list = _fetch_sp_nasdaq_listed(url, label)
        added = 0
        for t in sp_list:
            if t in seen:
                continue
            seen.add(t)
            tickers.append(t)
            added += 1
            if len(tickers) >= n:
                break
        log.info("%s에서 추가 %d 종목 (누적 %d)", label, added, len(tickers))

    # 2순위: nasdaqlisted.txt 우량 cascade (Q → G).
    # 시총 정렬 X — 알파벳 순. 운영 단에서 가격/거래량 사전 필터 필요.
    # 사용자 결정 (2026-06-02): 500 → 1500까지 확대. Q+G 약 1967종목 풀.
    if len(tickers) < n:
        composite = _fetch_nasdaqlisted_common(market_categories=("Q", "G"))
        added = 0
        for t in composite:
            if t in seen:
                continue
            seen.add(t)
            tickers.append(t)
            added += 1
            if len(tickers) >= n:
                break
        log.info("nasdaqlisted Q+G에서 추가 %d 종목 (누적 %d)", added, len(tickers))

    return tickers[:n]


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

    if market == "NASDAQ":
        log.info("Fetching NASDAQ-100 tickers from Wikipedia (target n=%d, cap=100)...", n)
        tickers = _fetch_top_n_nasdaq_wikipedia(n)
    else:
        log.info("Fetching top %d %s by market cap (pykrx/Naver)...", n, market)
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
