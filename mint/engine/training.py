"""
LightGBM 학습 파이프라인.

흐름:
  1. 워치리스트의 각 종목에 대해 일봉 fetch
  2. 슬라이딩 윈도우로 (피처 t, 레이블 t→t+1) 페어 생성
     - 레이블: 백테스트와 동일한 시뮬레이션 exit으로 win/loss 판정
  3. 시계열 split (앞 80% train / 뒤 20% val)
  4. LightGBM 학습 → isotonic calibration
  5. mint/data/models/mint_lgbm.joblib 저장 + 메트릭 로그

사용:
  python mint/main.py train --days 365
"""
from __future__ import annotations

import logging
import os
from datetime import datetime
from typing import List, Optional, Tuple

import numpy as np
import pandas as pd

from config.settings import config
from data.collector import fetch_bars
from data.universe import get_watchlist
from engine.backtest import _simulate_exit
from engine.features import FEATURE_NAMES, MIN_BARS, compute_features

log = logging.getLogger("mint.training")


def _watchlist(market: str, n: Optional[int] = None) -> List[str]:
    return get_watchlist(market, n=n if n is not None else config.ops.watchlist_size)


def build_ticker_dataset(
    ticker: str,
    market: str,
    days: int,
    window: int = 60,
    max_hold_days: int = 1,
    target_return: Optional[float] = None,
    stop_loss: Optional[float] = None,
) -> List[dict]:
    """단일 종목 → (피처, 레이블) 리스트.

    target_return/stop_loss/max_hold_days override 가능 (NASDAQ 라벨 변경 실험용,
    2026-05-26). None이면 config.signal 기본값 (KR 학습 호환).

    중요(2026-05-19 수정): 학습 분포 == 추론 분포가 되도록 룰 필터(룰 스캐너와 동일 조건)
    통과한 시점만 학습 데이터로 사용. 이전 버전은 모든 슬라이딩 윈도우 시점을 학습했으나
    실시간 scan은 룰 통과 종목만 시그널을 발생시키므로 train/inference 분포 mismatch였음.
    분봉 룰은 학습 시점에 재현 불가능(분봉 히스토리 없음) — 일봉 룰까지만 매칭.
    """
    from engine.signals.rule_scanner import (
        _estimate_expected_return_1d,
        _risk_score,
        _volume_ratio,
    )

    bars = fetch_bars(ticker, market, days=days + window)
    if bars.empty or len(bars) < window + 2:
        return []

    rows: List[dict] = []
    sig = config.signal
    tgt_ret = target_return if target_return is not None else sig.target_return
    stop_ret = stop_loss if stop_loss is not None else sig.stop_loss

    for i in range(window, len(bars) - 1):
        sub = bars.iloc[i - window : i + 1].reset_index(drop=True)
        if len(sub) < MIN_BARS:
            continue

        # 룰 필터 — 룰 스캐너의 evaluate_ticker와 동일 임계값
        expected = _estimate_expected_return_1d(sub)
        if expected < sig.min_expected_return_1d:
            continue
        risk = _risk_score(sub)
        if risk > sig.max_risk_score:
            continue
        vol_ratio = _volume_ratio(sub)
        if vol_ratio < sig.min_volume_ratio:
            continue

        feats = compute_features(sub)
        if feats is None:
            continue

        entry_price = float(bars.iloc[i]["close"])
        target_price = entry_price * (1 + tgt_ret)
        stop_price = entry_price * (1 + stop_ret)

        trade = _simulate_exit(
            bars=bars,
            entry_idx=i,
            target_price=target_price,
            stop_price=stop_price,
            max_hold_days=max_hold_days,
        )
        if not trade:
            continue

        label = 1 if trade.profit_pct > 0 else 0
        rows.append(
            {
                **feats,
                "label": label,
                "ticker": ticker,
                "market": market,
                "date": str(bars.iloc[i]["ts_local"])[:10],
            }
        )
    return rows


