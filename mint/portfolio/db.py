"""
Mint - 포트폴리오 DB
SQLAlchemy 기반. DATABASE_URL env로 sqlite:///mint.db 기본, postgresql:// 등 지원.
매매 이력, 보유 종목, 시그널 추적 (signals ↔ positions ↔ trades).
Cloud Migration (2026-05-21): SQLite ↔ Postgres 양쪽 호환.
"""
import os
import logging
from datetime import datetime, timedelta
from contextlib import contextmanager
from typing import Optional, List, Dict, Iterable

import pandas as pd
from sqlalchemy import create_engine, text, bindparam, event
from sqlalchemy.engine import Engine

from config.settings import config

log = logging.getLogger("mint.db")

DB_PATH = os.environ.get("MINT_DB_PATH", config.db.path)
DATABASE_URL = os.environ.get("DATABASE_URL", f"sqlite:///{DB_PATH}")

_engine: Optional[Engine] = None


def _get_engine() -> Engine:
    global _engine
    if _engine is None:
        connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}
        _engine = create_engine(DATABASE_URL, future=True, connect_args=connect_args)
        # SQLite FK 활성화 (postgres는 기본 ON)
        if _engine.dialect.name == "sqlite":
            @event.listens_for(_engine, "connect")
            def _fk_on(dbapi_conn, _):
                try:
                    dbapi_conn.execute("PRAGMA foreign_keys=ON")
                except Exception:
                    pass
    return _engine


def _is_sqlite() -> bool:
    return _get_engine().dialect.name == "sqlite"


# ── 스키마 ────────────────────────────────────────────────

def _pk() -> str:
    """dialect별 PRIMARY KEY 정의 (auto-increment 포함)."""
    return "INTEGER PRIMARY KEY AUTOINCREMENT" if _is_sqlite() else "BIGSERIAL PRIMARY KEY"


def _schema_statements() -> List[str]:
    pk = _pk()
    return [
        f"""CREATE TABLE IF NOT EXISTS signals (
            id              {pk},
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
        )""",
        f"""CREATE TABLE IF NOT EXISTS positions (
            id              {pk},
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
        )""",
        f"""CREATE TABLE IF NOT EXISTS trades (
            id              {pk},
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
        )""",
        """CREATE TABLE IF NOT EXISTS daily_summary (
            date            TEXT PRIMARY KEY,
            total_trades    INTEGER DEFAULT 0,
            winning_trades  INTEGER DEFAULT 0,
            total_profit    REAL DEFAULT 0,
            win_rate        REAL DEFAULT 0,
            avg_hold_hours  REAL DEFAULT 0
        )""",
        # Cloud Migration Phase 2 — 토큰/상태 영속화 (GHA 휘발 컨테이너 대응)
        """CREATE TABLE IF NOT EXISTS auth_tokens (
            service             TEXT PRIMARY KEY,
            access_token        TEXT,
            refresh_token       TEXT,
            expires_at          TEXT,
            refresh_expires_at  TEXT,
            updated_at          TEXT
        )""",
        """CREATE TABLE IF NOT EXISTS app_state (
            key         TEXT PRIMARY KEY,
            value       TEXT,
            updated_at  TEXT
        )""",
    ]


