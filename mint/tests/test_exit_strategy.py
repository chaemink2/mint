"""Exit strategy unit tests (no network — current_price 주입)."""
from datetime import timedelta
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from config.tz import now_kst
from engine.signals.exit_strategy import evaluate_position


def _pos(buy_price=10000, target=10350, stop=9800, bought_minutes_ago=60):
    # buy_time은 KST tz-aware ISO (2026-05-27 KST 통일 후 신규 저장 형식)
    return {
        "id": 1,
        "ticker": "005930",
        "market": "KOSPI",
        "name": "삼성전자",
        "buy_price": buy_price,
        "target_price": target,
        "stop_loss": stop,
        "buy_time": (now_kst() - timedelta(minutes=bought_minutes_ago)).isoformat(),
        "quantity": 10,
        "remaining_qty": 10,
    }


def test_target_hit_returns_sell_now():
    adv = evaluate_position(_pos(), current_price=10400)
    assert adv.action == "SELL_NOW"
    assert adv.reason == "TARGET"
    assert adv.profit_pct > 3.0


def test_stop_hit_is_advisory_consider():
    adv = evaluate_position(_pos(), current_price=9700)
    # stop_loss_is_advisory=True 기본 → CONSIDER_SELL
    assert adv.action == "CONSIDER_SELL"
    assert adv.reason == "STOP_LOSS"


def test_hold_when_in_between():
    adv = evaluate_position(_pos(), current_price=10100)
    assert adv.action == "HOLD"
    assert adv.reason == "HOLD"


def test_time_exit_after_max_hold():
    pos = _pos(bought_minutes_ago=60 * 30)  # 30시간
    adv = evaluate_position(pos, current_price=10100)
    assert adv.action == "CONSIDER_SELL"
    assert adv.reason == "TIME"


if __name__ == "__main__":
    test_target_hit_returns_sell_now()
    test_stop_hit_is_advisory_consider()
    test_hold_when_in_between()
    test_time_exit_after_max_hold()
    print("all exit_strategy tests pass")
