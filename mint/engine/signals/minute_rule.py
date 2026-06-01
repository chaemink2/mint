"""
분봉(5분봉) 기반 장중 매수 패턴 검증 룰.

운영 흐름:
  1. 일봉 룰 + ML 필터 통과한 종목만 분봉 평가 (AND 조건)
  2. KIS 분봉 fetch (당일, 최근 ~30봉)
  3. 세 가지 조건 모두 만족하면 통과:
     (a) 거래량 spike — 마지막 봉 거래량 ≥ 직전 N봉 평균 × min_minute_vol_spike
     (b) 단기 모멘텀 — 최근 short_window 평균 종가 > 직전 long_window 평균 종가
     (c) 양봉 — 마지막 봉 close ≥ open

설계 의도:
  - 일봉 룰: "최근 추세 좋고 ML이 24h 내 +3.5% 도달 가능성 높다고 판단"
  - 분봉 룰: "그 안에서도 장중에 실제로 매수 모멘텀이 진행 중인 종목만"
  - 두 조건이 AND이므로 시그널이 줄어들지만 정밀도는 올라감
  - KIS 분봉 호출은 일봉 후보(매일 ~10개)에 한정 — 호출 한도 무리 X

환경변수:
  MINT_USE_MINUTE_RULE       (기본 false — 안전 디폴트)
  MINT_MIN_MINUTE_VOL_SPIKE  (기본 3.0)
  MINT_MINUTE_SHORT_WINDOW   (기본 5)
  MINT_MINUTE_LONG_WINDOW    (기본 20)
"""
from __future__ import annotations

import logging
from typing import Optional

import pandas as pd

from config.settings import config

log = logging.getLogger("mint.minute_rule")


def evaluate_minute_rule(bars: pd.DataFrame) -> Optional[dict]:
    """분봉 OHLCV로 장중 매수 패턴 평가.

    bars: DataFrame[ts, open, high, low, close, volume] (시간 정순)
    반환: 통과 시 metric dict, 미통과 시 None.
    """
    sig = config.signal
    needed = sig.minute_long_window + 1
    if bars is None or len(bars) < needed:
        return None

    last = bars.iloc[-1]
    last_vol = float(last["volume"])
    last_open = float(last["open"])
    last_close = float(last["close"])

    prev = bars.iloc[-(sig.minute_long_window + 1) : -1]
    vol_avg = float(prev["volume"].mean()) if len(prev) > 0 else 0.0
    vol_spike = (last_vol / vol_avg) if vol_avg > 0 else 0.0

    short = bars["close"].iloc[-sig.minute_short_window :].astype(float).mean()
    long = (
        bars["close"]
        .iloc[-(sig.minute_long_window) : -sig.minute_short_window]
        .astype(float)
        .mean()
    )

    pass_vol = vol_spike >= sig.min_minute_vol_spike
    pass_momentum = short > long
    pass_bullish = last_close >= last_open

    if pass_vol and pass_momentum and pass_bullish:
        return {
            "minute_pass": True,
            "minute_vol_spike": round(float(vol_spike), 2),
            "minute_short_ma": float(short),
            "minute_long_ma": float(long),
            "minute_last_close": last_close,
        }
    return None


def fetch_and_evaluate(ticker: str) -> Optional[dict]:
    """KIS 분봉 fetch + 평가를 한 번에. KIS 키 없거나 fetch 실패 시 None."""
    from data import kis_client

    bars = kis_client.get_minute_bars(ticker)
    if bars is None:
        return None
    return evaluate_minute_rule(bars)


# ============================================================================
# 2026-06-01: 분봉 1차 발견 룰 (MINT_MINUTE_FIRST=true 시 활성)
#
# 기존 evaluate_minute_rule은 일봉 통과 후 추가 필터 (정밀도 ↑, 신호 ↓).
# 새 evaluate_minute_first_discovery는 분봉 자체로 강한 매수 패턴을 1차 발견:
#   - 거래량 spike ≥ vol_spike_strong (기본 2.5배)
#   - 신고가 돌파 — 마지막 봉 high > 직전 long_window 봉 high
#   - 모멘텀 가속 — short_ma > medium_ma > long_ma (정렬)
#   - 양봉 (마지막 봉)
#
# 이 패턴이 잡혔으면 일봉은 보조 필터로만 (risk gate). ML 모델 통과는 옵션.
# ============================================================================


def evaluate_minute_first_discovery(bars: pd.DataFrame) -> Optional[dict]:
    """분봉 자체로 강한 매수 패턴 1차 발견.

    bars: DataFrame[ts, open, high, low, close, volume] (시간 정순)
    반환: 통과 시 metric dict, 미통과 시 None.

    조건 (AND):
      (a) vol_spike ≥ vol_spike_strong (기본 2.5배)
      (b) 신고가 돌파 — last bar high > 직전 long_window 봉의 max(high)
      (c) 모멘텀 가속 — close MA(short) > MA(medium) > MA(long)
      (d) 양봉 — last close ≥ last open
    """
    import os
    sig = config.signal
    vol_spike_strong = float(os.getenv("MINT_MIN_MINUTE_VOL_SPIKE_STRONG", "2.5"))
    short_w = sig.minute_short_window         # 기본 5
    medium_w = max(short_w + 2, sig.minute_short_window * 2)  # 기본 10
    long_w = sig.minute_long_window           # 기본 20

    needed = long_w + 1
    if bars is None or len(bars) < needed:
        return None

    last = bars.iloc[-1]
    last_high = float(last["high"])
    last_open = float(last["open"])
    last_close = float(last["close"])
    last_vol = float(last["volume"])

    prev = bars.iloc[-(long_w + 1) : -1]
    vol_avg = float(prev["volume"].mean()) if len(prev) > 0 else 0.0
    vol_spike = (last_vol / vol_avg) if vol_avg > 0 else 0.0

    # 신고가 돌파 — 직전 long_w 봉의 최고가를 last_high가 넘어섬
    prev_high_max = float(prev["high"].max()) if len(prev) > 0 else 0.0
    pass_breakout = last_high > prev_high_max if prev_high_max > 0 else False

    # 모멘텀 가속 — short > medium > long
    closes = bars["close"].astype(float)
    ma_short = float(closes.iloc[-short_w:].mean())
    ma_medium = float(closes.iloc[-medium_w:].mean())
    ma_long = float(closes.iloc[-long_w:].mean())
    pass_accel = ma_short > ma_medium > ma_long

    pass_vol = vol_spike >= vol_spike_strong
    pass_bullish = last_close >= last_open

    if pass_vol and pass_breakout and pass_accel and pass_bullish:
        return {
            "minute_first": True,
            "minute_vol_spike": round(vol_spike, 2),
            "minute_breakout_ratio": round(last_high / prev_high_max, 4) if prev_high_max else None,
            "minute_short_ma": ma_short,
            "minute_medium_ma": ma_medium,
            "minute_long_ma": ma_long,
            "minute_last_close": last_close,
        }
    return None


def fetch_and_discover(ticker: str) -> Optional[dict]:
    """분봉 1차 발견: KIS 분봉 fetch + evaluate_minute_first_discovery."""
    from data import kis_client

    bars = kis_client.get_minute_bars(ticker)
    if bars is None:
        return None
    return evaluate_minute_first_discovery(bars)
