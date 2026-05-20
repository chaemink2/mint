"""
Mint - 메인 실행 진입점

기본: 단발 스캔 (PC 가끔 켜는 운영)
  python mint/main.py scan
  python mint/main.py catch-up

상시 스케줄러 (선택, MINT_DAEMON=1):
  python mint/main.py daemon
"""
import argparse
import logging
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from datetime import datetime

from config.settings import config
from portfolio.db import (
    init_db, migrate_db, expire_stale_signals, get_open_positions,
    check_price_expiry, unnotified_expired_signals, mark_expiry_notified,
    evaluate_pending_outcomes, get_outcome_stats,
)
from engine.signals.rule_scanner import run_rule_scan
from engine.signals.exit_strategy import evaluate_positions

logging.basicConfig(
    level=getattr(logging, config.log_level),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
# pykrx 내부 `logging.info(args, kwargs)` (잘못된 포맷 호출)이 root 로거로 흘러와 시끄러움.
# 우리는 ticker 실패를 이미 except 처리하므로 root는 WARNING, mint.*만 INFO 유지.
logging.getLogger().setLevel(logging.WARNING)
logging.getLogger("pykrx").setLevel(logging.WARNING)
logging.getLogger("mint").setLevel(getattr(logging, config.log_level))
log = logging.getLogger("mint.main")


def _setup_log_file():
    os.makedirs(config.log_path, exist_ok=True)
    fh = logging.FileHandler(
        os.path.join(config.log_path, f"mint_{datetime.now().strftime('%Y%m%d')}.log"),
        encoding="utf-8",
    )
    fh.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s"))
    logging.getLogger().addHandler(fh)


def _notify_buys(ids):
    if not ids:
        return
    try:
        from notifier import notify_buy_signals
        notify_buy_signals(ids)
    except Exception as e:
        log.warning("notifier failure (buy): %s", e)


def _process_expiries():
    """시간 만료 + 가격 도달 만료를 처리하고 사용자에게 카톡 알림.
    scan/catch-up 시작 시 호출. 알림 중복 방지(expiry_notified 마킹).
    """
    try:
        time_count = expire_stale_signals()
        if time_count:
            log.info("Expired by time: %d signal(s)", time_count)
        price_expired = check_price_expiry()
        if price_expired:
            log.info("Expired by price: %d signal(s)", len(price_expired))

        pending = unnotified_expired_signals()
        if pending:
            from notifier import notify_expired_signals
            notify_expired_signals(pending)
            mark_expiry_notified([s["id"] for s in pending])
    except Exception as e:
        log.warning("expiry processing failed: %s", e)


def cmd_scan():
    """KR 워치리스트 룰 스캔 → signals DB. MINT_US_SCAN=true면 NASDAQ도 포함."""
    init_db()
    migrate_db()
    markets = ["KOSPI", "KOSDAQ"]
    if config.ops.enable_us_market_scan:
        markets.append("NASDAQ")
    try:
        from notifier import maybe_send_heartbeat, maybe_send_midday_ping
        maybe_send_heartbeat(markets)
        maybe_send_midday_ping(markets)
    except Exception as e:
        log.warning("heartbeat/midday failure: %s", e)

    # 만료된 시그널 정리 + 알림 (BEFORE new scan: 사용자가 새 시그널 보기 전에 죽은 거 알림)
    _process_expiries()

    ids = run_rule_scan(markets=markets)
    log.info("Scan finished — %s signal(s) logged (markets=%s)", len(ids), markets)
    _notify_buys(ids)
    return ids


def cmd_scan_us():
    """US-only scan (daemon에서 야간 호출용)."""
    init_db()
    migrate_db()
    # KR 시그널 만료/알림도 같이 처리 (사용자가 자고 있는 동안 만료된 거 정리)
    _process_expiries()
    ids = run_rule_scan(markets=["NASDAQ"])
    log.info("US scan finished — %s signal(s) logged", len(ids))
    _notify_buys(ids)
    return ids


def cmd_catch_up():
    """PC 재실행 시: stale 시그널 만료 + 보유 포지션 매도 권고 로그."""
    init_db()
    migrate_db()
    _process_expiries()

    positions = get_open_positions()
    if not positions:
        log.info("No open positions")
        return

    advices = evaluate_positions(positions)
    for adv in advices:
        log.info(
            "[%s] %s (%s) %s %s — 현재 %.0f / 매수 %.0f (%+.2f%%) · 보유 %.1fh%s",
            adv.action,
            adv.name or adv.ticker,
            adv.ticker,
            adv.reason,
            "🟢" if adv.profit_pct >= 0 else "🔴",
            adv.current_price,
            adv.buy_price,
            adv.profit_pct,
            adv.hold_hours,
            f" — {adv.note}" if adv.note else "",
        )
    log.info(
        "매도 권고: 손절/익절은 카카오페이 앱에서 실행하세요 (Mint는 자동 주문하지 않습니다)"
    )

    try:
        from notifier import notify_exit_advices
        notify_exit_advices(advices)
    except Exception as e:
        log.warning("notifier failure (exit): %s", e)


def cmd_daemon():
    """선택: 상시 스케줄러 (MINT_US_SCAN으로 US 스캔 on/off)."""
    from apscheduler.schedulers.blocking import BlockingScheduler
    from apscheduler.triggers.cron import CronTrigger

    _setup_log_file()
    init_db()
    migrate_db()

    scheduler = BlockingScheduler(timezone="Asia/Seoul")
    scheduler.add_job(
        cmd_scan,
        CronTrigger(day_of_week="mon-fri", hour="9-15", minute="*/10"),
        id="scan_kr",
    )
    if config.ops.enable_us_market_scan:
        scheduler.add_job(
            cmd_scan_us,
            CronTrigger(day_of_week="mon-fri", hour="23,0,1,2,3,4,5", minute="*/10"),
            id="scan_us",
        )
    scheduler.add_job(
        cmd_catch_up,
        CronTrigger(day_of_week="mon-fri", hour="8", minute="50"),
        id="catch_up_morning",
    )
    scheduler.add_job(
        cmd_daily_summary,
        CronTrigger(day_of_week="mon-fri", hour="15", minute="35"),
        id="daily_summary",
    )

    log.info("Daemon scheduler started (US scan=%s)", config.ops.enable_us_market_scan)
    try:
        scheduler.start()
    except KeyboardInterrupt:
        log.info("Mint daemon stopped")


def cmd_outcomes():
    """미평가 시그널의 24h 후 outcome (WIN/LOSS/TIME_EXIT) 일괄 평가."""
    init_db()
    migrate_db()
    n = evaluate_pending_outcomes(limit=200)
    log.info("Outcome evaluated: %d signal(s)", n)
    s7 = get_outcome_stats(days=7)
    s30 = get_outcome_stats(days=30)
    log.info(
        "Win rate — 7d: %s (%d/%d), 30d: %s (%d/%d)",
        f"{s7['win_rate']:.2%}" if s7['win_rate'] is not None else "n/a",
        s7['win'], s7['total'],
        f"{s30['win_rate']:.2%}" if s30['win_rate'] is not None else "n/a",
        s30['win'], s30['total'],
    )


def cmd_daily_summary():
    """장 마감 후 1회: 오늘 매수 시그널/포지션/매도권고 + 누적 win rate 카톡."""
    init_db()
    migrate_db()

    # outcome 평가 먼저 (24h 지난 시그널들 자동 채움)
    evaluated = evaluate_pending_outcomes(limit=200)
    if evaluated:
        log.info("Outcomes evaluated for %d signal(s)", evaluated)

    from datetime import datetime, timedelta
    from portfolio.db import get_conn

    today = datetime.now().strftime("%Y-%m-%d")
    start = f"{today}T00:00:00"
    end = (datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
           + timedelta(days=1)).strftime("%Y-%m-%dT%H:%M:%S")

    with get_conn() as conn:
        buy_today = conn.execute(
            """SELECT COUNT(*) FROM signals
               WHERE signal_type='BUY' AND created_at >= ? AND created_at < ?""",
            (start, end),
        ).fetchone()[0]

    positions = get_open_positions()
    advices = evaluate_positions(positions) if positions else []
    non_hold = [a for a in advices if a.action != "HOLD"]

    extra = []
    for a in non_hold[:3]:
        extra.append(f"  · {a.action} {a.name or a.ticker} ({a.profit_pct:+.2f}%)")

    # 누적 win rate (최근 7일, 30일)
    s7 = get_outcome_stats(days=7)
    s30 = get_outcome_stats(days=30)
    stats_lines = []

    # 오늘 시장 지수 (Naver API)
    try:
        from data.market_index import format_summary_line
        idx_line = format_summary_line()
        if idx_line:
            stats_lines.append(idx_line)
    except Exception as e:
        log.debug("market index fetch failed: %s", e)

    # 오늘 스캔 funnel (카드 b) — 시그널 0건일 때 어디서 막혔는지 보여줌
    try:
        from notifier import get_today_scan_stats
        fs = get_today_scan_stats()
        if fs.get("scans"):
            funnel = (
                f"🔍 오늘 스캔 {fs.get('scans',0)}회: "
                f"평가 {fs.get('evaluated',0)} → "
                f"모멘텀 {fs.get('passed_momentum',0)} → "
                f"리스크 {fs.get('passed_risk',0)} → "
                f"거래량 {fs.get('passed_volume',0)}"
            )
            if fs.get("passed_ml") is not None and fs.get("passed_ml", 0) > 0 or "passed_ml" in fs:
                funnel += f" → ML {fs.get('passed_ml',0)}"
            if fs.get("passed_minute", 0) > 0 or "passed_minute" in fs:
                funnel += f" → 분봉 {fs.get('passed_minute',0)}"
            funnel += f" → 시그널 {fs.get('signals_created',0)}"
            if fs.get("skipped_dedup", 0):
                funnel += f" (중복 skip {fs['skipped_dedup']})"
            stats_lines.append(funnel)
    except Exception as e:
        log.debug("scan funnel fetch failed: %s", e)

    if s7["total"]:
        stats_lines.append(
            f"📈 최근 7일 Win rate: {s7['win_rate']*100:.0f}% "
            f"(W{s7['win']}/L{s7['loss']}/T{s7['time_exit']})"
        )
    if s30["total"]:
        stats_lines.append(
            f"📈 최근 30일 Win rate: {s30['win_rate']*100:.0f}% "
            f"(W{s30['win']}/L{s30['loss']}/T{s30['time_exit']})"
        )

    log.info(
        "Daily summary: BUY=%d, positions=%d, exit_advices(non-HOLD)=%d, 7d_win=%s",
        buy_today, len(positions), len(non_hold),
        f"{s7['win_rate']:.2%}" if s7['win_rate'] is not None else "n/a",
    )
    try:
        from notifier import send_daily_summary
        send_daily_summary(
            buy_count=buy_today,
            open_positions=len(positions),
            exit_actions=len(non_hold),
            extra_lines=(extra + stats_lines) or None,
        )
    except Exception as e:
        log.warning("daily summary notify failure: %s", e)


def cmd_backtest(markets: list, days: int, max_hold_days: int) -> None:
    from engine.backtest import print_summary, run_backtest, save_csv, summarize

    log.info("Backtest start — markets=%s days=%s", markets, days)
    trades = run_backtest(markets=markets, days=days, max_hold_days=max_hold_days)
    summary = summarize(trades)
    print_summary(summary, markets, days)

    if trades:
        path = save_csv(trades)
        log.info("Trades saved → %s", path)


def cmd_train(markets: list, days: int, max_hold_days: int,
              universe_size: int | None) -> None:
    """LightGBM 학습 → mint/data/models/mint_lgbm.joblib 저장."""
    try:
        from engine.training import print_training_report, run_training
    except Exception as e:
        log.error("학습 모듈 로드 실패: %s", e)
        return

    try:
        result = run_training(
            markets=markets, days=days, max_hold_days=max_hold_days,
            universe_size=universe_size,
        )
    except RuntimeError as e:
        log.error("%s", e)
        return
    print_training_report(result)


def main():
    parser = argparse.ArgumentParser(description="Mint — short-term trading signals")
    parser.add_argument(
        "command",
        nargs="?",
        default="scan",
        choices=["scan", "catch-up", "daemon", "backtest", "train", "daily-summary", "outcomes"],
        help="scan (default): one-shot KR rule scan",
    )
    parser.add_argument("--markets", nargs="+", default=None,
                        help="backtest/train 대상 (KOSPI KOSDAQ NASDAQ)")
    parser.add_argument("--days", type=int, default=180,
                        help="backtest 일수 (기본 180, train 미지정시 365)")
    parser.add_argument("--max-hold-days", type=int, default=1,
                        help="backtest/train 최대 보유일 (기본 1)")
    parser.add_argument("--watchlist-size", type=int, default=None,
                        help="시총 상위 N개 동적 워치리스트 (KR만). 미지정시 static 10개")
    args = parser.parse_args()

    _setup_log_file()
    log.info("Mint command: %s", args.command)

    if args.command == "scan":
        cmd_scan()
    elif args.command == "catch-up":
        cmd_catch_up()
    elif args.command == "daemon":
        if os.getenv("MINT_DAEMON", "").lower() not in ("1", "true", "yes"):
            log.warning(
                "Daemon mode requires MINT_DAEMON=1. "
                "Default operation is scan-once for intermittent PC use."
            )
        cmd_daemon()
    elif args.command == "daily-summary":
        cmd_daily_summary()
    elif args.command == "outcomes":
        cmd_outcomes()
    elif args.command == "backtest":
        markets = args.markets or ["KOSPI", "KOSDAQ"]
        cmd_backtest([m.upper() for m in markets], args.days, args.max_hold_days)
    elif args.command == "train":
        markets = args.markets or ["KOSPI", "KOSDAQ"]
        # 학습은 기본 365일이 backtest 기본 180보다 길어야 의미 — 사용자가 명시 안 하면 365.
        train_days = args.days if args.days != 180 else 365
        cmd_train([m.upper() for m in markets], train_days, args.max_hold_days,
                  args.watchlist_size)


if __name__ == "__main__":
    main()
