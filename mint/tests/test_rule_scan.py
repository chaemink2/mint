"""Rule scanner unit tests (no network)."""
import pandas as pd
from datetime import datetime, timedelta

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from engine.signals.rule_scanner import evaluate_ticker, _estimate_expected_return_1d


def _fake_bars(n: int = 30, spike: bool = False) -> pd.DataFrame:
    rows = []
    base = 10000.0
    for i in range(n):
        close = base * (1 + 0.01 * i if spike and i > n - 6 else 1 + 0.001 * i)
        rows.append(
            {
                "ticker": "005930",
                "market": "KOSPI",
                "ts_utc": datetime(2026, 1, 1) + timedelta(days=i),
                "ts_local": datetime(2026, 1, 1) + timedelta(days=i),
                "open": close,
                "high": close * 1.02,
                "low": close * 0.98,
                "close": close,
                "volume": 1_000_000 * (3.0 if spike and i == n - 1 else 1.0),
                "source": "test",
                "is_adjusted": True,
                "currency": "KRW",
            }
        )
    return pd.DataFrame(rows)


def test_evaluate_returns_none_on_flat():
    df = _fake_bars(spike=False)
    assert evaluate_ticker("005930", "KOSPI", df) is None


def test_estimate_return_positive_on_spike():
    df = _fake_bars(spike=True)
    assert _estimate_expected_return_1d(df) > 0
