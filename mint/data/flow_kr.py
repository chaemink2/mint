"""
외국인/기관 수급 데이터 (KR) — Naver Finance 종목별 페이지 스크래핑.

진짜 KR 알파 카드 C1 (2026-06-02).
배경:
  - pykrx의 `get_market_net_purchases_of_equities`는 KRX 인증 필요 (5/18 도입)
  - KRX_ID/KRX_PW 없는 GHA 환경에서 빈 결과 → Naver 폴백
  - Naver `/item/frgn.naver?code=` 표에서 일별 외국인/기관 순매매 추출

호출 패턴:
  - run_rule_scan에서 시그널 후보(분봉+ML 통과한 ~30종목)만 fetch
  - 600 종목 전체 fetch는 GHA timeout 위험이라 회피
  - in-process 60초 캐시로 동일 scan 내 중복 호출 방지

반환:
  get_flow_summary(ticker, days=5) → {
    'foreign_net_5d': int (5일 누적 외국인 순매매 주식수, +=매수우위),
    'inst_net_5d': int  (5일 누적 기관 순매매),
    'foreign_pct': float (외국인 보유비율 % 최신),
    'days_used': int (실제 사용 일수, 휴일 제외),
  }  또는 None (fetch 실패)
"""
from __future__ import annotations

import logging
import re
import time
from typing import Dict, Optional, Tuple

log = logging.getLogger("mint.flow_kr")

_NAVER_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
_CACHE: Dict[str, Tuple[float, dict]] = {}
_CACHE_TTL_SEC = 60.0


def _parse_int(s: str) -> Optional[int]:
    """'+3,088,203' / '-11,016,912' / '' → int 또는 None."""
    if not s:
        return None
    s = s.replace(",", "").replace("+", "").strip()
    try:
        return int(s)
    except ValueError:
        return None


def _parse_pct(s: str) -> Optional[float]:
    """'48.11%' → 48.11 float."""
    if not s:
        return None
    s = s.replace("%", "").strip()
    try:
        return float(s)
    except ValueError:
        return None


def _fetch_flow_table(ticker: str) -> Optional[list]:
    """Naver frgn.naver 페이지 → 일별 데이터 행 리스트 (가장 최근 먼저).

    Naver 표 컬럼 순서:
      0: 날짜
      1: 종가
      2: 전일대비 (상승/하락 텍스트)
      3: 등락률
      4: 거래량
      5: 기관 순매매 (주)
      6: 외국인 순매매 (주)
      7: 외국인 보유주수
      8: 외국인 보유비율
    """
    try:
        import requests
        from bs4 import BeautifulSoup
    except ImportError:
        log.warning("requests/beautifulsoup4 미설치 — flow_kr fallback 불가")
        return None

    code = str(ticker).strip().zfill(6)
    url = f"https://finance.naver.com/item/frgn.naver?code={code}"
    try:
        r = requests.get(url, headers={"User-Agent": _NAVER_UA}, timeout=8)
        if r.status_code != 200:
            log.debug("Naver frgn %s status=%d", code, r.status_code)
            return None
    except Exception as e:
        log.debug("Naver frgn %s fetch failed: %s", code, e)
        return None

    soup = BeautifulSoup(r.text, "html.parser")
    tables = soup.select("table.type2")
    if len(tables) < 2:
        return None
    # 마지막 table.type2가 일별 외국인/기관 표
    rows = tables[-1].select("tr")
    parsed: list = []
    for row in rows:
        cells = [c.get_text(strip=True) for c in row.select("td")]
        if len(cells) < 9:
            continue
        date_str = cells[0]
        # 날짜 형식 'YYYY.MM.DD' 만 유효 데이터 row
        if not re.match(r"\d{4}\.\d{2}\.\d{2}", date_str):
            continue
        inst_net = _parse_int(cells[5])
        foreign_net = _parse_int(cells[6])
        foreign_pct = _parse_pct(cells[8])
        if inst_net is None and foreign_net is None:
            continue
        parsed.append({
            "date": date_str,
            "inst_net": inst_net or 0,
            "foreign_net": foreign_net or 0,
            "foreign_pct": foreign_pct,
        })
    return parsed


def get_flow_summary(ticker: str, days: int = 5) -> Optional[dict]:
    """N일 누적 외국인/기관 순매매 합계 + 외국인 최신 보유 비율.

    in-process 60초 캐시. 같은 scan run에서 동일 종목 중복 호출 시 즉시 반환.
    """
    cache_key = f"{ticker}_{days}"
    now = time.time()
    cached = _CACHE.get(cache_key)
    if cached and (now - cached[0]) < _CACHE_TTL_SEC:
        return cached[1]

    rows = _fetch_flow_table(ticker)
    if not rows:
        return None

    # 가장 최근 days일 합계 (휴일 자동 제외 — 표에 휴일은 row 없음)
    head = rows[:days]
    foreign_net_sum = sum(r["foreign_net"] for r in head)
    inst_net_sum = sum(r["inst_net"] for r in head)
    foreign_pct_latest = None
    for r in head:
        if r["foreign_pct"] is not None:
            foreign_pct_latest = r["foreign_pct"]
            break

    result = {
        "foreign_net_5d": foreign_net_sum,
        "inst_net_5d": inst_net_sum,
        "foreign_pct": foreign_pct_latest,
        "days_used": len(head),
    }
    _CACHE[cache_key] = (now, result)
    return result


def clear_cache() -> None:
    _CACHE.clear()
