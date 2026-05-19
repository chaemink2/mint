"""
Mint 알림 디스패처.

사용:
  from notifier import notify_buy_signals, notify_exit_advices

  ids = run_rule_scan(...)
  notify_buy_signals(ids)

  advices = evaluate_positions(positions)
  notify_exit_advices(advices)

채널:
  - 현재는 카카오톡 "나에게 보내기" (notifier.kakao)
  - 키 없거나 토큰 미설정이면 자동 비활성 (no-op)

환경변수:
  MINT_NOTIFY_ENABLED=true|false   (기본 true; false면 모든 알림 skip)

메시지 정책:
  - 매수 시그널: 종목당 1메시지. 다수 시그널이면 요약 1통 + 개별 발송 (최대 N건).
  - 매도 권고: action != HOLD 만 발송. SELL_NOW 우선.
"""
from __future__ import annotations

import json
import logging
import os
from datetime import datetime
from typing import Iterable, List, Optional

from portfolio.db import get_signal

log = logging.getLogger("mint.notifier")

MAX_INDIVIDUAL_SENDS = int(os.getenv("MINT_NOTIFY_MAX_PER_RUN", "5"))
_HEARTBEAT_STATE = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "data",
    ".notifier_state.json",
)


def _enabled() -> bool:
    if os.getenv("MINT_NOTIFY_ENABLED", "true").lower() not in ("1", "true", "yes"):
        return False
    try:
        from notifier import kakao  # 지연 import
    except Exception:
        return False
    return kakao.is_configured()


def _market_emoji(market: str) -> str:
    return {"KOSPI": "🇰🇷", "KOSDAQ": "🇰🇷", "NASDAQ": "🇺🇸"}.get(market, "📈")


def _format_buy_signal(sig: dict) -> str:
    """단일 매수 시그널 → 200자 이내 메시지. 표기는 의도적으로 정직하게.

    - 'expected_return' = 휴리스틱 모멘텀 점수 (rule_scanner._estimate_expected_return_1d).
      따라서 '예상 수익' 이라고 단정하지 않고 '모멘텀' 으로 표기.
    - 'confidence' = ML 켰을 때 P(win), 아니면 룰 score (0~1). 라벨 분기.
    - target/stop은 가격 + % 둘 다.
    """
    from config.settings import config

    name = sig.get("name") or sig["ticker"]
    market = sig.get("market", "")
    ref = sig.get("ref_price") or 0
    momentum_pct = (sig.get("expected_return") or 0) * 100
    confidence_pct = (sig.get("confidence") or 0) * 100
    target = sig.get("target_price") or 0
    stop = sig.get("stop_price") or 0

    target_ret = config.signal.target_return * 100
    stop_ret = config.signal.stop_loss * 100
    hold_h = config.signal.max_hold_hours

    conf_label = "ML 확률" if config.signal.use_ml_confidence else "룰 점수"

    valid_min = config.ops.signal_valid_minutes

    lines = [
        f"🟢 [Mint 매수] {_market_emoji(market)} {name} ({sig['ticker']})",
        f"기준가 {ref:,.0f}원 · {hold_h}h내 +{target_ret:.1f}%/{stop_ret:+.1f}% 권고",
        f"모멘텀 {momentum_pct:+.1f}% · {conf_label} {confidence_pct:.0f}%",
        f"목표 {target:,.0f} / 손절 {stop:,.0f}",
        f"시그널 유효 {valid_min}분",
    ]
    return "\n".join(line for line in lines if line)


_ACTION_KR = {
    "SELL_NOW": "지금 매도",
    "CONSIDER_SELL": "매도 검토",
    "HOLD": "보유",
}

_REASON_KR = {
    "TARGET": "목표가 도달",
    "STOP_LOSS": "손절가 터치",
    "TIME": "시간청산(24h)",
    "REVERSE": "역방향 시그널",
    "HOLD": "조건 미충족",
}


def _format_exit_advice(advice) -> str:
    """단일 매도 권고 → 메시지. advice는 ExitAdvice 인스턴스 or dict."""
    if hasattr(advice, "to_dict"):
        d = advice.to_dict()
    else:
        d = dict(advice)

    action = d.get("action", "HOLD")
    reason = d.get("reason", "")
    name = d.get("name") or d.get("ticker", "")
    ticker = d.get("ticker", "")
    cur = d.get("current_price") or 0
    buy = d.get("buy_price") or 0
    pnl = d.get("profit_pct") or 0
    hold_h = d.get("hold_hours") or 0
    market = d.get("market", "")

    emoji = "🚨" if action == "SELL_NOW" else "⚠️"
    color = "🟢" if pnl >= 0 else "🔴"
    action_kr = _ACTION_KR.get(action, action)
    reason_kr = _REASON_KR.get(reason, reason)
    lines = [
        f"{emoji} [Mint {action_kr}] {_market_emoji(market)} {name} ({ticker})",
        f"현재 {cur:,.0f} / 매수 {buy:,.0f} ({pnl:+.2f}%) {color}",
        f"사유: {reason_kr} · 보유 {hold_h:.1f}h",
        d.get("note") or "",
        "👉 실제 매도는 카카오페이 앱에서 실행",
    ]
    return "\n".join(line for line in lines if line)


