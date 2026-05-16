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
from portfolio.db import init_db, migrate_db, expire_stale_signals, get_open_positions
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


def cmd_scan():
    """KR 워치리스트 룰 스캔 → signals DB. MINT_US_SCAN=true면 NASDAQ도 포함."""
    init_db()
    migrate_db()
    markets = ["KOSPI", "KOSDAQ"]
    if config.ops.enable_us_market_scan:
        markets.append("NASDAQ")
    ids = run_rule_scan(markets=markets)
    log.info("Scan finished — %s signal(s) logged (markets=%s)", len(ids), markets)
    return ids


def cmd_scan_us():
    """US-only scan (daemon에서 야간 호출용)."""
    init_db()
    migrate_db()
    ids = run_rule_scan(markets=["NASDAQ"])
    log.info("US scan finished — %s signal(s) logged", len(ids))
    return ids


def cmd_catch_up():
    """PC 재실행 시: stale 시그널 만료 + 보유 포지션 매도 권고 로그."""
    init_db()
    migrate_db()
    expired = expire_stale_signals()
    log.info("Expired %s stale signal(s)", expired)

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

    log.info("Daemon scheduler started (US scan=%s)", config.ops.enable_us_market_scan)
    try:
        scheduler.start()
    except KeyboardInterrupt:
        log.info("Mint daemon stopped")


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
        choices=["scan", "catch-up", "daemon", "backtest", "train"],
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
