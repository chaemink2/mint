"""
LightGBM용 피처 16개 — 외부 ta 라이브러리 없이 직접 계산.

요건:
  - 입력: 일봉 OHLCV DataFrame (최소 60봉 권장, 25봉 미만이면 None)
  - 출력: dict[str, float], 마지막 봉 기준 단일 row
  - NaN/Inf 없음 (모두 0으로 폴백)

피처 키는 FEATURE_NAMES 순서로 고정 — 학습/추론에서 같은 순서로 사용해야 함.

확장 이력:
  v1 (2026-05-17): 11개 — ret/vol/atr/rsi/ma/high
  v2 (2026-05-18): +5개 — bb_position, obv_slope, gap_pct, regime_trend, turnover_pct60
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
    "bb_position", "obv_slope", "gap_pct", "regime_trend", "turnover_pct60",
]

# 2026-06-16 M1: v2 — 시장 regime 2개 추가.
# 학습-운영 분포 정합 + 강세장 끝물/약세장 진입 구간 구분 목적.
FEATURE_NAMES_V2 = FEATURE_NAMES + ["mkt_regime_score", "mkt_regime_bear"]

MIN_BARS = 25


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


def _bb_position(close: pd.Series, period: int = 20, k: float = 2.0) -> float:
    """Bollinger Band 내 현재 close 위치. lower=0, mid=0.5, upper=1. 밴드 폭 0이면 0.5."""
    if len(close) < period:
        return 0.5
    window = close.iloc[-period:]
    mid = window.mean()
    std = window.std(ddof=0)
    last = close.iloc[-1]
    if std is None or pd.isna(std) or std <= 0:
        return 0.5
    upper = mid + k * std
    lower = mid - k * std
    width = upper - lower
    if width <= 0:
        return 0.5
    pos = (last - lower) / width
    return _safe(float(pos), 0.5)


def _obv_slope(close: pd.Series, volume: pd.Series, period: int = 10) -> float:
    """최근 period봉 OBV 선형 기울기 / |OBV mean|. 정규화로 종목 간 비교 가능."""
    n = min(period, len(close) - 1)
    if n < 3:
        return 0.0
    diff = close.diff().fillna(0)
    direction = np.sign(diff)
    obv = (direction * volume).cumsum()
    series = obv.iloc[-(n + 1):]
    if len(series) < 3:
        return 0.0
    x = np.arange(len(series), dtype=float)
    y = series.values.astype(float)
    try:
        slope = np.polyfit(x, y, 1)[0]
    except Exception:
        return 0.0
    scale = np.abs(y).mean()
    if scale <= 0:
        return 0.0
    return _safe(float(slope / scale), 0.0)


def _gap_pct(bars: pd.DataFrame) -> float:
    """마지막 봉의 갭 = open / prev_close - 1."""
    if len(bars) < 2:
        return 0.0
    last_open = bars["open"].iloc[-1]
    prev_close = bars["close"].iloc[-2]
    if prev_close is None or prev_close <= 0:
        return 0.0
    return _safe(float(last_open / prev_close - 1), 0.0)


def _regime_trend(close: pd.Series, period: int = 20) -> float:
    """최근 period봉 중 close > MA(period) 비율. 강세 regime 0.5+, 약세 0.5-."""
    if len(close) < period * 2:
        return 0.5
    ma = close.rolling(period).mean()
    recent_close = close.iloc[-period:]
    recent_ma = ma.iloc[-period:]
    mask = (recent_close > recent_ma) & recent_ma.notna()
    return _safe(float(mask.sum() / period), 0.5)


def _turnover_pct60(bars: pd.DataFrame, period: int = 60) -> float:
    """현재 거래대금이 최근 period봉 분포에서의 백분위 (0~1)."""
    if len(bars) < 10:
        return 0.5
    n = min(period, len(bars))
    closes = bars["close"].iloc[-n:].astype(float)
    vols = bars["volume"].iloc[-n:].astype(float)
    turnover = closes * vols
    last = turnover.iloc[-1]
    if last <= 0:
        return 0.5
    rank = (turnover <= last).sum() / len(turnover)
    return _safe(float(rank), 0.5)


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

    feats["bb_position"] = _bb_position(close, period=20, k=2.0)
    feats["obv_slope"] = _obv_slope(close, volume, period=10)
    feats["gap_pct"] = _gap_pct(bars)
    feats["regime_trend"] = _regime_trend(close, period=20)
    feats["turnover_pct60"] = _turnover_pct60(bars, period=60)

    return {k: feats[k] for k in FEATURE_NAMES}


def features_to_array(features: dict) -> np.ndarray:
    """dict → ordered ndarray (1, n_features). 추론 시 사용."""
    return np.array([[features[k] for k in FEATURE_NAMES]], dtype=float)
