"""
룰 백테스트 — 3% 필터의 빈도/승률/평균 수익 측정.

사용:
  python mint/main.py backtest          # 기본: KOSPI+KOSDAQ, 180일
  python mint/main.py backtest --days 365 --markets KOSPI KOSDAQ NASDAQ

설계:
  - 워치리스트의 각 종목에 대해 60일 윈도우를 1일씩 슬라이드
  - 그 시점의 evaluate_ticker로 BUY 시그널 여부 판정
  - BUY가 발생하면 그 다음 max_hold_days 영업일 동안 OHLC를 보고:
      · high가 target_price 이상이면 → TARGET (이긴 거래)
      · low가 stop_price 이하면     → STOP (진 거래)
      · 둘 다 안 닿으면 종료가 기준 → TIME (수익률 그대로)
      · 같은 봉에서 둘 다 닿으면 보수적으로 STOP (사용자 손실 최소화 원칙)
  - 결과를 콘솔에 요약 + CSV (mint/data/backtest_<ts>.csv)
"""
from __future__ import annotations

import csv
import logging
import os
from dataclasses import dataclass
from datetime import datetime
from typing import List, Optional

import pandas as pd

from config.settings import config
from data.collector import fetch_bars
from data.universe import get_watchlist
from engine.signals.rule_scanner import evaluate_ticker

log = logging.getLogger("mint.backtest")


@dataclass
class Trade:
    ticker: str
    market: str
    entry_date: str
    entry_price: float
    target_price: float
    stop_price: float
    exit_date: str
    exit_price: float
    exit_reason: str  # TARGET | STOP | TIME
    profit_pct: float
    hold_days: int


def _watchlist(market: str, n: Optional[int] = None) -> List[str]:
    return get_watchlist(market, n=n if n is not None else config.ops.watchlist_size)


def _simulate_exit(
    bars: pd.DataFrame,
    entry_idx: int,
    target_price: float,
    stop_price: float,
    max_hold_days: int,
) -> Optional[Trade]:
    """entry_idx 다음 봉부터 시뮬레이션."""
    if entry_idx + 1 >= len(bars):
        return None

    end_idx = min(entry_idx + max_hold_days, len(bars) - 1)
    entry_bar = bars.iloc[entry_idx]
    entry_price = float(entry_bar["close"])

    for i in range(entry_idx + 1, end_idx + 1):
        bar = bars.iloc[i]
        high = float(bar["high"])
        low = float(bar["low"])
        hit_target = high >= target_price
        hit_stop = low <= stop_price

        if hit_target and hit_stop:
            # 보수적 — 손절 먼저 닿았다고 가정
            return Trade(
                ticker=str(entry_bar["ticker"]),
                market=str(entry_bar["market"]),
                entry_date=str(entry_bar["ts_local"])[:10],
                entry_price=entry_price,
                target_price=target_price,
                stop_price=stop_price,
                exit_date=str(bar["ts_local"])[:10],
                exit_price=stop_price,
                exit_reason="STOP",
                profit_pct=(stop_price / entry_price - 1) * 100,
                hold_days=i - entry_idx,
            )
        if hit_target:
            return Trade(
                ticker=str(entry_bar["ticker"]),
                market=str(entry_bar["market"]),
                entry_date=str(entry_bar["ts_local"])[:10],
                entry_price=entry_price,
                target_price=target_price,
                stop_price=stop_price,
                exit_date=str(bar["ts_local"])[:10],
                exit_price=target_price,
                exit_reason="TARGET",
                profit_pct=(target_price / entry_price - 1) * 100,
                hold_days=i - entry_idx,
            )
        if hit_stop:
            return Trade(
                ticker=str(entry_bar["ticker"]),
                market=str(entry_bar["market"]),
                entry_date=str(entry_bar["ts_local"])[:10],
                entry_price=entry_price,
                target_price=target_price,
                stop_price=stop_price,
                exit_date=str(bar["ts_local"])[:10],
                exit_price=stop_price,
                exit_reason="STOP",
                profit_pct=(stop_price / entry_price - 1) * 100,
                hold_days=i - entry_idx,
            )

    # 시간 청산 — 마지막 종가로
    last = bars.iloc[end_idx]
    last_close = float(last["close"])
    return Trade(
        ticker=str(entry_bar["ticker"]),
        market=str(entry_bar["market"]),
        entry_date=str(entry_bar["ts_local"])[:10],
        entry_price=entry_price,
        target_price=target_price,
        stop_price=stop_price,
        exit_date=str(last["ts_local"])[:10],
        exit_price=last_close,
        exit_reason="TIME",
        profit_pct=(last_close / entry_price - 1) * 100,
        hold_days=end_idx - entry_idx,
    )


