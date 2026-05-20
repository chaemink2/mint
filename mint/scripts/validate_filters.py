"""
필터 검증 스크립트 — 5/19c 학습 결과 재현 + 운영 시뮬레이션.

실행 (workspace 루트에서):
  python -X utf8 mint/scripts/validate_filters.py

출력:
  - 학습/Val 분포 (n, base rate)
  - P(win) 분포 (mean, std, percentiles)
  - 임계값별 시그널 / Precision / Lift / 일평균
  - Top-K per day
  - Feature importance (gain Top 10)

분봉 시뮬은 KIS 의존이라 placeholder만 — 별도 1주일치 분봉 수집 후 분석 권장.
"""
from __future__ import annotations

import glob
import os
import sys

import joblib
import numpy as np
import pandas as pd

# 우리 코드는 workspace/mint 안에 있음
MINT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, MINT_ROOT)

from engine.features import FEATURE_NAMES


def load_latest_dataset_and_model():
    csvs = sorted(glob.glob(os.path.join(MINT_ROOT, "data/models/training_data_*.csv")))
    model_path = os.path.join(MINT_ROOT, "data/models/mint_lgbm.joblib")
    if not csvs or not os.path.exists(model_path):
        return None, None, None
    df = pd.read_csv(csvs[-1])
    df["ticker"] = df["ticker"].astype(str).str.zfill(6)
    df["date"] = pd.to_datetime(df["date"])
    payload = joblib.load(model_path)
    return df, payload, os.path.basename(csvs[-1])


def main() -> int:
    df, payload, csv_name = load_latest_dataset_and_model()
    if df is None:
        print("학습 CSV 또는 모델 파일이 없습니다. python mint/main.py train 먼저 실행.")
        return 1

    booster = payload["booster"]
    calibrator = payload.get("calibrator")

    df = df.sort_values("date").reset_index(drop=True)
    n_train = int(len(df) * 0.8)
    val = df.iloc[n_train:].copy()

    X = val[FEATURE_NAMES].values.astype(float)
    raw = booster.predict(X)
    val["prob"] = calibrator.predict(raw) if calibrator is not None else raw

    base = val["label"].mean()
    n_days = val["date"].nunique()

    print(f"=== Dataset / Model ===")
    print(f"CSV         : {csv_name}")
    print(f"trained_at  : {payload.get('trained_at', '')[:19]}")
    m = payload.get("val_metrics", {})
    print(f"Val AUC     : {m.get('val_auc', 0):.4f}")
    print(f"Val LogLoss : {m.get('val_logloss', 0):.4f}")
    print(f"n_train     : {m.get('n_train', 0):,}")
    print(f"n_val       : {m.get('n_val', 0):,}")
    print()

    print(f"=== Val set ({len(val)} rows, {n_days} days, base win {base:.3f}) ===")
    print(f"P(win) — mean {val['prob'].mean():.3f}, std {val['prob'].std():.3f}, max {val['prob'].max():.3f}")
    for p in [25, 50, 75, 90, 95, 99]:
        print(f"  p{p:02d} = {np.percentile(val['prob'], p):.3f}")
    print()

    print("=== 임계값별 운영 시뮬레이션 (분봉 미반영) ===")
    print(f"{'thr':<6}{'signals':>9}{'rate':>8}{'precision':>11}{'lift':>7}{'/day':>7}")
    for thr in [0.45, 0.50, 0.55, 0.60, 0.65, 0.70, 0.75, 0.80]:
        sel = val[val["prob"] >= thr]
        n = len(sel)
        if n > 0:
            prec = sel["label"].mean()
            print(f"{thr:<6.2f}{n:>9d}{n/len(val):>8.2%}{prec:>11.3f}{prec/base:>7.2f}x{n/n_days:>7.1f}")
        else:
            print(f"{thr:<6.2f}{n:>9d}{n/len(val):>8.2%}{'-':>11}{'-':>7}{'-':>7}")
    print()

    print("=== Top-K per day ===")
    for k in [1, 3, 5]:
        topk = val.sort_values(["date", "prob"], ascending=[True, False]).groupby("date").head(k)
        wr = topk["label"].mean() if len(topk) > 0 else 0
        print(f"  Top-{k}/day: n={len(topk)}, win={wr:.3f}, lift={wr/base if base else 0:.2f}x")
    print()

    print("=== Feature importance (gain Top 10) ===")
    gain = booster.feature_importance(importance_type="gain")
    pairs = sorted(zip(FEATURE_NAMES, gain), key=lambda x: x[1], reverse=True)
    total = float(sum(gain))
    for n, g in pairs[:10]:
        print(f"  {n:<18}{g:>10.1f}  ({g/total*100:.1f}%)")
    print()

    print("=== 분봉 시뮬레이션 (placeholder) ===")
    print("  KIS 분봉 백테스트 인프라 미구축. 다음 작업 권장:")
    print("    1. KIS 분봉 1주일치 수집 (data/models/minute_bars_*.csv)")
    print("    2. minute_rule.evaluate_minute_rule 로 통과 비율 측정")
    print("    3. vol_spike 분포 (p50, p90) 플롯")
    print("    4. 일봉+ML 통과 종목 중 분봉도 통과한 비율 예측 → 실 운영 일평균 추정")
    print()

    print("=== 운영 환경 권장 ===")
    print("  MINT_USE_ML_CONFIDENCE=true · MINT_MIN_ML_CONFIDENCE=0.60")
    print("  분봉: 평상시 일평균 0~2건이 정상. MINT_MIN_MINUTE_VOL_SPIKE=2.0 (1~2주 실험 권장)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
