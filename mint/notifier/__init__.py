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


def _format_price(value: float, market: str) -> str:
    """시장별 통화 포맷. KR=원(정수), NASDAQ=$(소수 2자리)."""
    if market == "NASDAQ":
        return f"${value:,.2f}"
    return f"{value:,.0f}원"


def _freshness_line(ticker: str, market: str, ref_price: float) -> Optional[str]:
    """KIS 현재가 fetch → drift 마커 줄 반환. 없으면 None (KIS 미설정/실패).

    - 위로 stale (현재가 >> 기준가): ⚠️ 엔트리 늦음
    - 아래로 stale (현재가 << 기준가): 💡 더 좋은 진입 기회
    - drift 작으면 ✓ 신선
    """
    if market not in ("KOSPI", "KOSDAQ"):
        return None
    if not ref_price or ref_price <= 0:
        return None
    try:
        from config.settings import config
        from data import kis_client
        kp = kis_client.get_current_price(ticker)
    except Exception:
        return None
    if not kp:
        return None

    drift = (kp.price - ref_price) / ref_price
    drift_pct = drift * 100
    threshold = config.ops.ref_price_stale_pct
    if drift > threshold:
        return f"⚠️ 현재 {kp.price:,.0f}원 ({drift_pct:+.2f}% · 이미 상승, 엔트리 늦음)"
    if drift < -threshold:
        return f"💡 현재 {kp.price:,.0f}원 ({drift_pct:+.2f}% · 기준보다 낮음, 더 좋은 진입)"
    return f"✓ 현재 {kp.price:,.0f}원 ({drift_pct:+.2f}% · 신선)"


def _format_buy_signal(sig: dict) -> str:
    """단일 매수 시그널 → 200자 이내 메시지. 표기는 의도적으로 정직하게.

    - 'expected_return' = 휴리스틱 모멘텀 점수 (rule_scanner._estimate_expected_return_1d).
      따라서 '예상 수익' 이라고 단정하지 않고 '모멘텀' 으로 표기.
    - 'confidence' = ML 켰을 때 P(win), 아니면 룰 score (0~1). 라벨 분기.
    - target/stop은 가격 + % 둘 다.
    - KIS 현재가 있으면 신선도 마커 추가 (⚠️/💡/✓).
    """
    from config.settings import config

    name = sig.get("name") or sig["ticker"]
    market = sig.get("market", "")
    ref = sig.get("ref_price") or 0
    momentum_pct = (sig.get("expected_return") or 0) * 100
    confidence_pct = (sig.get("confidence") or 0) * 100
    target = sig.get("target_price") or 0
    stop = sig.get("stop_price") or 0

    # 2026-05-22 Dynamic exit — 시그널별 target/stop/hold가 있으면 그걸 사용
    if sig.get("max_hold_hours") and ref > 0 and target > 0 and stop > 0:
        target_ret = (target / ref - 1) * 100
        stop_ret = (stop / ref - 1) * 100
        hold_h = float(sig["max_hold_hours"])
    else:
        target_ret = config.signal.target_return * 100
        stop_ret = config.signal.stop_loss * 100
        hold_h = config.signal.max_hold_hours

    # Regime 표시
    regime_label = sig.get("regime_label")
    regime_line = ""
    if regime_label:
        try:
            from engine.market_regime import REGIME_EMOJI, REGIME_KO
            emoji_r = REGIME_EMOJI.get(regime_label, "")
            ko_r = REGIME_KO.get(regime_label, regime_label)
            regime_line = f"시장 {emoji_r} {market} {ko_r}"
        except Exception:
            pass

    conf_label = "ML 확률" if config.signal.use_ml_confidence else "룰 점수"
    valid_min = config.ops.signal_valid_minutes
    fresh = _freshness_line(sig["ticker"], market, ref)
    minute_marker = "🔥 5분봉 패턴 동시 통과" if config.signal.use_minute_rule else ""

    # 2026-06-02: C1 수급 한 줄 (KR only). 외국인/기관 5d 순매매 + 외국인 보유 비율.
    flow_line = ""
    if market in ("KOSPI", "KOSDAQ") and sig.get("foreign_net_5d") is not None:
        f_net = sig.get("foreign_net_5d") or 0
        i_net = sig.get("inst_net_5d") or 0
        f_pct = sig.get("foreign_pct")
        f_emoji = "🟩" if f_net > 0 else ("🟥" if f_net < 0 else "⬜")
        i_emoji = "🟩" if i_net > 0 else ("🟥" if i_net < 0 else "⬜")
        pct_str = f" · 외국인 {f_pct:.1f}%" if f_pct is not None else ""
        flow_line = (
            f"{f_emoji} 외국인 {f_net/10000:+,.0f}만주 · "
            f"{i_emoji} 기관 {i_net/10000:+,.0f}만주{pct_str} (5d)"
        )

    # 2026-06-02: C2 — D+1 강한 상승(+15%) leading indicator P (KR only).
    # 학습 결과 (val n=37k, base rate 3.78%):
    #   P=0.30 → precision 60.0% / lift 15.9× / 일평균 0.4건 (rare-strong)
    #   P=0.20 → precision 28.6% / lift  7.6× / 일평균 2.2건 (sweet spot)
    #   P=0.10 → precision 13.7% / lift  3.6× / 일평균 35건  (loose)
    limitup_line = ""
    if sig.get("limitup_prob") is not None:
        lp = float(sig["limitup_prob"])
        if lp >= 0.30:
            tag = "🚀🚀🚀 매우 강함 (precision 60%)"
        elif lp >= 0.20:
            tag = "🚀🚀 강함 (precision 29%)"
        elif lp >= 0.10:
            tag = "🚀 양호 (precision 14%)"
        else:
            tag = ""
        if lp >= 0.05:  # 5% 미만은 표시 의미 약함
            limitup_line = f"⚡ D+1 강한상승 P={lp*100:.1f}% {tag}".strip()

    # 순서: 핵심(잘리면 안 됨) → 부가(잘려도 OK)
    # truncate가 라인 단위라 아래쪽부터 잘림
    lines = [
        f"🟢 [Mint 매수] {_market_emoji(market)} {name} ({sig['ticker']})",
        f"기준가 {_format_price(ref, market)}",
        f"🎯 {_format_price(target, market)} ({target_ret:+.1f}%) / 손절 {_format_price(stop, market)} ({stop_ret:+.1f}%)",
        f"⏱ {hold_h:.0f}h내 권고 · 유효 {valid_min}분",
        regime_line,
        limitup_line,
        flow_line,
        fresh or "",
        minute_marker,
        f"모멘텀 {momentum_pct:+.1f}% · {conf_label} {confidence_pct:.0f}%",
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
        f"현재 {_format_price(cur, market)} / 매수 {_format_price(buy, market)} ({pnl:+.2f}%) {color}",
        f"사유: {reason_kr} · 보유 {hold_h:.1f}h",
        d.get("note") or "",
        "👉 실제 매도는 카카오페이 앱에서 실행",
    ]
    return "\n".join(line for line in lines if line)


