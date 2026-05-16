"""
Mint - 포트폴리오 DB (SQLite)
매매 이력, 보유 종목, 시그널 추적 (signals ↔ positions ↔ trades)
"""
import sqlite3
from datetime import datetime, timedelta
from contextlib import contextmanager
from typing import Optional, List, Dict
import os

from config.settings import config


DB_PATH = os.environ.get("MINT_DB_PATH", config.db.path)

_SCHEMA_V2 = """
        CREATE TABLE IF NOT EXISTS signals (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            ticker          TEXT NOT NULL,
            market          TEXT NOT NULL,
            name            TEXT,
            signal_type     TEXT NOT NULL,
            confidence      REAL,
            expected_return REAL,
            risk_score      REAL,
            model_score     REAL,
            ref_price       REAL,
            target_price    REAL,
            stop_price      REAL,
            status          TEXT DEFAULT 'active',
            valid_until     TEXT,
            created_at      TEXT NOT NULL,
            notified        INTEGER DEFAULT 0,
            notified_at     TEXT
        );

        CREATE TABLE IF NOT EXISTS positions (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            signal_id       INTEGER REFERENCES signals(id),
            ticker          TEXT NOT NULL,
            market          TEXT NOT NULL,
            name            TEXT,
            buy_price       REAL NOT NULL,
            quantity        INTEGER NOT NULL,
            remaining_qty   INTEGER NOT NULL,
            buy_time        TEXT NOT NULL,
            target_price    REAL,
            stop_loss       REAL,
            signal_conf     REAL,
            currency        TEXT DEFAULT 'KRW',
            fx_rate_at_buy  REAL,
            source          TEXT DEFAULT 'manual',
            status          TEXT DEFAULT 'open'
        );

        CREATE TABLE IF NOT EXISTS trades (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            position_id     INTEGER REFERENCES positions(id),
            signal_id       INTEGER REFERENCES signals(id),
            ticker          TEXT NOT NULL,
            market          TEXT NOT NULL,
            name            TEXT,
            action          TEXT NOT NULL,
            price           REAL NOT NULL,
            quantity        INTEGER NOT NULL,
            amount          REAL NOT NULL,
            fee             REAL DEFAULT 0,
            slippage        REAL DEFAULT 0,
            fx_rate         REAL,
            profit_loss     REAL,
            profit_pct      REAL,
            hold_hours      REAL,
            exit_reason     TEXT,
            source          TEXT DEFAULT 'manual',
            created_at      TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS daily_summary (
            date            TEXT PRIMARY KEY,
            total_trades    INTEGER DEFAULT 0,
            winning_trades  INTEGER DEFAULT 0,
            total_profit    REAL DEFAULT 0,
            win_rate        REAL DEFAULT 0,
            avg_hold_hours  REAL DEFAULT 0
        );
        """

# Legacy v1 columns → v2 via migrate_db()
_MIGRATIONS = [
    ("signals", "name", "TEXT"),
    ("signals", "ref_price", "REAL"),
    ("signals", "target_price", "REAL"),
    ("signals", "stop_price", "REAL"),
    ("signals", "status", "TEXT DEFAULT 'active'"),
    ("signals", "valid_until", "TEXT"),
    ("signals", "notified_at", "TEXT"),
    ("positions", "signal_id", "INTEGER"),
    ("positions", "remaining_qty", "INTEGER"),
    ("positions", "currency", "TEXT DEFAULT 'KRW'"),
    ("positions", "fx_rate_at_buy", "REAL"),
    ("positions", "source", "TEXT DEFAULT 'manual'"),
    ("trades", "position_id", "INTEGER"),
    ("trades", "signal_id", "INTEGER"),
    ("trades", "fee", "REAL DEFAULT 0"),
    ("trades", "slippage", "REAL DEFAULT 0"),
    ("trades", "fx_rate", "REAL"),
    ("trades", "source", "TEXT DEFAULT 'manual'"),
]


def init_db(db_path: str = DB_PATH) -> None:
    os.makedirs(os.path.dirname(db_path) or ".", exist_ok=True)
    with get_conn(db_path) as conn:
        conn.executescript(_SCHEMA_V2)
        _backfill_remaining_qty(conn)


def _column_exists(conn: sqlite3.Connection, table: str, column: str) -> bool:
    rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    return any(r[1] == column for r in rows)


