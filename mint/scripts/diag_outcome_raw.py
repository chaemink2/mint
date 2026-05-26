"""
outcome 컬럼 진단 — 실제 distinct 값 + 5/22~5/24 시그널의 outcome/created_at/status 직접 추출.

이유:
  audit 는 25건 BUY signal 을 PENDING 으로 분류했는데 diag_outcome 의
  `outcome IS NULL` 필터는 5/25 시그널부터 시작 (#13~#17). 5/22~5/24 12건은 어디로?

실행:
  $env:DATABASE_URL = "postgresql://..."
  python -X utf8 mint/scripts/diag_outcome_raw.py
"""
from __future__ import annotations

import os
import sys

MINT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if MINT_ROOT not in sys.path:
    sys.path.insert(0, MINT_ROOT)

from sqlalchemy import text

from portfolio.db import get_conn


def main() -> int:
    with get_conn() as c:
        print("=== outcome distinct (signal_type='BUY') ===")
        for r in c.execute(
            text(
                "SELECT outcome, COUNT(*) AS n FROM signals "
                "WHERE signal_type='BUY' GROUP BY outcome"
            )
        ).fetchall():
            print(" ", dict(r._mapping))

        print()
        print("=== 모든 signal_type 카운트 ===")
        for r in c.execute(
            text("SELECT signal_type, COUNT(*) AS n FROM signals GROUP BY signal_type")
        ).fetchall():
            print(" ", dict(r._mapping))

        print()
        print("=== 5/22~5/24 시그널 raw ===")
        rows = c.execute(
            text(
                "SELECT id, signal_type, status, outcome, "
                "       CASE WHEN outcome IS NULL THEN 1 ELSE 0 END AS is_null, "
                "       CASE WHEN created_at IS NULL THEN 1 ELSE 0 END AS created_null, "
                "       SUBSTR(created_at, 1, 19) AS created_at, "
                "       max_hold_hours "
                "  FROM signals "
                " WHERE created_at LIKE '2026-05-22%' "
                "    OR created_at LIKE '2026-05-23%' "
                "    OR created_at LIKE '2026-05-24%' "
                " ORDER BY id"
            )
        ).fetchall()
        for r in rows:
            print(" ", dict(r._mapping))
        print(f"  total = {len(rows)}")

        print()
        print("=== 14d signal 전체 (audit 25건 확인) ===")
        rows = c.execute(
            text(
                "SELECT id, signal_type, status, outcome, "
                "       SUBSTR(created_at, 1, 19) AS created_at, "
                "       max_hold_hours "
                "  FROM signals "
                " WHERE created_at >= '2026-05-19' "
                " ORDER BY id"
            )
        ).fetchall()
        for r in rows:
            print(" ", dict(r._mapping))
        print(f"  total = {len(rows)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
