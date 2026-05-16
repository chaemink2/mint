"""
Canonical OHLCV bar schema — all sources normalize to this before factors/signals.
"""
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

import pandas as pd

BAR_COLUMNS = [
    "ticker",
    "market",
    "ts_utc",
    "ts_local",
    "open",
    "high",
    "low",
    "close",
    "volume",
    "source",
    "is_adjusted",
    "currency",
]


@dataclass
class Bar:
    ticker: str
    market: str
    ts_utc: datetime
    ts_local: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float
    source: str
    is_adjusted: bool = True
    currency: str = "KRW"


def empty_bars() -> pd.DataFrame:
    return pd.DataFrame(columns=BAR_COLUMNS)


def validate_bars(df: pd.DataFrame) -> pd.DataFrame:
    """Ensure required columns exist and dtypes are consistent."""
    if df.empty:
        return empty_bars()
    missing = [c for c in BAR_COLUMNS if c not in df.columns]
    if missing:
        raise ValueError(f"Missing bar columns: {missing}")
    out = df[BAR_COLUMNS].copy()
    out["ts_utc"] = pd.to_datetime(out["ts_utc"], utc=True)
    out["ts_local"] = pd.to_datetime(out["ts_local"])
    for col in ("open", "high", "low", "close", "volume"):
        out[col] = pd.to_numeric(out[col], errors="coerce")
    out = out.dropna(subset=["close", "volume"])
    return out.sort_values("ts_local").reset_index(drop=True)
