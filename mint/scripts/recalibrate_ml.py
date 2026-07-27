"""
E — ML isotonic recalibration on live outcome (2026-07-27).

문제 진단:
  · 40일 실측 (6/17~7/27, KR 140건) 에서 model_score / confidence 100% saturate.
  · isotonic calibrator가 booster raw score를 모두 P(win)=1.0으로 매핑.
  · ML score 0.95+ 148건 dec 21.5% vs ML 0.5~0.7 13건 dec 27.3% — anti-calibration.
  · threshold 무력, ML 필터가 사실상 no-op.

접근:
  1. audit CSV 로드 → 라이브 KR 시그널 + WIN 라벨 확보
  2. 각 시그널 (ticker, created_date) → fetch_bars → compute_features → booster.predict
     (라이브 raw score 재현)
  3. (raw_score, win_label) 로 새 isotonic fit
  4. 모델 backup + new calibrator 저장 → mint_lgbm.joblib
  5. new score 분포 + threshold sweep 출력

실행:
  python -X utf8 mint/scripts/recalibrate_ml.py \\
      --audit-csv tmp/audit_40d/signals_2026-06-17_2026-07-27.csv \\
      --dry-run     # 모델 파일 저장 안 함

주의:
  · outcome=WIN 은 fixed +3%/-2% 라벨 도달 (24h 안). NASDAQ 은 다른 라벨이라 제외.
  · TIME_EXIT은 라벨 0으로 취급 (target 미도달).
  · 실 win rate ~20%라 pos rate 낮음. sample n=140~161이면 fit noisy but 방향성 OK.
"""
from __future__ import annotations

import argparse
import logging
import os
import sys
from datetime import datetime, timedelta
from typing import List, Optional

import numpy as np
import pandas as pd

MINT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if MINT_ROOT not in sys.path:
    sys.path.insert(0, MINT_ROOT)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
log = logging.getLogger("recal")


def load_live_signals(csv_path: str) -> pd.DataFrame:
    df = pd.read_csv(csv_path)
    df["created"] = pd.to_datetime(df["created_at"], format="mixed", utc=True).dt.tz_convert("Asia/Seoul")
    df = df[(df.signal_type == "BUY") & (df.created >= pd.Timestamp("2026-06-17", tz="Asia/Seoul"))].copy()
    df = df[df.outcome.isin(["WIN", "LOSS", "TIME_EXIT"])].copy()
    df = df[df.market.isin(["KOSPI", "KOSDAQ"])].copy()  # NASDAQ은 다른 모델
    df["label"] = (df.outcome == "WIN").astype(int)
    df["created_date"] = df.created.dt.strftime("%Y-%m-%d")
    log.info("Live KR signals loaded: %d (WIN rate %.3f)", len(df), df.label.mean())
    return df


def compute_raw_score(row: dict, model) -> Optional[float]:
    """단일 시그널의 원본 features → booster raw score (calibrator 우회)."""
    from data.collector import fetch_bars
    from engine.features import compute_features
    from engine.market_regime import fetch_index_history, regime_at_date, regime_to_features

    try:
        # 발급 시점 + 60일 컨텍스트로 fetch (features용 window)
        bars = fetch_bars(row["ticker"], row["market"], days=90)
        if bars is None or bars.empty:
            return None
        # 시그널 발급 시점 이전까지만 (data leakage 방지)
        target_date = pd.Timestamp(row["created_date"])
        bars["ts_local"] = pd.to_datetime(bars["ts_local"])
        bars_ts = bars["ts_local"].dt.tz_localize(None) if bars["ts_local"].dt.tz is not None else bars["ts_local"]
        cutoff = bars[bars_ts <= target_date]
        if len(cutoff) < 25:
            return None
        feats = compute_features(cutoff)
        if feats is None:
            return None
        # v2 모델은 regime feature 필요
        if "mkt_regime_score" in (model.feature_names or []):
            hist = fetch_index_history(row["market"], days=200)
            info = regime_at_date(row["market"], target_date, hist=hist)
            feats.update(regime_to_features(info))
        # v2a 모델은 18 features. features_to_array는 v1 16만 반환하므로 직접 array 생성.
        x = np.array([[feats[k] for k in model.feature_names]], dtype=float)
        raw = float(model.booster.predict(x)[0])
        return raw
    except Exception as e:
        log.debug("raw score fetch failed (%s): %s", row["ticker"], e)
        return None


