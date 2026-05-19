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