def backtest_ticker(
    ticker: str,
    market: str,
    days: int = 180,
    window: int = 60,
    max_hold_days: int = 1,
    cooldown_days: int = 3,
) -> List[Trade]:
    """단일 종목 백테스트 — 룰 스캐너와 동일한 evaluate_ticker 사용."""
    bars = fetch_bars(ticker, market, days=days + window)
    if bars.empty or len(bars) < window + 2:
        return []

    trades: List[Trade] = []
    i = window
    while i < len(bars):
        sub = bars.iloc[i - window : i + 1].reset_index(drop=True)
        candidate = evaluate_ticker(ticker, market, sub)
        if candidate:
            trade = _simulate_exit(
                bars=bars,
                entry_idx=i,
                target_price=candidate["target_price"],
                stop_price=candidate["stop_price"],
                max_hold_days=max_hold_days,
            )
            if trade:
                trades.append(trade)
                i += trade.hold_days + cooldown_days  # 동일 종목 중복 방지
                continue
        i += 1

    return trades


def run_backtest(
    markets: Optional[List[str]] = None,
    days: int = 180,
    max_hold_days: int = 1,
    universe_size: Optional[int] = None,
) -> List[Trade]:
    markets = markets or ["KOSPI", "KOSDAQ"]
    all_trades: List[Trade] = []
    for m in markets:
        tickers = _watchlist(m, n=universe_size)
        log.info("Backtest %s — %d tickers", m, len(tickers))
        for t in tickers:
            try:
                ts = backtest_ticker(t, m, days=days, max_hold_days=max_hold_days)
            except Exception as e:
                log.debug("backtest_ticker(%s) failed: %s", t, e)
                ts = []
            if ts:
                log.info("  %s — %d trades", t, len(ts))
            all_trades.extend(ts)
    return all_trades


def summarize(trades: List[Trade]) -> dict:
    if not trades:
        return {
            "total": 0,
            "wins": 0,
            "win_rate": 0.0,
            "avg_return_pct": 0.0,
            "avg_hold_days": 0.0,
            "target_hits": 0,
            "stop_hits": 0,
            "time_exits": 0,
        }
    wins = sum(1 for t in trades if t.profit_pct > 0)
    avg = sum(t.profit_pct for t in trades) / len(trades)
    avg_hold = sum(t.hold_days for t in trades) / len(trades)
    return {
        "total": len(trades),
        "wins": wins,
        "win_rate": wins / len(trades) * 100,
        "avg_return_pct": avg,
        "avg_hold_days": avg_hold,
        "target_hits": sum(1 for t in trades if t.exit_reason == "TARGET"),
        "stop_hits": sum(1 for t in trades if t.exit_reason == "STOP"),
        "time_exits": sum(1 for t in trades if t.exit_reason == "TIME"),
    }


def save_csv(trades: List[Trade], out_dir: str = "mint/data") -> str:
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, f"backtest_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv")
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(
            ["ticker", "market", "entry_date", "entry_price", "exit_date",
             "exit_price", "exit_reason", "profit_pct", "hold_days",
             "target_price", "stop_price"]
        )
        for t in trades:
            w.writerow(
                [t.ticker, t.market, t.entry_date, f"{t.entry_price:.4f}",
                 t.exit_date, f"{t.exit_price:.4f}", t.exit_reason,
                 f"{t.profit_pct:.3f}", t.hold_days,
                 f"{t.target_price:.4f}", f"{t.stop_price:.4f}"]
            )
    return path


def print_summary(summary: dict, markets: List[str], days: int) -> None:
    print()
    print("─" * 60)
    print(f"Backtest — markets={markets} days={days}")
    print(f"  target={config.signal.target_return*100:+.1f}% · "
          f"stop={config.signal.stop_loss*100:+.1f}% · "
          f"filter≥{config.signal.min_expected_return_1d*100:.1f}%")
    print("─" * 60)
    print(f"  총 시그널/거래 : {summary['total']}")
    print(f"  승률           : {summary['win_rate']:.1f}% ({summary['wins']}/{summary['total']})")
    print(f"  평균 수익      : {summary['avg_return_pct']:+.2f}%")
    print(f"  평균 보유      : {summary['avg_hold_days']:.1f}일")
    print(f"  목표가 도달    : {summary['target_hits']}")
    print(f"  손절 도달      : {summary['stop_hits']}")
    print(f"  시간 청산      : {summary['time_exits']}")
    print("─" * 60)
