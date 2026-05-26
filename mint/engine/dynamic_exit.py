"""
Dynamic exit 계산 — 종목 ATR + 시장 regime → 종목별 target/stop/holding.

배경 (2026-05-22 사용자 결정):
  - mint의 진짜 목표는 "최단시간 내 최대 수익".
  - 기존 고정값 (+3.5% / -2% / 24h)은 baseline 예시.
  - 변동 큰 종목엔 더 큰 target/stop이 자연스러움 (ATR 기반).
  - 강세장엔 길게 잡고, 약세장엔 짧게 자르기 (regime multiplier).
  - Hold 범위 6h~72h 허용 (사용자 결정 — 분봉 outcome 평가 인프라는 추후).

ML 모델은 여전히 binary classifier ("24h +3% 도달 여부"). 이 layer는
**시그널 통과 후 post-processing** — ML이 안 본 정보(ATR + regime)로
target/stop/hold를 동적 결정. ML 학습은 무영향.

Holding 6h 같은 짧은 hold은 현재 일봉 outcome 평가에 정확도 한계 있으나
일단 일봉 first-hit으로 보수적 평가 (분봉 평가는 별도 인프라 필요).
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional

from engine.market_regime import RegimeInfo, get_regime_or_sideways

log = logging.getLogger("mint.dynamic_exit")


# Regime별 multiplier (target, stop, hold)
REGIME_MULT = {
    "STRONG_BULL":  {"target": 1.5,  "stop": 0.7,  "hold": 1.5},
    "BULL":         {"target": 1.2,  "stop": 0.85, "hold": 1.25},
    "SIDEWAYS":     {"target": 1.0,  "stop": 1.0,  "hold": 1.0},
    "BEAR":         {"target": 0.75, "stop": 0.9,  "hold": 0.75},
    "STRONG_BEAR":  {"target": 0.5,  "stop": 0.85, "hold": 0.5},
}

# Baseline (ATR 기반)
ATR_TARGET_MULT = 1.5   # target = ATR * 1.5
ATR_STOP_MULT = 1.0     # stop = -ATR * 1.0
BASE_HOLD_HOURS = 24

# 최종 cap (사용자 결정 사안 — 변경 시 합의 필요)
TARGET_MIN = 0.015      # +1.5%
TARGET_MAX = 0.15       # +15%
STOP_MIN_ABS = 0.005    # -0.5% (절대값 최소 = 가장 좁은 stop)
STOP_MAX_ABS = 0.05     # -5%  (절대값 최대 = 가장 넓은 stop)
HOLD_MIN_HOURS = 6
HOLD_MAX_HOURS = 72


@dataclass
class DynamicExit:
    target_pct: float        # 양수 (예: 0.035 = +3.5%)
    stop_pct: float          # 음수 (예: -0.02 = -2%)
    max_hold_hours: float    # 6~72
    base_atr_pct: float      # 사용한 ATR (참조용)
    regime_label: str        # 사용한 regime (참조용)
    rationale: str           # 카톡/대시보드용 한 줄 설명

    @property
    def target_price(self) -> float:
        """multiplier로 곱하기. 외부에서 ref_price * (1 + target_pct) 형태로."""
        return self.target_pct

    @property
    def stop_price(self) -> float:
        return self.stop_pct


def compute_dynamic_exit(
    atr_pct: float,
    market: str,
    regime: Optional[RegimeInfo] = None,
) -> DynamicExit:
    """종목 ATR과 시장 regime → DynamicExit.

    atr_pct: ATR/close. 0~0.10 정도 정상 범위.
    market: 'KOSPI' | 'KOSDAQ' | 'NASDAQ'.
    regime: 명시 안 하면 시장에 맞는 regime 조회 (SIDEWAYS 폴백).
    """
    if regime is None:
        regime = get_regime_or_sideways(market)

    # 1) ATR 기반 baseline
    atr_pct = max(0.005, float(atr_pct))  # 너무 작은 ATR은 0.5% floor
    base_target = atr_pct * ATR_TARGET_MULT
    base_stop = -atr_pct * ATR_STOP_MULT
    base_hold = BASE_HOLD_HOURS

    # 2) Regime multiplier
    mult = REGIME_MULT.get(regime.label, REGIME_MULT["SIDEWAYS"])
    target_pct = base_target * mult["target"]
    stop_pct = base_stop * mult["stop"]
    hold_hours = base_hold * mult["hold"]

    # 3) Cap
    target_pct = max(TARGET_MIN, min(TARGET_MAX, target_pct))
    stop_pct = max(-STOP_MAX_ABS, min(-STOP_MIN_ABS, stop_pct))
    hold_hours = max(HOLD_MIN_HOURS, min(HOLD_MAX_HOURS, hold_hours))

    rationale = (
        f"ATR {atr_pct*100:.1f}% × {market} {regime.label} "
        f"({mult['target']:.2f}/{mult['stop']:.2f}/{mult['hold']:.2f})"
    )

    return DynamicExit(
        target_pct=float(target_pct),
        stop_pct=float(stop_pct),
        max_hold_hours=float(hold_hours),
        base_atr_pct=float(atr_pct),
        regime_label=regime.label,
        rationale=rationale,
    )


def format_for_message(de: DynamicExit) -> str:
    """카톡 시그널 메시지용 1줄. 200자 안전.
    예: "🎯 +6.8% / -2.1% · 36h (ATR 2.3% × KOSPI 강세)"
    """
    from engine.market_regime import REGIME_EMOJI, REGIME_KO
    emoji = REGIME_EMOJI.get(de.regime_label, "⚪")
    ko = REGIME_KO.get(de.regime_label, de.regime_label)
    return (
        f"🎯 {de.target_pct*100:+.1f}% / {de.stop_pct*100:.1f}% · "
        f"{int(round(de.max_hold_hours))}h {emoji}{ko}"
    )