_MIGRATIONS = [
    ("signals", "name", "TEXT"),
    ("signals", "ref_price", "REAL"),
    ("signals", "target_price", "REAL"),
    ("signals", "stop_price", "REAL"),
    ("signals", "status", "TEXT DEFAULT 'active'"),
    ("signals", "valid_until", "TEXT"),
    ("signals", "notified_at", "TEXT"),
    ("signals", "expiry_reason", "TEXT"),
    ("signals", "expiry_notified", "INTEGER DEFAULT 0"),
    ("signals", "expiry_price", "REAL"),
    ("signals", "outcome", "TEXT"),
    ("signals", "outcome_max", "REAL"),
    ("signals", "outcome_min", "REAL"),
    ("signals", "outcome_evaluated_at", "TEXT"),
    # 2026-05-22 Dynamic exit (시장 regime + ATR 기반 종목별 target/stop/hold)
    ("signals", "max_hold_hours", "REAL"),
    ("signals", "regime_label", "TEXT"),
    ("positions", "max_hold_hours", "REAL"),
    ("positions", "regime_label", "TEXT"),
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


def init_db(db_path: Optional[str] = None) -> None:
    # db_path는 sqlite 경로 호환용. SQLAlchemy URL은 모듈 import 시점에 고정.
    if db_path and DATABASE_URL.startswith("sqlite"):
        os.makedirs(os.path.dirname(db_path) or ".", exist_ok=True)
    engine = _get_engine()
    with engine.begin() as conn:
        for stmt in _schema_statements():
            conn.exec_driver_sql(stmt)
    with get_conn() as conn:
        _backfill_remaining_qty(conn)


def _existing_columns(conn, table: str) -> set:
    if _is_sqlite():
        rows = conn.execute(text(f"PRAGMA table_info({table})")).fetchall()
        return {r[1] for r in rows}
    # postgres
    rows = conn.execute(
        text("""SELECT column_name FROM information_schema.columns
                WHERE table_name=:t"""),
        {"t": table},
    ).fetchall()
    return {r[0] for r in rows}


def _backfill_remaining_qty(conn) -> None:
    cols = _existing_columns(conn, "positions")
    if "remaining_qty" not in cols:
        return
    conn.execute(
        text("""UPDATE positions SET remaining_qty = quantity
                WHERE remaining_qty IS NULL AND status = 'open'""")
    )


def migrate_db(db_path: Optional[str] = None) -> None:
    init_db(db_path)
    engine = _get_engine()
    with engine.begin() as conn:
        for table, col, typedef in _MIGRATIONS:
            cols = _existing_columns(conn, table)
            if col in cols:
                continue
            try:
                conn.exec_driver_sql(f"ALTER TABLE {table} ADD COLUMN {col} {typedef}")
            except Exception as e:
                log.debug("ALTER TABLE %s ADD %s skipped: %s", table, col, e)
    with get_conn() as conn:
        _backfill_remaining_qty(conn)


@contextmanager
def get_conn(db_path: Optional[str] = None):
    """SQLAlchemy connection with auto-commit/rollback.
    yield 받은 conn은 .execute(text(sql), {params}) 호출. fetchall/fetchone/scalar 가능.
    """
    engine = _get_engine()
    conn = engine.connect()
    trans = conn.begin()
    try:
        yield conn
        trans.commit()
    except Exception:
        trans.rollback()
        raise
    finally:
        conn.close()


def _rows_to_dicts(rows) -> List[Dict]:
    return [dict(r._mapping) for r in rows]


def _row_to_dict(row) -> Optional[Dict]:
    return dict(row._mapping) if row is not None else None


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
    max_hold_hours: Optional[float] = None,
    regime_label: Optional[str] = None,
) -> int:
    with get_conn() as conn:
        result = conn.execute(
            text("""INSERT INTO signals
               (ticker, market, name, signal_type, confidence, expected_return,
                risk_score, model_score, ref_price, target_price, stop_price,
                status, valid_until, created_at, max_hold_hours, regime_label)
               VALUES (:ticker, :market, :name, :signal_type, :confidence, :expected_return,
                       :risk_score, :model_score, :ref_price, :target_price, :stop_price,
                       :status, :valid_until, :created_at, :max_hold_hours, :regime_label)
               RETURNING id"""),
            {
                "ticker": ticker,
                "market": market,
                "name": name,
                "signal_type": signal_type,
                "confidence": confidence,
                "expected_return": expected_return,
                "risk_score": risk_score,
                "model_score": model_score,
                "ref_price": ref_price,
                "target_price": target_price,
                "stop_price": stop_price,
                "status": "active",
                "valid_until": valid_until,
                "created_at": datetime.now().isoformat(),
                "max_hold_hours": max_hold_hours,
                "regime_label": regime_label,
            },
        )
        return int(result.scalar_one())


def get_active_signals(limit: int = 50) -> List[Dict]:
    now = datetime.now().isoformat()
    with get_conn() as conn:
        rows = conn.execute(
            text("""SELECT * FROM signals
               WHERE status = 'active' AND signal_type = 'BUY'
                 AND (valid_until IS NULL OR valid_until > :now)
               ORDER BY created_at DESC LIMIT :lim"""),
            {"now": now, "lim": limit},
        ).fetchall()
        return _rows_to_dicts(rows)


