"""
시장 regime 산출 — KOSPI / KOSDAQ 각각 독립.

5단계 카테고리:
  STRONG_BULL  · BULL · SIDEWAYS · BEAR · STRONG_BEAR

규칙 (KOSPI/KOSDAQ 각각 동일):
  - ret_5d : 최근 5거래일 등락률
  - ret_20d : 최근 20거래일 등락률
  - ma20_dist : (close - MA20) / MA20
  - volatility : 최근 20일 std(daily return)

  composite_score = ret_5d * 0.5 + ret_20d * 0.3 + ma20_dist * 0.2
  단순 가중합. 5d 비중 가장 큼 (사용자 직관 "최근 분위기").

  카테고리 (composite_score 기준):
    >= +0.04 → STRONG_BULL
    >= +0.01 → BULL
    > -0.01  → SIDEWAYS
    > -0.04  → BEAR
    else     → STRONG_BEAR

배경:
  - 사용자 직관(2026-05-22): "상승장엔 다 오르고 하락장엔 다 떨어진다 →
    지수 추종이 종목 선택보다 더 큰 효과". 본 모듈은 dynamic_exit에 input.
  - KOSPI 종목과 KOSDAQ 종목은 다른 regime 적용 (시장 변동성 다름).
  - 캐시 60초 — scan마다 fetch 비용 절감.
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Dict, Optional

import pandas as pd

log = logging.getLogger("mint.regime")

_CACHE: Dict[str, tuple] = {}  # market -> (ts, RegimeInfo)
_CACHE_TTL_SEC = 60


REGIME_LABELS = ("STRONG_BULL", "BULL", "SIDEWAYS", "BEAR", "STRONG_BEAR")
REGIME_EMOJI = {
    "STRONG_BULL": "🟢🟢",
    "BULL": "🟢",
    "SIDEWAYS": "⚪",
    "BEAR": "🔴",
    "STRONG_BEAR": "🔴🔴",
}
REGIME_KO = {
    "STRONG_BULL": "강한 상승",
    "BULL": "상승",
    "SIDEWAYS": "횡보",
    "BEAR": "하락",
    "STRONG_BEAR": "강한 하락",
}


@dataclass
class RegimeInfo:
    market: str  # 'KOSPI' | 'KOSDAQ'
    label: str   # REGIME_LABELS 중 하나
    score: float
    ret_5d: float
    ret_20d: float
    ma20_dist: float
    volatility: float

    def emoji(self) -> str:
        return REGIME_EMOJI.get(self.label, "⚪")

    def ko(self) -> str:
        return REGIME_KO.get(self.label, self.label)

    def short_line(self) -> str:
        """카톡/대시보드 한 줄: "🟢 KOSPI 상승 (5d +2.4%, MA20 위)" """
        ma20_sign = "위" if self.ma20_dist > 0 else "아래"
        return (
            f"{self.emoji()} {self.market} {self.ko()} "
            f"(5d {self.ret_5d*100:+.1f}%, MA20 {ma20_sign})"
        )


# ── 내부 산출 ────────────────────────────────────────────────

def _market_index_yfinance(market: str) -> Optional[str]:
    """KOSPI/KOSDAQ 지수 yfinance ticker."""
    return {"KOSPI": "^KS11", "KOSDAQ": "^KQ11"}.get(market.upper())


def _fetch_index_bars(market: str, days: int = 40) -> Optional[pd.DataFrame]:
    """지수 일봉 fetch (yfinance — KRX 인증 우회). 실패 시 None."""
    yf_ticker = _market_index_yfinance(market)
    if not yf_ticker:
        return None
    try:
        import yfinance as yf
        # yfinance는 period로 60일 데이터 충분
        df = yf.download(yf_ticker, period=f"{days*2}d", interval="1d",
                         progress=False, auto_adjust=False)
        if df is None or df.empty:
            return None
        # MultiIndex column일 수 있음 — 평탄화
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
        return df.tail(days).copy()
    except Exception as e:
        log.debug("index bars fetch failed (%s): %s", market, e)
        return None


def _compute_regime(market: str, df: pd.DataFrame) -> Optional[RegimeInfo]:
    """일봉 → RegimeInfo. df 부족 시 None."""
    if df is None or len(df) < 21:
        return None
    # 컬럼명 호환 (pykrx '종가' / yfinance 'Close' / canonical 'close')
    if "종가" in df.columns:
        close = df["종가"].astype(float)
    elif "Close" in df.columns:
        close = df["Close"].astype(float)
    elif "close" in df.columns:
        close = df["close"].astype(float)
    else:
        return None
    if len(close) < 21:
        return None

    last = float(close.iloc[-1])
    ret_5d = last / float(close.iloc[-6]) - 1
    ret_20d = last / float(close.iloc[-21]) - 1
    ma20 = float(close.iloc[-21:-1].mean())
    ma20_dist = (last - ma20) / ma20 if ma20 > 0 else 0.0

    daily_ret = close.pct_change().tail(20)
    volatility = float(daily_ret.std()) if len(daily_ret.dropna()) >= 5 else 0.0

    composite = ret_5d * 0.5 + ret_20d * 0.3 + ma20_dist * 0.2

    if composite >= 0.04:
        label = "STRONG_BULL"
    elif composite >= 0.01:
        label = "BULL"
    elif composite > -0.01:
        label = "SIDEWAYS"
    elif composite > -0.04:
        label = "BEAR"
    else:
        label = "STRONG_BEAR"

    return RegimeInfo(
        market=market,
        label=label,
        score=float(composite),
        ret_5d=float(ret_5d),
        ret_20d=float(ret_20d),
        ma20_dist=float(ma20_dist),
        volatility=float(volatility),
    )


# ── public API ──────────────────────────────────────────────

def get_regime(market: str, force_refresh: bool = False) -> Optional[RegimeInfo]:
    """KOSPI 또는 KOSDAQ regime. 60초 캐시. fetch 실패 시 None.
    None일 때는 호출 측이 SIDEWAYS로 폴백 (보수적).
    """
    market = market.upper()
    if market not in ("KOSPI", "KOSDAQ"):
        return None

    now = time.time()
    if not force_refresh and market in _CACHE:
        ts, info = _CACHE[market]
        if now - ts < _CACHE_TTL_SEC:
            return info

    df = _fetch_index_bars(market)
    info = _compute_regime(market, df)
    if info is not None:
        _CACHE[market] = (now, info)
    return info


def get_regime_or_sideways(market: str) -> RegimeInfo:
    """fetch 실패 시 보수적 SIDEWAYS 폴백."""
    info = get_regime(market)
    if info is not None:
        return info
    return RegimeInfo(
        market=market.upper(),
        label="SIDEWAYS",
        score=0.0,
        ret_5d=0.0,
        ret_20d=0.0,
        ma20_dist=0.0,
        volatility=0.0,
    )


def both_regimes_line() -> str:
    """KOSPI + KOSDAQ regime 한 줄 (카톡/대시보드용).
    예: "🟢 KOSPI 상승 (5d +2.4%) / 🔴 KOSDAQ 하락 (5d -3.1%)"
    """
    kospi = get_regime("KOSPI")
    kosdaq = get_regime("KOSDAQ")
    parts = []
    if kospi is not None:
        parts.append(f"{kospi.emoji()} KOSPI {kospi.ko()} (5d {kospi.ret_5d*100:+.1f}%)")
    if kosdaq is not None:
        parts.append(f"{kosdaq.emoji()} KOSDAQ {kosdaq.ko()} (5d {kosdaq.ret_5d*100:+.1f}%)")
    return " / ".join(parts) if parts else "시장 regime 조회 실패"