_NOTIFIER_STATE_KEY = "notifier_state"


def _load_state() -> dict:
    """1순위 DB(app_state['notifier_state']), 2순위 파일 — DB로 자동 마이그레이션."""
    try:
        from portfolio.db import get_app_state
        raw = get_app_state(_NOTIFIER_STATE_KEY)
        if raw:
            return json.loads(raw)
    except Exception as e:
        log.debug("notifier state DB load failed: %s", e)

    if not os.path.exists(_HEARTBEAT_STATE):
        return {}
    try:
        with open(_HEARTBEAT_STATE, "r", encoding="utf-8") as f:
            state = json.load(f)
        # 1회 마이그레이션
        try:
            from portfolio.db import set_app_state
            set_app_state(_NOTIFIER_STATE_KEY, json.dumps(state, ensure_ascii=False))
            log.info("Notifier state migrated from file to DB")
        except Exception:
            pass
        return state
    except Exception:
        return {}


def _save_state(state: dict) -> None:
    """DB 우선. 로컬 sqlite 운영일 때만 파일 동시 보존."""
    try:
        from portfolio.db import set_app_state
        set_app_state(_NOTIFIER_STATE_KEY, json.dumps(state, ensure_ascii=False))
    except Exception as e:
        log.debug("notifier state DB save failed: %s", e)

    try:
        from portfolio.db import DATABASE_URL as _DB_URL
        if not _DB_URL.startswith("sqlite"):
            return
    except Exception:
        pass
    try:
        os.makedirs(os.path.dirname(_HEARTBEAT_STATE), exist_ok=True)
        with open(_HEARTBEAT_STATE, "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False, indent=2)
    except Exception as e:
        log.debug("notifier state file save failed: %s", e)


_STATE_LOCK_PATH = _HEARTBEAT_STATE + ".lock"
_STATE_LOCK_TIMEOUT = 5.0


def _state_lock():
    """간단한 cross-process file lock (Windows/Linux 호환).
    여러 scan이 같은 시각에 끝날 때 _save_state race 방지.
    """
    import time
    deadline = time.time() + _STATE_LOCK_TIMEOUT
    while time.time() < deadline:
        try:
            fd = os.open(_STATE_LOCK_PATH, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.close(fd)
            return True
        except FileExistsError:
            time.sleep(0.05)
    return False


def _state_unlock():
    try:
        os.remove(_STATE_LOCK_PATH)
    except FileNotFoundError:
        pass


def accumulate_scan_stats(stats: dict) -> None:
    """rule_scanner가 매 scan 끝날 때 호출. 오늘 누적 funnel에 더함.
    여러 scan 동시 종료 시 file lock으로 race 방지.
    """
    locked = _state_lock()
    try:
        state = _load_state()
        # KST 기준 today — GHA UTC에서도 한국 거래일과 정합 (R1, 2026-05-23)
        from config.tz import today_kst
        today = today_kst()
        key = f"scan_stats_{today}"
        cur = state.get(key, {})
        for k, v in stats.items():
            cur[k] = cur.get(k, 0) + v
        cur["scans"] = cur.get("scans", 0) + 1
        state[key] = cur
        _save_state(state)
    finally:
        if locked:
            _state_unlock()


def get_today_scan_stats() -> dict:
    state = _load_state()
    from config.tz import today_kst
    today = today_kst()
    return state.get(f"scan_stats_{today}", {})


def maybe_send_midday_ping(markets: List[str]) -> bool:
    """점심시간(11:50~13:00) 첫 scan에서 1회. 오전 시그널 수 + 시장 + funnel 핵심.
    사용자 외출 중에도 '시스템 살아있고 약세장이라 시그널 적다' 같은 가시성 제공.
    """
    if not _enabled():
        return False
    # KST 시각으로 점심시간 판정 (R1) — GHA UTC면 매번 새벽이라 11~13시 못 잡음
    from config.tz import now_kst
    now = now_kst()
    if not (11 <= now.hour <= 13):
        return False
    if now.hour == 13 and now.minute > 0:
        return False
    today = now.strftime("%Y-%m-%d")
    state = _load_state()
    if state.get("last_midday_date") == today:
        return False

    from notifier import kakao
    try:
        from data.market_index import format_summary_line
        market_line = format_summary_line()
    except Exception:
        market_line = None

    # 오늘 오전까지의 funnel
    fs = state.get(f"scan_stats_{today}", {})
    signals = fs.get("signals_created", 0)
    scans = fs.get("scans", 0)

    lines = [
        f"🕛 Mint 미드데이 — {now.strftime('%H:%M')}",
    ]
    if market_line:
        lines.append(market_line)
    # 시장 regime (KOSPI/KOSDAQ 각각)
    try:
        from engine.market_regime import both_regimes_line
        rl = both_regimes_line()
        if rl and "조회 실패" not in rl:
            lines.append(rl)
    except Exception:
        pass
    lines.append(f"오전 스캔 {scans}회 · 시그널 {signals}건")
    if signals == 0 and scans > 0:
        # 어디서 막혔는지 한 줄
        if fs.get("passed_momentum", 0) == 0:
            lines.append("→ 거의 모든 종목이 모멘텀 부족 (약세장)")
        elif fs.get("passed_ml", 0) == 0 and fs.get("passed_volume", 0) > 0:
            lines.append("→ 룰은 통과하나 ML 점수 미달")
        elif fs.get("passed_minute", 0) == 0 and fs.get("passed_ml", 0) > 0:
            lines.append("→ ML 통과했으나 분봉 패턴 미충족")
    lines.append("시스템 정상 동작 중")

    ok = kakao.send_text("\n".join(lines))
    if ok:
        state["last_midday_date"] = today
        _save_state(state)
        log.info("Midday ping sent for %s", today)
    return ok


def maybe_send_heartbeat(markets: List[str]) -> bool:
    """오늘 처음 스캔이면 하트비트 1통. 이미 보냈으면 skip."""
    if not _enabled():
        return False
    # KST 기준 today (R1)
    from config.tz import today_kst, now_kst
    today = today_kst()
    state = _load_state()
    if state.get("last_heartbeat_date") == today:
        return False

    from notifier import kakao
    try:
        from data.market_index import format_summary_line
        market_line = format_summary_line()
    except Exception:
        market_line = None

    now = now_kst().strftime("%H:%M")
    lines = [
        f"🟢 Mint 시작 — {today} {now}",
        f"대상: {', '.join(markets)}",
    ]
    if market_line:
        lines.append(market_line)
    # 시장 regime
    try:
        from engine.market_regime import both_regimes_line
        rl = both_regimes_line()
        if rl and "조회 실패" not in rl:
            lines.append(rl)
    except Exception:
        pass
    lines.append("새 시그널이 잡히면 이 채팅으로 알려드립니다.")
    ok = kakao.send_text("\n".join(lines))
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
    # KST 기준 today (R1) — GHA UTC가 KST 자정 직후일 때 같은 KST 날짜 정합
    from config.tz import today_kst
    today = today_kst()
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
    # 시장 regime (KOSPI/KOSDAQ + NASDAQ — 야간 매매 의향 있는 사용자 위해)
    try:
        from engine.market_regime import regimes_line
        rl = regimes_line(["KOSPI", "KOSDAQ", "NASDAQ"])
        if rl and "조회 실패" not in rl:
            lines.append(rl)
    except Exception:
        pass
    if extra_lines:
        lines.extend(extra_lines)
    ok = kakao.send_text("\n".join(lines))
    if ok:
        state["last_summary_date"] = today
        _save_state(state)
        log.info("Daily summary sent for %s", today)
    return ok


_EXPIRY_LABEL = {
    "TIME": "❌ 시그널 만료 — 유효시간 지남",
    "TARGET_HIT": "✅ 목표가 도달 — 매수 적기 종료",
    "STOP_HIT": "🔴 손절가 터치 — 매수 추천 종료",
}


def _format_expiry(sig: dict) -> str:
    """만료 시그널 한 통."""
    reason = sig.get("expiry_reason") or "TIME"
    label = _EXPIRY_LABEL.get(reason, f"❌ 만료 ({reason})")
    name = sig.get("name") or sig.get("ticker", "")
    ticker = sig.get("ticker", "")
    market = sig.get("market", "")
    ref = sig.get("ref_price") or 0
    cur = sig.get("expiry_price") or 0
    lines = [
        f"{label}",
        f"{_market_emoji(market)} {name} ({ticker})",
        f"기준가 {_format_price(ref, market)}" + (
            f" → 현재 {_format_price(cur, market)}" if cur else ""
        ),
        "👉 이미 매수했다면 별도 매도 권고를 기다리세요.",
        "    아직 안 샀다면 이 시그널은 무시하세요.",
    ]
    return "\n".join(line for line in lines if line)


def notify_expired_signals(signals: Iterable[dict]) -> int:
    """만료된 시그널 목록 → 카톡 알림. 발송 수 반환."""
    items = [s for s in signals if s]
    if not items:
        return 0
    if not _enabled():
        log.info("Expiry notify skipped (%d items) — notifier disabled", len(items))
        return 0

    from notifier import kakao
    sent = 0
    for s in items[:MAX_INDIVIDUAL_SENDS]:
        if kakao.send_text(_format_expiry(s)):
            sent += 1
    if len(items) > MAX_INDIVIDUAL_SENDS:
        kakao.send_text(
            f"❌ 만료 시그널 {len(items)}건 중 상위 {MAX_INDIVIDUAL_SENDS}건만 표시"
        )
    log.info("Kakao expiry notify sent=%d (of %d)", sent, len(items))
    return sent


def notify_buy_signals(signal_ids: Iterable[int]) -> int:
    """시그널 ID 목록 → 카카오 알림. 발송된 메시지 수 반환.

    발송 성공한 시그널은 signals.notified=1로 마킹 (mark_buy_notified).
    cancel/실패 시 마킹 안 하므로 다음 scan에서 unnotified_buy_signals catch-up.
    """
    ids = [i for i in signal_ids if i]
    if not ids:
        return 0
    if not _enabled():
        log.info("Notify skipped (%d new signals) — notifier disabled or unconfigured",
                 len(ids))
        return 0

    from notifier import kakao  # 지연 import
    from portfolio.db import mark_buy_notified

    signals = [get_signal(i) for i in ids]
    signals = [s for s in signals if s]
    if not signals:
        return 0

    sent_ids: List[int] = []
    sent = 0

    # 다수면 요약부터
    if len(signals) > MAX_INDIVIDUAL_SENDS:
        names = ", ".join((s.get("name") or s["ticker"]) for s in signals[:5])
        summary = (
            f"🟢 [Mint] 매수 시그널 {len(signals)}건\n"
            f"{names}{' 외' if len(signals) > 5 else ''}\n"
            f"상위 {MAX_INDIVIDUAL_SENDS}건만 상세 발송합니다."
        )
        if kakao.send_text(summary):
            sent += 1
            # 요약 발송 성공 = 전체 시그널 mark (재발송 폭주 방지).
            # 상위 MAX_INDIVIDUAL_SENDS 외 종목은 종목명만 전달돼도 사용자에게 알린 것으로 봄.
            sent_ids.extend(int(s["id"]) for s in signals if s.get("id"))
        signals = signals[:MAX_INDIVIDUAL_SENDS]

    for s in signals:
        if kakao.send_text(_format_buy_signal(s)):
            sent += 1
            sid = s.get("id")
            if sid is not None and int(sid) not in sent_ids:
                sent_ids.append(int(sid))

    if sent_ids:
        try:
            mark_buy_notified(sent_ids)
        except Exception as e:
            log.warning("mark_buy_notified failure: %s", e)

    log.info("Kakao buy notify sent=%d (of %d signals, marked=%d)",
             sent, len(ids), len(sent_ids))
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
