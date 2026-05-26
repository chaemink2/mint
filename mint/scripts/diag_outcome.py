"""
outcome 평가 실패 원인 진단 — pending 시그널마다 단계별로 어디서 None인지 추적.

이유:
  evaluate_pending_outcomes 가 limit=200으로 도는데 outcome이 누적 안 됨.
  _evaluate_single_outcome 은 silent (None 반환만). 어떤 가드에서 fall-through 되는지
  로그가 없어 운영 데이터만 보면 디버그 불가.

실행:
  $env:DATABASE_URL = "postgresql://..."
  python -X utf8 mint/scripts/diag_outcome.py
  python -X utf8 mint/scripts/diag_outcome.py --limit 5

출력:
  pending 시그널 N건 각각에 대해:
    [PASS/FAIL] step1 created_at 파싱
    [PASS/FAIL] step2 horizon 경과 (now_kst >= created + max_hold_hours)
    [PASS/FAIL] step3 target/stop/ref 존재
    [PASS/FAIL] step4 market in (KOSPI/KOSDAQ)
    [PASS/FAIL] step5 pykrx fetch_daily_bars 성공
    [PASS/FAIL] step6 bars non-empty
    [PASS/FAIL] step7 after = bars > created 비어 있지 않음
    -> 최종 outcome (도달 시)
"""
from __future__ import annotations

import argparse
import os
import sys
import traceback
from datetime import datetime, timedelta

MINT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if MINT_ROOT not in sys.path:
    sys.path.insert(0, MINT_ROOT)

import pandas as pd
from sqlalchemy import text

from config.settings import config as _cfg
from config.tz import now_kst, to_kst
from data import krx_client as _krx
from portfolio.db import _rows_to_dicts, get_conn


def diag_one(sig: dict) -> None:
    sid = sig.get("id")
    print(f"\n── signal #{sid} {sig.get('market')} {sig.get('ticker')} ({sig.get('name')}) ──")
    print(f"   created_at = {sig.get('created_at')}")
    print(f"   target={sig.get('target_price')}  stop={sig.get('stop_price')}  ref={sig.get('ref_price')}")
    print(f"   max_hold_hours={sig.get('max_hold_hours')}  status={sig.get('status')}")

    # step1 created_at 파싱
    try:
        created = datetime.fromisoformat(sig["created_at"])
    except Exception as e:
        print(f"   [FAIL step1] created_at 파싱 실패: {e}")
        return
    print(f"   [PASS step1] parsed = {created}")

    created_kst = to_kst(created)
    print(f"   created_kst = {created_kst}")

    # step2 horizon 경과 여부
    horizon_h = float(sig.get("max_hold_hours") or _cfg.signal.max_hold_hours)
    eligible_at = created_kst + timedelta(hours=horizon_h)
    nk = now_kst()
    print(f"   horizon = {horizon_h:.1f}h  eligible_at_kst = {eligible_at}  now_kst = {nk}")
    if nk < eligible_at:
        diff = (eligible_at - nk).total_seconds() / 3600
        print(f"   [FAIL step2] horizon 미경과 (남은 {diff:.1f}h)")
        return
    print(f"   [PASS step2] horizon 경과")

    # step3 target/stop/ref 존재
    target = sig.get("target_price")
    stop = sig.get("stop_price")
    ref = sig.get("ref_price")
    if not target or not stop or not ref:
        print(f"   [FAIL step3] target/stop/ref 누락: target={target} stop={stop} ref={ref}")
        return
    print(f"   [PASS step3] target/stop/ref 모두 존재")

    # step4 market check
    if sig.get("market") not in ("KOSPI", "KOSDAQ"):
        print(f"   [FAIL step4] market={sig.get('market')} 평가 대상 아님")
        return
    print(f"   [PASS step4] market 평가 대상")

    # step5 pykrx fetch
    try:
        bars = _krx.fetch_daily_bars(sig["ticker"], sig["market"], days=5)
    except Exception as e:
        print(f"   [FAIL step5] pykrx fetch 예외:")
        traceback.print_exc()
        return
    print(f"   [PASS step5] pykrx fetch_daily_bars 호출 성공")

    # step6 bars non-empty
    if bars is None or bars.empty:
        print(f"   [FAIL step6] bars empty/None  (bars={bars})")
        return
    print(f"   [PASS step6] bars rows={len(bars)}  cols={list(bars.columns)}")
    bars = bars.copy()
    bars["ts_local"] = pd.to_datetime(bars["ts_local"])
    print(f"   bars ts_local range: {bars['ts_local'].min()} ~ {bars['ts_local'].max()}")

    # step7 after (bars > created)
    after = bars[bars["ts_local"] > created_kst]
    if after.empty:
        print(
            f"   [FAIL step7] after empty — bars 의 모든 ts_local 이 created_kst({created_kst}) 이하"
        )
        print("   → 가설: 같은 날 일봉 ts_local(자정) 이 created_at(장중) 보다 빠르고,")
        print("           다음 영업일 일봉이 pykrx 에 아직 없음 (장 마감/주말/휴장)")
        return
    horizon_days = max(1, int(horizon_h // 24))
    after = after.head(horizon_days).reset_index(drop=True)
    print(f"   [PASS step7] after rows={len(after)} (horizon_days={horizon_days})")

    # 평가 (실제 _evaluate_single_outcome 로직과 동일)
    outcome = "TIME_EXIT"
    for _, bar in after.iterrows():
        hi, lo = float(bar["high"]), float(bar["low"])
        if lo <= stop and hi >= target:
            outcome = "LOSS"
            break
        if lo <= stop:
            outcome = "LOSS"
            break
        if hi >= target:
            outcome = "WIN"
            break
    print(f"   → outcome = {outcome}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=5, help="진단할 pending 시그널 수")
    args = parser.parse_args()

    with get_conn() as conn:
        rows = conn.execute(
            text(
                """SELECT * FROM signals
                   WHERE signal_type = 'BUY' AND outcome IS NULL AND created_at IS NOT NULL
                   ORDER BY created_at ASC LIMIT :lim"""
            ),
            {"lim": args.limit},
        ).fetchall()
        sigs = _rows_to_dicts(rows)

    print(f"=== Pending outcome 진단 (n={len(sigs)}) ===")
    print(f"now_kst = {now_kst()}")
    if not sigs:
        print("(pending 시그널 없음)")
        return 0

    for s in sigs:
        try:
            diag_one(s)
        except Exception as e:
            print(f"diag_one 예외 ({s.get('id')}): {e}")
            traceback.print_exc()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
