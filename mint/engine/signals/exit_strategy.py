"""
Exit strategy — 보유 포지션의 매도 권고 산출.

자동 주문은 하지 않는다 (사용자는 카카오페이에서 수동 매매).
"권고"만 제공: TARGET / STOP_LOSS / TIME / HOLD.

stop_loss는 advisory (config.ops.stop_loss_is_advisory).
실제 손절 주문은 카카오페이 앱에서 지정가/예약매도로 사용자가 설정.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Iterable, List, Optional

from config.settings import config
from data import kis_client
from data.collector import fetch_bars


@dataclass
class ExitAdvice:
    position_id: int
    ticker: str
    name: Optional[str]
    market: str
    buy_price: float
    current_price: float
    profit_pct: float
    hold_hours: float
    action: str            # SELL_NOW | CONSIDER_SELL | HOLD
    reason: str            # TARGET | STOP_LOSS | TIME | REVERSE | HOLD
    note: str = ""

    def to_dict(self) -> dict:
        return {
            "position_id": self.position_id,
            "ticker": self.ticker,
            "name": self.name,
            "market": self.market,
            "buy_price": self.buy_price,
            "current_price": self.current_price,
            "profit_pct": self.profit_pct,
            "hold_hours": self.hold_hours,
            "action": self.action,
            "reason": self.reason,
            "note": self.note,
        }


def _latest_price(ticker: str, market: str) -> Optional[float]:
    """KIS 현재가 우선 → 일봉 close 폴백."""
    if market in ("KOSPI", "KOSDAQ"):
        kis_px = kis_client.get_current_price(ticker)
        if kis_px:
            return kis_px.price
    try:
        bars = fetch_bars(ticker, market, days=5)
        if bars.empty:
            return None
        return float(bars["close"].iloc[-1])
    except Exception:
        return None


def evaluate_position(position: dict, current_price: Optional[float] = None) -> ExitAdvice:
    """
    단일 포지션의 매도 권고를 산출.
    position: portfolio.db.get_open_positions() row.
    """
    ticker = position["ticker"]
    market = position["market"]
    buy_price = float(position["buy_price"])
    target = float(position.get("target_price") or 0) or buy_price * (1 + config.signal.target_return)
    stop = float(position.get("stop_loss") or 0) or buy_price * (1 + config.signal.stop_loss)
    buy_time = datetime.fromisoformat(position["buy_time"])
    hold_hours = (datetime.now() - buy_time).total_seconds() / 3600

    price = current_price if current_price is not None else _latest_price(ticker, market)
    if price is None or price <= 0:
        price = buy_price
        note = "현재가 미확보 — 매수가로 대체"
    else:
        note = ""

    profit_pct = (price / buy_price - 1) * 100

    if price >= target:
        action, reason = "SELL_NOW", "TARGET"
    elif price <= stop:
        # 손절은 advisory: 강제 매도가 아닌 "고려" 단계로 표시
        action = "CONSIDER_SELL" if config.ops.stop_loss_is_advisory else "SELL_NOW"
        reason = "STOP_LOSS"
    elif hold_hours >= config.signal.max_hold_hours:
        action, reason = "CONSIDER_SELL", "TIME"
    else:
        action, reason = "HOLD", "HOLD"

    return ExitAdvice(
        position_id=position["id"],
        ticker=ticker,
        name=position.get("name"),
        market=market,
        buy_price=buy_price,
        current_price=price,
        profit_pct=profit_pct,
        hold_hours=hold_hours,
        action=action,
        reason=reason,
        note=note,
    )


def evaluate_positions(positions: Iterable[dict]) -> List[ExitAdvice]:
    return [evaluate_position(p) for p in positions]
