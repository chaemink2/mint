"""
시장 지수 (KOSPI/KOSDAQ) 현재가 + 등락률.

데이터 소스: Naver Finance 모바일 API (인증 불필요, JSON).
  https://m.stock.naver.com/api/index/{KOSPI|KOSDAQ}/basic

응답 핵심 필드:
  closePrice                       — 현재 지수 (문자열, comma 포함)
  compareToPreviousClosePrice      — 전일대비 (부호 포함)
  fluctuationsRatio                — 등락률 % (문자열)
  marketStatus                     — OPEN / CLOSE 등
  localTradedAt                    — 마지막 체결시각

캐시: 호출당 비싸지 않으므로 짧게 (60초). 일일 요약/스캔에 가볍게 호출 가능.
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Optional

import requests

log = logging.getLogger("mint.market_index")

_CACHE: dict[str, tuple[float, "IndexQuote"]] = {}
_CACHE_TTL = 60.0  # 초


@dataclass
class IndexQuote:
    code: str         # KOSPI | KOSDAQ
    value: float      # 현재 지수
    change: float     # 전일대비 (절대값, 부호 포함)
    change_pct: float # 등락률 %
    market_status: str  # OPEN / CLOSE
    traded_at: str      # localTradedAt 문자열

    def is_down(self) -> bool:
        return self.change_pct < 0

    def emoji(self) -> str:
        if self.change_pct >= 0.5:
            return "📈"
        if self.change_pct <= -0.5:
            return "📉"
        return "➖"


def _parse_number(s) -> float:
    """'7,208.95' / '-62.71' / '-0.86' → float. 실패 시 0.0."""
    if s is None:
        return 0.0
    try:
        return float(str(s).replace(",", "").strip())
    except (ValueError, TypeError):
        return 0.0


def get_market_index(code: str) -> Optional[IndexQuote]:
    """지수 조회 (KOSPI / KOSDAQ). 실패 시 None."""
    code = code.upper()
    if code not in ("KOSPI", "KOSDAQ"):
        return None

    # 60초 캐시
    now = time.time()
    cached = _CACHE.get(code)
    if cached and now - cached[0] < _CACHE_TTL:
        return cached[1]

    try:
        r = requests.get(
            f"https://m.stock.naver.com/api/index/{code}/basic",
            headers={"User-Agent": "Mozilla/5.0"},
            timeout=5,
        )
        if r.status_code != 200:
            log.debug("Naver index %s status=%d", code, r.status_code)
            return None
        d = r.json()
    except Exception as e:
        log.debug("Naver index %s fetch failed: %s", code, e)
        return None

    quote = IndexQuote(
        code=code,
        value=_parse_number(d.get("closePrice")),
        change=_parse_number(d.get("compareToPreviousClosePrice")),
        change_pct=_parse_number(d.get("fluctuationsRatio")),
        market_status=str(d.get("marketStatus") or ""),
        traded_at=str(d.get("localTradedAt") or ""),
    )
    if quote.value <= 0:
        return None

    _CACHE[code] = (now, quote)
    return quote


def get_market_summary() -> dict:
    """KOSPI + KOSDAQ 한 번에. 메시지 포맷 직전 사용.
    반환: {'KOSPI': IndexQuote|None, 'KOSDAQ': IndexQuote|None}
    """
    return {
        "KOSPI": get_market_index("KOSPI"),
        "KOSDAQ": get_market_index("KOSDAQ"),
    }


def format_summary_line(summary: Optional[dict] = None) -> Optional[str]:
    """일일 요약/하트비트용 한 줄 문자열.
    예: '📉 KOSPI 2,541.20 (-0.86%) · KOSDAQ 763.50 (-2.61%)'
    둘 다 fetch 실패하면 None.
    """
    summary = summary or get_market_summary()
    parts = []
    for code in ("KOSPI", "KOSDAQ"):
        q = summary.get(code)
        if q is None:
            continue
        parts.append(f"{q.emoji()} {code} {q.value:,.2f} ({q.change_pct:+.2f}%)")
    if not parts:
        return None
    return " · ".join(parts)
