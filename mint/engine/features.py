"""
LightGBM용 피처 11개 — 외부 ta 라이브러리 없이 직접 계산.

요건:
  - 입력: 일봉 OHLCV DataFrame (최소 25봉)
  - 출력: dict[str, float], 마지막 봉 기준 단일 row
  - NaN/Inf 없음 (모두 0으로 폴백)

피처 키는 FEATURE_NAMES 순서로 고정 — 학습/추론에서 같은 순서로 사용해야 함.
"""
from __future__ import annotations

from typing import Optional

import numpy as np
import pandas as pd


FEATURE_NAMES = [
    "ret_1d", "ret_3d", "ret_5d", "ret_10d",
    "vol_ratio_5d", "vol_ratio_20d",
    "atr_pct", "rsi_14",
    "dist_ma5", "dist_ma20", "dist_high60",
]

MIN_BARS = 25  # ATR(14) + RSI(14)에 안전한 최소


def _safe(value: float, fallback: float = 0.0) -> float:
    if value is None:
        return fallback
    try:
        v = float(value)
    except (TypeError, ValueError):
        return fallback
    if np.isnan(v) or np.isinf(v):
        return fallback
    return v


def _rsi(close: pd.Series, period: int = 14) -> float:
    if len(close) < period + 1:
        return 50.0
    delta = close.diff()
    gain = delta.clip(lower=0).rolling(period).mean().iloc[-1]
    loss = (-delta.clip(upper=0)).rolling(period).mean().iloc[-1]
    if loss is None or pd.isna(loss) or loss == 0:
        return 100.0 if (gain or 0) > 0 else 50.0
    rs = gain / loss
    return 100.0 - 100.0 / (1.0 + rs)


def _atr_pct(bars: pd.DataFrame, period: int = 14) -> float:
    if len(bars) < period + 1:
        return 0.0
    high = bars["high"].astype(float)
    low = bars["low"].astype(float)
    close = bars["close"].astype(float)
    tr = pd.concat(
        [high - low, (high - close.shift(1)).abs(), (low - close.shift(1)).abs()],
        axis=1,
    ).max(axis=1)
    atr = tr.rolling(period).mean().iloc[-1]
    last = close.iloc[-1]
    if last <= 0:
        return 0.0
    return _safe(atr / last)


def compute_features(bars: pd.DataFrame) -> Optional[dict]:
    """마지막 봉 기준 피처 dict. 데이터 부족 시 None."""
    if bars is None or len(bars) < MIN_BARS:
        return None

    close = bars["close"].astype(float)
    high = bars["high"].astype(float)
    volume = bars["volume"].astype(float)

    last_close = close.iloc[-1]
    if last_close <= 0:
        return None

    feats = {
        "ret_1d": _safe(close.pct_change(1).iloc[-1]),
        "ret_3d": _safe(close.pct_change(3).iloc[-1]),
        "ret_5d": _safe(close.pct_change(5).iloc[-1]),
        "ret_10d": _safe(close.pct_change(10).iloc[-1]),
    }

    # Volume ratios — 직전 봉 제외하고 최근 N봉 평균 대비
    vol_now = volume.iloc[-1]
    vol_5_avg = volume.iloc[-6:-1].mean() if len(volume) >= 6 else 0
    vol_20_avg = volume.iloc[-21:-1].mean() if len(volume) >= 21 else 0
    feats["vol_ratio_5d"] = _safe(vol_now / vol_5_avg if vol_5_avg > 0 else 0)
    feats["vol_ratio_20d"] = _safe(vol_now / vol_20_avg if vol_20_avg > 0 else 0)

    feats["atr_pct"] = _atr_pct(bars)
    feats["rsi_14"] = _safe(_rsi(close, 14), 50.0)

    ma5 = close.rolling(5).mean().iloc[-1]
    ma20 = close.rolling(20).mean().iloc[-1]
    feats["dist_ma5"] = _safe((last_close / ma5 - 1) if ma5 and ma5 > 0 else 0)
    feats["dist_ma20"] = _safe((last_close / ma20 - 1) if ma20 and ma20 > 0 else 0)

    high_60 = high.iloc[-60:].max() if len(high) >= 60 else high.max()
    feats["dist_high60"] = _safe(
        (last_close / high_60 - 1) if high_60 and high_60 > 0 else 0
    )

    return {k: feats[k] for k in FEATURE_NAMES}


def features_to_array(features: dict) -> np.ndarray:
    """dict → ordered ndarray (1, n_features). 추론 시 사용."""
    return np.array([[features[k] for k in FEATURE_NAMES]], dtype=float)