def get_signal(signal_id: int) -> Optional[Dict]:
    with get_conn() as conn:
        row = conn.execute(
            text("SELECT * FROM signals WHERE id = :id"),
            {"id": signal_id},
        ).fetchone()
        return _row_to_dict(row)


def has_recent_signal(ticker: str, signal_type: str, hours: int = 4) -> bool:
    since = (datetime.now() - timedelta(hours=hours)).isoformat()
    with get_conn() as conn:
        row = conn.execute(
            text("""SELECT 1 FROM signals
               WHERE ticker = :t AND signal_type = :st AND created_at >= :since
               LIMIT 1"""),
            {"t": ticker, "st": signal_type, "since": since},
        ).fetchone()
        return row is not None


def expire_stale_signals() -> int:
    """시간 만료된 active 시그널을 expired로. 만료 사유는 'TIME'."""
    now = datetime.now().isoformat()
    with get_conn() as conn:
        result = conn.execute(
            text("""UPDATE signals
               SET status = 'expired',
                   expiry_reason = COALESCE(expiry_reason, 'TIME')
               WHERE status = 'active'
                 AND valid_until IS NOT NULL AND valid_until < :now"""),
            {"now": now},
        )
        return int(result.rowcount or 0)


def check_price_expiry() -> List[Dict]:
    """active 시그널 중 KIS 현재가 기준 target/stop 도달 → expired 처리.
    반환: 새로 만료된 시그널 dict 리스트 (expiry_reason, expiry_price 포함).
    KIS 미설정/실패한 종목은 skip.
    """
    from data import kis_client  # 순환 방지 위해 함수 내 import

    newly: List[Dict] = []
    with get_conn() as conn:
        rows = conn.execute(
            text("""SELECT * FROM signals
               WHERE status = 'active' AND signal_type = 'BUY'
                 AND market IN ('KOSPI','KOSDAQ')
                 AND target_price IS NOT NULL AND stop_price IS NOT NULL""")
        ).fetchall()
        active = _rows_to_dicts(rows)

    for sig in active:
        try:
            kp = kis_client.get_current_price(sig["ticker"])
        except Exception:
            continue
        if not kp:
            continue

        reason = None
        if kp.price >= float(sig["target_price"]):
            reason = "TARGET_HIT"
        elif kp.price <= float(sig["stop_price"]):
            reason = "STOP_HIT"
        if not reason:
            continue

        with get_conn() as conn:
            conn.execute(
                text("""UPDATE signals
                   SET status = 'expired', expiry_reason = :reason, expiry_price = :price
                   WHERE id = :id AND status = 'active'"""),
                {"reason": reason, "price": kp.price, "id": sig["id"]},
            )
        newly.append({**sig, "expiry_reason": reason, "expiry_price": kp.price})

    return newly


def unnotified_expired_signals() -> List[Dict]:
    """만료 알림 아직 안 보낸 시그널 목록."""
    with get_conn() as conn:
        rows = conn.execute(
            text("""SELECT * FROM signals
               WHERE status = 'expired'
                 AND (expiry_notified IS NULL OR expiry_notified = 0)
               ORDER BY id ASC""")
        ).fetchall()
        return _rows_to_dicts(rows)


def mark_expiry_notified(signal_ids: List[int]) -> None:
    if not signal_ids:
        return
    stmt = text("UPDATE signals SET expiry_notified = 1 WHERE id IN :ids").bindparams(
        bindparam("ids", expanding=True)
    )
    with get_conn() as conn:
        conn.execute(stmt, {"ids": list(signal_ids)})