def _load_state() -> dict:
    if not os.path.exists(_HEARTBEAT_STATE):
        return {}
    try:
        with open(_HEARTBEAT_STATE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _save_state(state: dict) -> None:
    try:
        os.makedirs(os.path.dirname(_HEARTBEAT_STATE), exist_ok=True)
        with open(_HEARTBEAT_STATE, "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False, indent=2)
    except Exception as e:
        log.debug("notifier state save failed: %s", e)


def maybe_send_heartbeat(markets: List[str]) -> bool:
    """오늘 처음 스캔이면 하트비트 1통. 이미 보냈으면 skip."""
    if not _enabled():
        return False
    today = datetime.now().strftime("%Y-%m-%d")
    state = _load_state()
    if state.get("last_heartbeat_date") == today:
        return False

    from notifier import kakao
    now = datetime.now().strftime("%H:%M")
    msg = (
        f"🟢 Mint 시작 — {today} {now}\n"
        f"오늘의 자동 스캔 가동 (대상: {', '.join(markets)})\n"
        f"새 시그널이 잡히면 이 채팅으로 알려드립니다."
    )
    ok = kakao.send_text(msg)
    if ok:
        state["last_heartbeat_date"] = today
        _save_state(state)
        log.info("Heartbeat sent for %s", today)
    return ok


def send_daily_summary(
    buy_count: int,
    open_positions: int,
    exit_actions: int,
    extra_lines: Optional[List[str]] = None,
) -> bool:
    """장 마감 후 1통. 매도 권고가 있어도 보냄(요약 성격)."""
    if not _enabled():
        return False
    today = datetime.now().strftime("%Y-%m-%d")
    state = _load_state()
    if state.get("last_summary_date") == today:
        log.info("Daily summary already sent for %s — skipping", today)
        return False

    from notifier import kakao
    lines = [
        f"📊 Mint 일일 요약 — {today}",
        f"오늘 매수 시그널: {buy_count}건",
        f"보유 포지션: {open_positions}건",
        f"매도 권고(HOLD 제외): {exit_actions}건",
    ]
    if extra_lines:
        lines.extend(extra_lines)
    ok = kakao.send_text("\n".join(lines))
    if ok:
        state["last_summary_date"] = today
        _save_state(state)
        log.info("Daily summary sent for %s", today)
    return ok


def notify_buy_signals(signal_ids: Iterable[int]) -> int:
    """시그널 ID 목록 → 카카오 알림. 발송된 메시지 수 반환."""
    ids = [i for i in signal_ids if i]
    if not ids:
        return 0
    if not _enabled():
        log.info("Notify skipped (%d new signals) — notifier disabled or unconfigured",
                 len(ids))
        return 0

    from notifier import kakao  # 지연 import

    signals = [get_signal(i) for i in ids]
    signals = [s for s in signals if s]
    if not signals:
        return 0

    # 다수면 요약부터
    sent = 0
    if len(signals) > MAX_INDIVIDUAL_SENDS:
        names = ", ".join((s.get("name") or s["ticker"]) for s in signals[:5])
        summary = (
            f"🟢 [Mint] 매수 시그널 {len(signals)}건\n"
            f"{names}{' 외' if len(signals) > 5 else ''}\n"
            f"상위 {MAX_INDIVIDUAL_SENDS}건만 상세 발송합니다."
        )
        if kakao.send_text(summary):
            sent += 1
        signals = signals[:MAX_INDIVIDUAL_SENDS]

    for s in signals:
        if kakao.send_text(_format_buy_signal(s)):
            sent += 1
    log.info("Kakao buy notify sent=%d (of %d signals)", sent, len(ids))
    return sent


def notify_exit_advices(advices: Iterable) -> int:
    """매도 권고 목록 → 카카오 알림. HOLD는 skip. 발송 수 반환."""
    items = []
    for a in advices:
        action = getattr(a, "action", None) or (a.get("action") if isinstance(a, dict) else None)
        if action and action != "HOLD":
            items.append(a)
    if not items:
        return 0
    if not _enabled():
        log.info("Exit notify skipped (%d advices) — notifier disabled", len(items))
        return 0

    from notifier import kakao

    items.sort(key=lambda x: 0 if (getattr(x, "action", None) == "SELL_NOW"
                                   or (isinstance(x, dict) and x.get("action") == "SELL_NOW"))
               else 1)
    sent = 0
    for a in items[:MAX_INDIVIDUAL_SENDS]:
        if kakao.send_text(_format_exit_advice(a)):
            sent += 1
    if len(items) > MAX_INDIVIDUAL_SENDS:
        kakao.send_text(
            f"⚠️ 매도 권고 {len(items)}건 중 상위 {MAX_INDIVIDUAL_SENDS}건만 표시"
        )
    log.info("Kakao exit notify sent=%d (of %d advices)", sent, len(items))
    return sent
