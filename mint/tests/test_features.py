"""Feature computation unit tests (no network)."""
import math
import os
import sys
from datetime import datetime, timedelta

import pandas as pd

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from engine.features import FEATURE_NAMES, compute_features, features_to_array


def _bars(n: int = 60, trend: float = 0.001) -> pd.DataFrame:
    rows = []
    base = 10000.0
    for i in range(n):
        close = base * (1 + trend * i)
        rows.append(
            {
                "ticker": "005930",
                "market": "KOSPI",
                "ts_utc": datetime(2026, 1, 1) + timedelta(days=i),
                "ts_local": datetime(2026, 1, 1) + timedelta(days=i),
                "open": close,
                "high": close * 1.015,
                "low": close * 0.985,
                "close": close,
                "volume": 1_000_000,
                "source": "test",
                "is_adjusted": True,
                "currency": "KRW",
            }
        )
    return pd.DataFrame(rows)


def test_returns_none_below_min_bars():
    df = _bars(n=20)
    assert compute_features(df) is None


def test_returns_all_feature_keys():
    df = _bars(n=60)
    feats = compute_features(df)
    assert feats is not None
    assert set(feats.keys()) == set(FEATURE_NAMES)


def test_no_nan_or_inf():
    df = _bars(n=60)
    feats = compute_features(df)
    for k, v in feats.items():
        assert isinstance(v, float), f"{k} not float: {type(v)}"
        assert not math.isnan(v), f"{k} is NaN"
        assert not math.isinf(v), f"{k} is Inf"


def test_uptrend_positive_returns():
    df = _bars(n=60, trend=0.005)  # 강한 상승
    feats = compute_features(df)
    assert feats["ret_5d"] > 0
    assert feats["ret_10d"] > 0
    # 강한 상승이면 60일 고점 ≈ 마지막 봉 high. close는 high보다 항상 낮으므로 음수, 절댓값 작음.
    assert -0.05 < feats["dist_high60"] <= 0


def test_features_to_array_order():
    df = _bars(n=60)
    feats = compute_features(df)
    arr = features_to_array(feats)
    assert arr.shape == (1, len(FEATURE_NAMES))
    # 순서 확인
    for i, name in enumerate(FEATURE_NAMES):
        assert arr[0, i] == feats[name]


if __name__ == "__main__":
    test_returns_none_below_min_bars()
    test_returns_all_feature_keys()
    test_no_nan_or_inf()
    test_uptrend_positive_returns()
    test_features_to_array_order()
    print("all feature tests pass")