def fit_new_isotonic(raw_scores: np.ndarray, labels: np.ndarray):
    from sklearn.isotonic import IsotonicRegression
    iso = IsotonicRegression(out_of_bounds="clip")
    iso.fit(raw_scores, labels)
    return iso


def threshold_sweep(raw: np.ndarray, cal_scores: np.ndarray, labels: np.ndarray) -> None:
    print()
    print("=== Raw booster score 분포 ===")
    print(f"  min {raw.min():.4f} · p10 {np.quantile(raw, .1):.4f} · median {np.median(raw):.4f} · "
          f"p90 {np.quantile(raw, .9):.4f} · max {raw.max():.4f}")
    print()
    print("=== 새 isotonic 후 score 분포 ===")
    print(f"  min {cal_scores.min():.4f} · median {np.median(cal_scores):.4f} · max {cal_scores.max():.4f}")
    print()
    base = labels.mean()
    print(f"=== 임계값 sweep (n={len(labels)}, base rate {base:.3f}) ===")
    print(f"  {'thr':>6} {'pass':>5} {'WIN':>5} {'precision':>10} {'lift':>6}")
    for thr in [0.10, 0.15, 0.20, 0.25, 0.30, 0.40, 0.50, 0.60, 0.70]:
        mask = cal_scores >= thr
        n_pass = int(mask.sum())
        if n_pass == 0:
            continue
        n_win = int(labels[mask].sum())
        prec = n_win / n_pass
        lift = prec / base if base > 0 else 0
        print(f"  {thr:>6.2f} {n_pass:>5d} {n_win:>5d} {prec:>9.3f} {lift:>5.2f}x")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--audit-csv", default="tmp/audit_40d/signals_2026-06-17_2026-07-27.csv")
    parser.add_argument("--model-path", default="mint/data/models/mint_lgbm.joblib")
    parser.add_argument("--backup-path", default="mint/data/models/mint_lgbm_pre_recal.joblib")
    parser.add_argument("--dry-run", action="store_true", help="모델 파일 저장 안 함")
    args = parser.parse_args()

    import joblib
    from engine.models.lgbm import TrainedModel, load_model
    model = load_model(args.model_path)
    if model is None:
        log.error("모델 로드 실패: %s", args.model_path)
        return 1

    live = load_live_signals(args.audit_csv)

    log.info("각 시그널 raw booster score 재추론 중 (~%d건, ticker 수만큼 fetch)...", len(live))
    raws: List[Optional[float]] = []
    for _, r in live.iterrows():
        raws.append(compute_raw_score(r.to_dict(), model))
    live["raw"] = raws
    ok = live.dropna(subset=["raw"]).copy()
    log.info("재추론 성공: %d / %d", len(ok), len(live))
    if len(ok) < 50:
        log.error("샘플 부족 (%d < 50) — 중단", len(ok))
        return 1

    raw_arr = ok["raw"].values.astype(float)
    y = ok["label"].values.astype(int)

    log.info("새 isotonic fit (n=%d, WIN %.3f)", len(y), y.mean())
    new_iso = fit_new_isotonic(raw_arr, y)
    cal = new_iso.predict(raw_arr)

    threshold_sweep(raw_arr, cal, y)

    if args.dry_run:
        log.info("[dry-run] 저장 안 함. 실제 적용은 --dry-run 없이 재실행.")
        return 0

    # backup + save
    if not os.path.exists(args.backup_path):
        import shutil
        shutil.copy2(args.model_path, args.backup_path)
        log.info("Backup: %s → %s", args.model_path, args.backup_path)

    payload = joblib.load(args.model_path)
    payload["calibrator"] = new_iso
    payload["config"] = dict(payload.get("config") or {})
    payload["config"]["recalibrated_at"] = datetime.now().isoformat()
    payload["config"]["recal_n"] = int(len(y))
    payload["config"]["recal_pos_rate"] = float(y.mean())
    joblib.dump(payload, args.model_path)
    log.info("모델 저장 완료 → %s", args.model_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