def _backfill_remaining_qty(conn: sqlite3.Connection) -> None:
    if not _column_exists(conn, "positions", "remaining_qty"):
        return
    conn.execute(
        """UPDATE positions SET remaining_qty = quantity
           WHERE remaining_qty IS NULL AND status = 'open'"""
    )


def migrate_db(db_path: str = DB_PATH) -> None:
    init_db(db_path)
    with get_conn(db_path) as conn:
        for table, col, typedef in _MIGRATIONS:
            if not _column_exists(conn, table, col):
                try:
                    conn.execute(f"ALTER TABLE {table} ADD COLUMN {col} {typedef}")
                except sqlite3.OperationalError:
                    pass
        _backfill_remaining_qty(conn)


@contextmanager
def get_conn(db_path: str = DB_PATH):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


# ── 시그널 ────────────────────────────────────────────────

def log_signal(
    ticker: str,
    market: str,
    signal_type: str,
    confidence: float,
    expected_return: float,
    risk_score: float,
    model_score: float,
    name: Optional[str] = None,
    ref_price: Optional[float] = None,
    valid_until: Optional[str] = None,
    target_price: Optional[float] = None,
    stop_price: Optional[float] = None,
) -> int:
    with get_conn() as conn:
        cur = conn.execute(
            """INSERT INTO signals
               (ticker, market, name, signal_type, confidence, expected_return,
                risk_score, model_score, ref_price, target_price, stop_price,
                status, valid_until, created_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                ticker,
                market,
                name,
                signal_type,
                confidence,
                expected_return,
                risk_score,
                model_score,
                ref_price,
                target_price,
                stop_price,
                "active",
                valid_until,
                datetime.now().isoformat(),
            ),
        )
        return cur.lastrowid


def get_active_signals(limit: int = 50) -> List[Dict]:
    now = datetime.now().isoformat()
    with get_conn() as conn:
        rows = conn.execute(
            """SELECT * FROM signals
               WHERE status = 'active' AND signal_type = 'BUY'
                 AND (valid_until IS NULL OR valid_until > ?)
               ORDER BY created_at DESC LIMIT ?""",
            (now, limit),
        ).fetchall()
        return [dict(r) for r in rows]


def get_signal(signal_id: int) -> Optional[Dict]:
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM signals WHERE id=?", (signal_id,)).fetchone()
        return dict(row) if row else None


def has_recent_signal(ticker: str, signal_type: str, hours: int = 4) -> bool:
    since = (datetime.now() - timedelta(hours=hours)).isoformat()
    with get_conn() as conn:
        row = conn.execute(
            """SELECT 1 FROM signals
               WHERE ticker=? AND signal_type=? AND created_at >= ?
               LIMIT 1""",
            (ticker, signal_type, since),
        ).fetchone()
        return row is not None


def expire_stale_signals() -> int:
    now = datetime.now().isoformat()
    with get_conn() as conn:
        cur = conn.execute(
            """UPDATE signals SET status='expired'
               WHERE status='active' AND valid_until IS NOT NULL AND valid_until < ?""",
            (now,),
        )
        return cur.rowcount


def mark_signal_acted(signal_id: int) -> None:
    with get_conn() as conn:
        conn.execute(
            "UPDATE signals SET status='acted' WHERE id=?",
            (signal_id,),
        )


# ── 포지션 (카카오페이 수동 체결) ─────────────────────────

def open_position_from_signal(
    signal_id: int,
    buy_price: float,
    quantity: int,
    fee: float = 0.0,
) -> int:
    sig = get_signal(signal_id)
    if not sig:
        raise ValueError(f"Signal {signal_id} not found")

    # 시그널 ref_price가 아닌 실제 체결가 기준으로 익절/손절을 재계산.
    # 카카오페이에서 더 싸게 체결됐다면 그 이득이 권고가에 반영되도록.
    target = buy_price * (1 + config.signal.target_return)
    stop = buy_price * (1 + config.signal.stop_loss)
    currency = "KRW" if sig["market"] in ("KOSPI", "KOSDAQ") else "USD"

    with get_conn() as conn:
        cur = conn.execute(
            """INSERT INTO positions
               (signal_id, ticker, market, name, buy_price, quantity, remaining_qty,
                buy_time, target_price, stop_loss, signal_conf, currency, source)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                signal_id,
                sig["ticker"],
                sig["market"],
                sig.get("name"),
                buy_price,
                quantity,
                quantity,
                datetime.now().isoformat(),
                target,
                stop,
                sig.get("confidence"),
                currency,
                "manual",
            ),
        )
        position_id = cur.lastrowid

        amount = buy_price * quantity
        conn.execute(
            """INSERT INTO trades
               (position_id, signal_id, ticker, market, name, action, price, quantity,
                amount, fee, source, created_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                position_id,
                signal_id,
                sig["ticker"],
                sig["market"],
                sig.get("name"),
                "BUY",
                buy_price,
                quantity,
                amount,
                fee,
                "manual",
                datetime.now().isoformat(),
            ),
        )

    mark_signal_acted(signal_id)
    return position_id


def close_position_partial(
    position_id: int,
    sell_price: float,
    quantity: int,
    fee: float = 0.0,
    exit_reason: str = "MANUAL",
) -> None:
    with get_conn() as conn:
        pos = conn.execute(
            "SELECT * FROM positions WHERE id=? AND status='open'",
            (position_id,),
        ).fetchone()
        if not pos:
            raise ValueError(f"Open position {position_id} not found")

        pos = dict(pos)
        qty = min(quantity, pos["remaining_qty"])
        if qty <= 0:
            raise ValueError("Invalid sell quantity")

        buy_price = pos["buy_price"]
        profit_pct = (sell_price / buy_price - 1) * 100
        profit_loss = (sell_price - buy_price) * qty - fee
        buy_time = datetime.fromisoformat(pos["buy_time"])
        hold_hours = (datetime.now() - buy_time).total_seconds() / 3600

        amount = sell_price * qty
        conn.execute(
            """INSERT INTO trades
               (position_id, signal_id, ticker, market, name, action, price, quantity,
                amount, fee, profit_loss, profit_pct, hold_hours, exit_reason, source, created_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                position_id,
                pos.get("signal_id"),
                pos["ticker"],
                pos["market"],
                pos.get("name"),
                "SELL",
                sell_price,
                qty,
                amount,
                fee,
                profit_loss,
                profit_pct,
                hold_hours,
                exit_reason,
                "manual",
                datetime.now().isoformat(),
            ),
        )

        remaining = pos["remaining_qty"] - qty
        if remaining <= 0:
            conn.execute(
                "UPDATE positions SET remaining_qty=0, status='closed' WHERE id=?",
                (position_id,),
            )
        else:
            conn.execute(
                "UPDATE positions SET remaining_qty=? WHERE id=?",
                (remaining, position_id),
            )