def _evaluate_single_outcome(sig: dict) -> Optional[dict]:
    """단일 시그널 outcome 평가. 시간 미경과 or 데이터 부족 시 None.

    반환: {'outcome', 'outcome_max', 'outcome_min'} 또는 None
    - outcome: 'WIN' (target 먼저 도달), 'LOSS' (stop 먼저), 'TIME_EXIT' (둘 다 안 도달)
    """
    from datetime import datetime as _dt
    from datetime import timedelta as _td
    from config.settings import config as _cfg
    from config.tz import to_kst, now_kst
    from data import krx_client as _krx

    try:
        created = _dt.fromisoformat(sig["created_at"])
    except Exception:
        return None
    # created_at은 tz-naive(과거 호환) 또는 tz-aware. 둘 다 KST로 통일 — bars["ts_local"]이 KST tz-aware이므로 비교 정합.
    created = to_kst(created)
    # 시그널별 동적 max_hold_hours 우선, 없으면 config 기본값 (24h).
    horizon_h = float(sig.get("max_hold_hours") or _cfg.signal.max_hold_hours)
    if now_kst() < created + _td(hours=horizon_h):
        return None

    target = sig.get("target_price")
    stop = sig.get("stop_price")
    ref = sig.get("ref_price")
    if not target or not stop or not ref:
        return None

    if sig.get("market") not in ("KOSPI", "KOSDAQ"):
        return None

    try:
        bars = _krx.fetch_daily_bars(sig["ticker"], sig["market"], days=5)
    except Exception:
        return None
    if bars is None or bars.empty:
        return None

    bars = bars.copy()
    bars["ts_local"] = pd.to_datetime(bars["ts_local"])
    after = bars[bars["ts_local"] > created]
    if after.empty:
        return None

    horizon_days = max(1, horizon_h // 24)
    after = after.head(horizon_days).reset_index(drop=True)

    max_h = float(after["high"].max())
    min_l = float(after["low"].min())
    last_close = float(after["close"].iloc[-1])

    outcome = "TIME_EXIT"
    # 같은 봉에서 둘 다 터치하면 보수적으로 LOSS (백테스트 관례)
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

    return {
        "outcome": outcome,
        "outcome_max": max_h,
        "outcome_min": min_l,
        "outcome_close": last_close,
    }


def evaluate_pending_outcomes(limit: int = 50) -> int:
    """미평가(outcome IS NULL) 시그널들 중 시간 경과한 것 일괄 평가.
    반환: 새로 평가된 시그널 수.
    """
    with get_conn() as conn:
        rows = conn.execute(
            text("""SELECT * FROM signals
               WHERE outcome IS NULL AND signal_type = 'BUY'
                 AND created_at IS NOT NULL
               ORDER BY created_at ASC
               LIMIT :lim"""),
            {"lim": limit},
        ).fetchall()
        pending = _rows_to_dicts(rows)

    evaluated = 0
    for sig in pending:
        result = _evaluate_single_outcome(sig)
        if result is None:
            continue
        with get_conn() as conn:
            conn.execute(
                text("""UPDATE signals
                   SET outcome = :o, outcome_max = :omax, outcome_min = :omin,
                       outcome_evaluated_at = :ea
                   WHERE id = :id"""),
                {
                    "o": result["outcome"],
                    "omax": result["outcome_max"],
                    "omin": result["outcome_min"],
                    "ea": datetime.now().isoformat(),
                    "id": sig["id"],
                },
            )
        evaluated += 1
    return evaluated


def get_outcome_stats(days: int = 30) -> dict:
    """최근 days일 시그널의 outcome 분포 + win rate."""
    since = (datetime.now() - timedelta(days=days)).isoformat()
    with get_conn() as conn:
        rows = conn.execute(
            text("""SELECT outcome, COUNT(*) as n FROM signals
               WHERE signal_type = 'BUY' AND created_at >= :since
                 AND outcome IS NOT NULL
               GROUP BY outcome"""),
            {"since": since},
        ).fetchall()

    counts = {r._mapping["outcome"]: r._mapping["n"] for r in rows}
    win = counts.get("WIN", 0)
    loss = counts.get("LOSS", 0)
    time_exit = counts.get("TIME_EXIT", 0)
    total = win + loss + time_exit
    win_rate = (win / total) if total else None
    return {
        "days": days,
        "total": total,
        "win": win,
        "loss": loss,
        "time_exit": time_exit,
        "win_rate": win_rate,
    }


def mark_signal_acted(signal_id: int) -> None:
    with get_conn() as conn:
        conn.execute(
            text("UPDATE signals SET status = 'acted' WHERE id = :id"),
            {"id": signal_id},
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
    # Dynamic exit: 시그널이 가진 dynamic target/stop/hold가 있으면 그 비율을 체결가에 적용.
    if sig.get("target_price") and sig.get("ref_price"):
        target_ratio = float(sig["target_price"]) / float(sig["ref_price"]) - 1
        target = buy_price * (1 + target_ratio)
    else:
        target = buy_price * (1 + config.signal.target_return)
    if sig.get("stop_price") and sig.get("ref_price"):
        stop_ratio = float(sig["stop_price"]) / float(sig["ref_price"]) - 1
        stop = buy_price * (1 + stop_ratio)
    else:
        stop = buy_price * (1 + config.signal.stop_loss)
    max_hold = sig.get("max_hold_hours") or float(config.signal.max_hold_hours)
    regime = sig.get("regime_label")
    currency = "KRW" if sig["market"] in ("KOSPI", "KOSDAQ") else "USD"
    now = datetime.now().isoformat()

    with get_conn() as conn:
        result = conn.execute(
            text("""INSERT INTO positions
               (signal_id, ticker, market, name, buy_price, quantity, remaining_qty,
                buy_time, target_price, stop_loss, signal_conf, currency, source,
                max_hold_hours, regime_label)
               VALUES (:signal_id, :ticker, :market, :name, :buy_price, :quantity, :remaining,
                       :buy_time, :target, :stop, :sigconf, :currency, :source,
                       :max_hold, :regime)
               RETURNING id"""),
            {
                "signal_id": signal_id,
                "ticker": sig["ticker"],
                "market": sig["market"],
                "name": sig.get("name"),
                "buy_price": buy_price,
                "quantity": quantity,
                "remaining": quantity,
                "buy_time": now,
                "target": target,
                "stop": stop,
                "sigconf": sig.get("confidence"),
                "currency": currency,
                "source": "manual",
                "max_hold": max_hold,
                "regime": regime,
            },
        )
        position_id = int(result.scalar_one())

        amount = buy_price * quantity
        conn.execute(
            text("""INSERT INTO trades
               (position_id, signal_id, ticker, market, name, action, price, quantity,
                amount, fee, source, created_at)
               VALUES (:position_id, :signal_id, :ticker, :market, :name, :action, :price, :qty,
                       :amount, :fee, :source, :created_at)"""),
            {
                "position_id": position_id,
                "signal_id": signal_id,
                "ticker": sig["ticker"],
                "market": sig["market"],
                "name": sig.get("name"),
                "action": "BUY",
                "price": buy_price,
                "qty": quantity,
                "amount": amount,
                "fee": fee,
                "source": "manual",
                "created_at": now,
            },
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
        row = conn.execute(
            text("SELECT * FROM positions WHERE id = :id AND status = 'open'"),
            {"id": position_id},
        ).fetchone()
        pos = _row_to_dict(row)
        if not pos:
            raise ValueError(f"Open position {position_id} not found")

        qty = min(quantity, pos["remaining_qty"])
        if qty <= 0:
            raise ValueError("Invalid sell quantity")

        buy_price = pos["buy_price"]
        profit_pct = (sell_price / buy_price - 1) * 100
        profit_loss = (sell_price - buy_price) * qty - fee
        buy_time = datetime.fromisoformat(pos["buy_time"])
        hold_hours = (datetime.now() - buy_time).total_seconds() / 3600
        amount = sell_price * qty
        now = datetime.now().isoformat()

        conn.execute(
            text("""INSERT INTO trades
               (position_id, signal_id, ticker, market, name, action, price, quantity,
                amount, fee, profit_loss, profit_pct, hold_hours, exit_reason, source, created_at)
               VALUES (:position_id, :signal_id, :ticker, :market, :name, :action, :price, :qty,
                       :amount, :fee, :pl, :pp, :hh, :reason, :source, :created_at)"""),
            {
                "position_id": position_id,
                "signal_id": pos.get("signal_id"),
                "ticker": pos["ticker"],
                "market": pos["market"],
                "name": pos.get("name"),
                "action": "SELL",
                "price": sell_price,
                "qty": qty,
                "amount": amount,
                "fee": fee,
                "pl": profit_loss,
                "pp": profit_pct,
                "hh": hold_hours,
                "reason": exit_reason,
                "source": "manual",
                "created_at": now,
            },
        )

        remaining = pos["remaining_qty"] - qty
        if remaining <= 0:
            conn.execute(
                text("UPDATE positions SET remaining_qty = 0, status = 'closed' WHERE id = :id"),
                {"id": position_id},
            )
        else:
            conn.execute(
                text("UPDATE positions SET remaining_qty = :r WHERE id = :id"),
                {"r": remaining, "id": position_id},
            )


def get_open_positions() -> List[Dict]:
    with get_conn() as conn:
        rows = conn.execute(
            text("""SELECT * FROM positions WHERE status = 'open' AND remaining_qty > 0
               ORDER BY buy_time DESC""")
        ).fetchall()
        return _rows_to_dicts(rows)


# ── 이력 / 통계 ───────────────────────────────────────────

def get_trade_history(limit: int = 50) -> List[Dict]:
    with get_conn() as conn:
        rows = conn.execute(
            text("SELECT * FROM trades ORDER BY created_at DESC LIMIT :lim"),
            {"lim": limit},
        ).fetchall()
        return _rows_to_dicts(rows)


def get_performance_summary() -> Dict:
    with get_conn() as conn:
        total = conn.execute(
            text("SELECT COUNT(*) AS cnt FROM trades WHERE action = 'SELL'")
        ).scalar() or 0

        wins = conn.execute(
            text("SELECT COUNT(*) AS cnt FROM trades WHERE action = 'SELL' AND profit_pct > 0")
        ).scalar() or 0

        avg_return = conn.execute(
            text("SELECT AVG(profit_pct) AS avg FROM trades WHERE action = 'SELL'")
        ).scalar() or 0.0

        avg_hold = conn.execute(
            text("SELECT AVG(hold_hours) AS avg FROM trades WHERE action = 'SELL'")
        ).scalar() or 0.0

        total_profit = conn.execute(
            text("SELECT SUM(profit_loss) AS total FROM trades WHERE action = 'SELL'")
        ).scalar() or 0.0

    return {
        "total_trades": int(total),
        "winning_trades": int(wins),
        "win_rate": (wins / total * 100) if total > 0 else 0.0,
        "avg_return_pct": float(avg_return),
        "avg_hold_hours": float(avg_hold),
        "total_profit": float(total_profit),
    }


# ── 인증 토큰 / 앱 상태 (Cloud Migration Phase 2) ──────────────

def get_auth_token(service: str) -> Optional[Dict]:
    """service='kakao'|'kis'. 없으면 None."""
    with get_conn() as conn:
        row = conn.execute(
            text("SELECT * FROM auth_tokens WHERE service = :s"),
            {"s": service},
        ).fetchone()
        return _row_to_dict(row)


def save_auth_token(
    service: str,
    access_token: Optional[str],
    refresh_token: Optional[str] = None,
    expires_at: Optional[str] = None,
    refresh_expires_at: Optional[str] = None,
) -> None:
    now = datetime.now().isoformat()
    with get_conn() as conn:
        # UPSERT: sqlite/postgres 모두 ON CONFLICT 지원 (sqlite 3.24+, postgres 9.5+)
        conn.execute(
            text("""INSERT INTO auth_tokens
               (service, access_token, refresh_token, expires_at, refresh_expires_at, updated_at)
               VALUES (:s, :a, :r, :e, :re, :u)
               ON CONFLICT(service) DO UPDATE SET
                 access_token = excluded.access_token,
                 refresh_token = excluded.refresh_token,
                 expires_at = excluded.expires_at,
                 refresh_expires_at = excluded.refresh_expires_at,
                 updated_at = excluded.updated_at"""),
            {
                "s": service,
                "a": access_token,
                "r": refresh_token,
                "e": expires_at,
                "re": refresh_expires_at,
                "u": now,
            },
        )


def get_app_state(key: str) -> Optional[str]:
    with get_conn() as conn:
        row = conn.execute(
            text("SELECT value FROM app_state WHERE key = :k"),
            {"k": key},
        ).fetchone()
        return row._mapping["value"] if row else None


def set_app_state(key: str, value: str) -> None:
    now = datetime.now().isoformat()
    with get_conn() as conn:
        conn.execute(
            text("""INSERT INTO app_state (key, value, updated_at)
               VALUES (:k, :v, :u)
               ON CONFLICT(key) DO UPDATE SET
                 value = excluded.value,
                 updated_at = excluded.updated_at"""),
            {"k": key, "v": value, "u": now},
        )