def build_dataset(
    markets: List[str],
    days: int = 365,
    max_hold_days: int = 1,
    universe_size: Optional[int] = None,
    target_return: Optional[float] = None,
    stop_loss: Optional[float] = None,
) -> pd.DataFrame:
    all_rows: List[dict] = []
    for m in markets:
        tickers = _watchlist(m, n=universe_size)
        log.info("Build dataset %s — %d tickers (target=%.3f/stop=%.3f/hold=%dd)",
                 m, len(tickers),
                 target_return if target_return is not None else config.signal.target_return,
                 stop_loss if stop_loss is not None else config.signal.stop_loss,
                 max_hold_days)
        for t in tickers:
            try:
                rows = build_ticker_dataset(
                    t, m, days=days, max_hold_days=max_hold_days,
                    target_return=target_return, stop_loss=stop_loss,
                )
            except Exception as e:
                log.debug("build_ticker_dataset(%s) failed: %s", t, e)
                rows = []
            if rows:
                log.info("  %s — %d samples (pos rate %.2f)",
                         t, len(rows), sum(r["label"] for r in rows) / len(rows))
            all_rows.extend(rows)
    return pd.DataFrame(all_rows)


def _time_split(df: pd.DataFrame, train_frac: float = 0.8) -> Tuple[pd.DataFrame, pd.DataFrame]:
    df = df.sort_values("date").reset_index(drop=True)
    n_train = int(len(df) * train_frac)
    return df.iloc[:n_train], df.iloc[n_train:]


def train_model(
    df: pd.DataFrame,
    target_return: Optional[float] = None,
    stop_loss: Optional[float] = None,
    max_hold_days: int = 1,
):
    """LightGBM 학습 + isotonic calibration. 학습된 TrainedModel 반환."""
    try:
        import lightgbm as lgb
        from sklearn.isotonic import IsotonicRegression
        from sklearn.metrics import log_loss, roc_auc_score
    except ImportError as e:
        raise RuntimeError(
            f"학습에는 lightgbm + scikit-learn 필요: pip install lightgbm scikit-learn joblib ({e})"
        )

    if df.empty:
        raise RuntimeError("Empty dataset — 워치리스트/기간을 확인하세요")
    if len(df) < 100:
        log.warning("Dataset size %d is small — 신뢰도 낮을 수 있음", len(df))

    train_df, val_df = _time_split(df)
    X_tr = train_df[FEATURE_NAMES].values
    y_tr = train_df["label"].values
    X_val = val_df[FEATURE_NAMES].values
    y_val = val_df["label"].values

    pos_rate_tr = y_tr.mean()
    pos_rate_val = y_val.mean()
    log.info(
        "Train n=%d (pos %.2f) · Val n=%d (pos %.2f)",
        len(train_df), pos_rate_tr, len(val_df), pos_rate_val,
    )

    train_set = lgb.Dataset(X_tr, label=y_tr, feature_name=list(FEATURE_NAMES))
    val_set = lgb.Dataset(X_val, label=y_val, feature_name=list(FEATURE_NAMES), reference=train_set)

    params = {
        "objective": "binary",
        "metric": "binary_logloss",
        "learning_rate": 0.05,
        "num_leaves": 31,
        "max_depth": 6,
        "min_data_in_leaf": 20,
        "feature_fraction": 0.9,
        "bagging_fraction": 0.9,
        "bagging_freq": 3,
        "verbose": -1,
    }

    booster = lgb.train(
        params,
        train_set,
        num_boost_round=300,
        valid_sets=[val_set],
        valid_names=["val"],
        callbacks=[lgb.early_stopping(stopping_rounds=30, verbose=False)],
    )

    raw_val = booster.predict(X_val)

    try:
        auc = roc_auc_score(y_val, raw_val) if len(set(y_val)) > 1 else float("nan")
    except Exception:
        auc = float("nan")
    ll = log_loss(y_val, np.clip(raw_val, 1e-6, 1 - 1e-6))

    # Isotonic calibration — 검증셋 기반 (단순 모델이므로 적은 데이터에서도 안정)
    calibrator = None
    if len(set(y_val)) > 1:
        calibrator = IsotonicRegression(out_of_bounds="clip")
        calibrator.fit(raw_val, y_val)

    metrics = {
        "n_train": int(len(train_df)),
        "n_val": int(len(val_df)),
        "pos_rate_train": float(pos_rate_tr),
        "pos_rate_val": float(pos_rate_val),
        "val_auc": float(auc),
        "val_logloss": float(ll),
        "best_iteration": int(booster.best_iteration or booster.current_iteration()),
    }
    log.info("Val AUC=%.3f logloss=%.4f best_iter=%d",
             metrics["val_auc"], metrics["val_logloss"], metrics["best_iteration"])

    from engine.models.lgbm import TrainedModel

    return TrainedModel(
        booster=booster,
        calibrator=calibrator,
        feature_names=list(FEATURE_NAMES),
        trained_at=datetime.now().isoformat(),
        val_metrics=metrics,
        config={
            "target_return": target_return if target_return is not None else config.signal.target_return,
            "stop_loss": stop_loss if stop_loss is not None else config.signal.stop_loss,
            "max_hold_days": max_hold_days,
        },
    )