def get_open_positions() -> List[Dict]:
    with get_conn() as conn:
        rows = conn.execute(
            """SELECT * FROM positions WHERE status='open' AND remaining_qty > 0
               ORDER BY buy_time DESC"""
        ).fetchall()
        return [dict(r) for r in rows]


# ── 이력 / 통계 ───────────────────────────────────────────

def get_trade_history(limit: int = 50) -> List[Dict]:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM trades ORDER BY created_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [dict(r) for r in rows]


def get_performance_summary() -> Dict:
    with get_conn() as conn:
        total = conn.execute(
            "SELECT COUNT(*) as cnt FROM trades WHERE action='SELL'"
        ).fetchone()["cnt"]

        wins = conn.execute(
            "SELECT COUNT(*) as cnt FROM trades WHERE action='SELL' AND profit_pct > 0"
        ).fetchone()["cnt"]

        avg_return = conn.execute(
            "SELECT AVG(profit_pct) as avg FROM trades WHERE action='SELL'"
        ).fetchone()["avg"] or 0.0

        avg_hold = conn.execute(
            "SELECT AVG(hold_hours) as avg FROM trades WHERE action='SELL'"
        ).fetchone()["avg"] or 0.0

        total_profit = conn.execute(
            "SELECT SUM(profit_loss) as total FROM trades WHERE action='SELL'"
        ).fetchone()["total"] or 0.0

    return {
        "total_trades": total,
        "winning_trades": wins,
        "win_rate": (wins / total * 100) if total > 0 else 0.0,
        "avg_return_pct": avg_return,
        "avg_hold_hours": avg_hold,
        "total_profit": total_profit,
    }
