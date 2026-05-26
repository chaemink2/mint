"""
실 운영 파이프라인 audit — funnel + outcome CSV export (read-only).

목적 (Cursor 4차 R8):
  5/29 의사결정 (카드 m 재학습 / 카드 N calibration / 운영 지속) 증거.
  DB 어떤 변경도 하지 않음. 시그널·outcome·funnel 카운트만 추출.

실행:
  $env:DATABASE_URL = "postgresql://..."   # Neon URL (생략 시 로컬 sqlite)
  python -X utf8 mint/scripts/audit_live_pipeline.py
  python -X utf8 mint/scripts/audit_live_pipeline.py --days 14 --output-dir tmp/audit
  python -X utf8 mint/scripts/audit_live_pipeline.py --no-csv      # 콘솔 요약만

출력 (default `mint/data/audit/`):
  signals_{since}_{until}.csv    — 시그널 행별 (status·outcome·ML score·regime·target/stop/hold)
  outcomes_daily.csv             — 일자별 WIN/LOSS/TIME_EXIT 카운트
  funnel_daily.csv               — 일자별 funnel 단계 통과 카운트 (notifier_state)
  console                        — 사람 가독 요약

전제:
  - portfolio.db 가 정상 import 가능 (mint 패키지 PYTHONPATH 또는 workspace 루트에서 실행).
  - signals 테이블에 outcome / regime_label / max_hold_hours 컬럼 존재 (5/22 c55e8e8 이후).
  - notifier_state app_state row 에 scan_stats_YYYY-MM-DD JSON 존재.
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import sys
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from typing import Dict, Iterable, List, Optional

# workspace 루트에서 실행했을 때 mint/ 패키지를 import 가능하게
MINT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if MINT_ROOT not in sys.path:
    sys.path.insert(0, MINT_ROOT)

from sqlalchemy import text

from portfolio.db import (
    get_app_state,
    get_conn,
    get_outcome_stats,
    get_signals_since,
)

# Outcome 카운트는 "오늘 KST" 기준이 자연스러움
try:
    from config.tz import today_kst, to_kst  # 5/23 R1+R2 이후
except Exception:  # 안전망 — tz 모듈이 없거나 다른 환경
    def today_kst() -> str:
        return datetime.now().strftime("%Y-%m-%d")

    def to_kst(s):  # type: ignore[override]
        return s


SIGNAL_CSV_FIELDS = [
    "id", "created_at", "market", "ticker", "name",
    "signal_type", "status", "outcome", "expiry_reason",
    "ref_price", "target_price", "stop_price",
    "expected_return", "confidence", "model_score",
    "risk_score", "max_hold_hours", "regime_label",
    "valid_until", "notified", "outcome_max", "outcome_min",
    "outcome_evaluated_at",
]


def _fmt_pct(p: Optional[float]) -> str:
    if p is None:
        return "  -  "
    return f"{p*100:5.1f}%"


def _fetch_signals(days: int) -> List[Dict]:
    """get_signals_since 는 signal_type='BUY' 만 — 충분."""
    since_dt = datetime.now() - timedelta(days=days)
    return get_signals_since(since_dt.isoformat(), limit=10_000)


def _fetch_funnel_states() -> Dict[str, dict]:
    """notifier_state JSON 안의 scan_stats_YYYY-MM-DD 키만 추출."""
    raw = get_app_state("notifier_state")
    if not raw:
        return {}
    try:
        d = json.loads(raw)
    except Exception:
        return {}
    return {k: v for k, v in d.items() if isinstance(k, str) and k.startswith("scan_stats_")}


def _kst_date(iso: str) -> str:
    """`created_at` ISO 문자열 → KST 'YYYY-MM-DD'. 실패 시 첫 10자 그대로."""
    if not iso:
        return "(unknown)"
    try:
        dt = datetime.fromisoformat(iso)
    except ValueError:
        return iso[:10] or "(unknown)"
    try:
        return to_kst(dt).strftime("%Y-%m-%d")
    except Exception:
        return iso[:10] or "(unknown)"


def _outcome_daily_table(signals: Iterable[Dict]) -> Dict[str, Counter]:
    """day(KST) → Counter(outcome -> n). outcome None은 'PENDING' 으로."""
    table: Dict[str, Counter] = defaultdict(Counter)
    for sig in signals:
        day = _kst_date(sig.get("created_at") or "")
        table[day][sig.get("outcome") or "PENDING"] += 1
    return table


def _status_table(signals: Iterable[Dict]) -> Counter:
    return Counter(sig.get("status") or "(none)" for sig in signals)


def _write_signals_csv(signals: List[Dict], out_path: str) -> None:
    with open(out_path, "w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=SIGNAL_CSV_FIELDS)
        w.writeheader()
        for s in signals:
            w.writerow({k: s.get(k, "") for k in SIGNAL_CSV_FIELDS})


def _write_outcomes_csv(daily: Dict[str, Counter], out_path: str) -> None:
    keys = ["WIN", "LOSS", "TIME_EXIT", "PENDING"]
    with open(out_path, "w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["date"] + keys + ["total", "win_rate"])
        for day in sorted(daily.keys()):
            row = daily[day]
            counts = [row.get(k, 0) for k in keys]
            evaluated = sum(row.get(k, 0) for k in ("WIN", "LOSS", "TIME_EXIT"))
            wr = row.get("WIN", 0) / evaluated if evaluated else ""
            w.writerow([day] + counts + [sum(counts), wr])


def _write_funnel_csv(funnel: Dict[str, dict], out_path: str) -> None:
    # 동적 키 — funnel value dict 의 모든 키를 union
    key_union: List[str] = []
    seen = set()
    for v in funnel.values():
        if not isinstance(v, dict):
            continue
        for k in v.keys():
            if k not in seen:
                seen.add(k)
                key_union.append(k)
    with open(out_path, "w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["date"] + key_union)
        for day_key in sorted(funnel.keys()):
            day = day_key.replace("scan_stats_", "", 1)
            v = funnel[day_key] if isinstance(funnel[day_key], dict) else {}
            w.writerow([day] + [v.get(k, "") for k in key_union])


def _print_console_summary(
    *,
    days: int,
    signals: List[Dict],
    daily_outcomes: Dict[str, Counter],
    funnel_states: Dict[str, dict],
) -> None:
    db_dialect = "?"
    try:
        with get_conn() as conn:
            db_dialect = conn.engine.dialect.name
    except Exception as e:
        db_dialect = f"(error: {e})"

    print(f"=== Audit (read-only) — last {days} days ===")
    print(f"DB dialect       : {db_dialect}")
    print(f"Signals fetched  : {len(signals)}")
    print()

    print("=== Status breakdown ===")
    for status, n in _status_table(signals).most_common():
        print(f"  {status:<12} {n:>4}")
    print()

    print("=== Daily outcomes (KST date · status:BUY 전체) ===")
    print(f"  {'date':<12}{'WIN':>5}{'LOSS':>5}{'T_EXIT':>7}{'PEND':>6}{'total':>7}{'win_rate':>10}")
    for day in sorted(daily_outcomes.keys()):
        row = daily_outcomes[day]
        evaluated = sum(row.get(k, 0) for k in ("WIN", "LOSS", "TIME_EXIT"))
        wr = row.get("WIN", 0) / evaluated if evaluated else None
        print(
            f"  {day:<12}"
            f"{row.get('WIN', 0):>5}"
            f"{row.get('LOSS', 0):>5}"
            f"{row.get('TIME_EXIT', 0):>7}"
            f"{row.get('PENDING', 0):>6}"
            f"{sum(row.values()):>7}"
            f"{_fmt_pct(wr):>10}"
        )
    print()

    for window in (7, 14, 30):
        if window > days and window != 30:
            continue
        s = get_outcome_stats(window)
        wr = s.get("win_rate")
        wr_s = _fmt_pct(wr) if wr is not None else "  -  "
        print(
            f"  outcome_stats[{window:>2}d]: total={s['total']:>3} · WIN {s['win']:>2} · "
            f"LOSS {s['loss']:>2} · T_EXIT {s['time_exit']:>2} · win_rate {wr_s}"
        )
    print()

    print("=== Funnel (notifier_state.scan_stats_YYYY-MM-DD) ===")
    if not funnel_states:
        print("  (no funnel state — GHA scan-kr 가 아직 한 번도 안 돌았거나 state 키 없음)")
    else:
        seen_cols: List[str] = []
        col_seen = set()
        for v in funnel_states.values():
            if isinstance(v, dict):
                for k in v.keys():
                    if k not in col_seen:
                        col_seen.add(k)
                        seen_cols.append(k)
        # 사람 가독: 흔히 보는 키만 우선 표시
        preferred = [k for k in ("evaluated", "passed_momentum", "passed_risk",
                                 "passed_volume", "passed_ml", "passed_minute",
                                 "signals_created") if k in seen_cols]
        cols = preferred or seen_cols
        header = "  " + f"{'date':<12}" + "".join(f"{c:>17}" for c in cols)
        print(header)
        for day_key in sorted(funnel_states.keys()):
            day = day_key.replace("scan_stats_", "", 1)
            v = funnel_states[day_key] if isinstance(funnel_states[day_key], dict) else {}
            line = "  " + f"{day:<12}" + "".join(f"{str(v.get(c, '-')):>17}" for c in cols)
            print(line)
    print()


def _ensure_output_dir(path: str) -> str:
    path = os.path.abspath(path)
    os.makedirs(path, exist_ok=True)
    return path


def main() -> int:
    parser = argparse.ArgumentParser(description="Mint live pipeline audit (read-only).")
    parser.add_argument("--days", type=int, default=7, help="시그널 조회 일수 (기본 7)")
    parser.add_argument(
        "--output-dir",
        default=os.path.join(MINT_ROOT, "data", "audit"),
        help="CSV 출력 경로 (기본 mint/data/audit/)",
    )
    parser.add_argument("--no-csv", action="store_true", help="콘솔 요약만 출력")
    args = parser.parse_args()

    signals = _fetch_signals(args.days)
    daily_outcomes = _outcome_daily_table(signals)
    funnel_states = _fetch_funnel_states()

    _print_console_summary(
        days=args.days,
        signals=signals,
        daily_outcomes=daily_outcomes,
        funnel_states=funnel_states,
    )

    if args.no_csv:
        return 0

    out_dir = _ensure_output_dir(args.output_dir)
    today = today_kst()
    since = (datetime.now() - timedelta(days=args.days)).strftime("%Y-%m-%d")

    sig_path = os.path.join(out_dir, f"signals_{since}_{today}.csv")
    out_path = os.path.join(out_dir, "outcomes_daily.csv")
    funnel_path = os.path.join(out_dir, "funnel_daily.csv")

    _write_signals_csv(signals, sig_path)
    _write_outcomes_csv(daily_outcomes, out_path)
    _write_funnel_csv(funnel_states, funnel_path)

    print(f"=== Files written ===")
    print(f"  {sig_path}  ({len(signals)} rows)")
    print(f"  {out_path}  ({len(daily_outcomes)} days)")
    print(f"  {funnel_path}  ({len(funnel_states)} days)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