def _resolve_model_path(markets: List[str], explicit: Optional[str]) -> str:
    """시장 셋에 맞는 기본 모델 경로 결정.
    explicit 명시 시 그 경로. 없으면 NASDAQ-only → us, 그 외 → KR(기본).
    KR+NASDAQ 혼합 학습은 분포 mismatch 위험 — 일단 KR 경로 사용 + 경고.
    """
    from engine.models.lgbm import MODEL_PATHS, DEFAULT_MODEL_PATH
    if explicit:
        return explicit
    if markets == ["NASDAQ"] or set(markets) == {"NASDAQ"}:
        return MODEL_PATHS["US"]
    if set(markets) <= {"KOSPI", "KOSDAQ"}:
        return MODEL_PATHS["KR"]
    log.warning("Mixed KR+US markets %s — KR 모델 경로에 저장하나 분포 mismatch 위험. "
                "시장별 분리 학습 권장.", markets)
    return DEFAULT_MODEL_PATH


def _market_suffix(markets: List[str]) -> str:
    if set(markets) == {"NASDAQ"}:
        return "us"
    if set(markets) <= {"KOSPI", "KOSDAQ"}:
        return "kr"
    return "mixed"


def run_training(
    markets: Optional[List[str]] = None,
    days: int = 365,
    max_hold_days: int = 1,
    model_path: Optional[str] = None,
    universe_size: Optional[int] = None,
    target_return: Optional[float] = None,
    stop_loss: Optional[float] = None,
) -> dict:
    """End-to-end: 데이터셋 → 학습 → 저장. NASDAQ-only면 us 경로 사용.

    target_return/stop_loss override (NASDAQ 라벨 실험용, 2026-05-26).
    """
    markets = markets or ["KOSPI", "KOSDAQ"]
    log.info("Building dataset — markets=%s days=%s universe_size=%s target=%s stop=%s hold=%dd",
             markets, days, universe_size if universe_size is not None else "static",
             target_return if target_return is not None else "default",
             stop_loss if stop_loss is not None else "default",
             max_hold_days)
    df = build_dataset(markets, days=days, max_hold_days=max_hold_days,
                       universe_size=universe_size,
                       target_return=target_return, stop_loss=stop_loss)
    log.info("Dataset built — %d samples (pos rate %.2f)",
             len(df), df["label"].mean() if not df.empty else 0)

    if df.empty:
        return {"error": "empty dataset", "n_samples": 0}

    # Save dataset for inspection (시장 suffix 포함)
    os.makedirs("mint/data/models", exist_ok=True)
    suffix = _market_suffix(markets)
    csv_path = f"mint/data/models/training_data_{suffix}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
    df.to_csv(csv_path, index=False, encoding="utf-8")
    log.info("Dataset saved → %s", csv_path)

    trained = train_model(df, max_hold_days=max_hold_days)
    from engine.models.lgbm import clear_model_cache

    save_path = _resolve_model_path(markets, model_path)
    trained.save(save_path)
    clear_model_cache()

    return {
        "n_samples": int(len(df)),
        "pos_rate": float(df["label"].mean()),
        "metrics": trained.val_metrics,
        "model_path": save_path,
        "dataset_csv": csv_path,
    }


def print_training_report(result: dict) -> None:
    print()
    print("─" * 60)
    print("LightGBM 학습 완료")
    print("─" * 60)
    if "error" in result:
        print(f"  오류: {result['error']}")
        return
    m = result["metrics"]
    print(f"  학습 샘플      : {result['n_samples']}  (Pos rate {result['pos_rate']:.3f})")
    print(f"  Train / Val    : {m['n_train']} / {m['n_val']}")
    print(f"  Val AUC        : {m['val_auc']:.3f}")
    print(f"  Val LogLoss    : {m['val_logloss']:.4f}")
    print(f"  Best iteration : {m['best_iteration']}")
    print(f"  모델 저장      : {result['model_path']}")
    print(f"  데이터셋 CSV   : {result['dataset_csv']}")
    print("─" * 60)
    print("  → scan에 적용하려면 MINT_USE_ML_CONFIDENCE=true")
    print(f"  → 필터 임계값  : MINT_MIN_ML_CONFIDENCE={config.signal.min_model_confidence}")
    print("─" * 60)
