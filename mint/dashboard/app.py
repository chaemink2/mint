"""
Mint Dashboard - Streamlit

실행 (workspace 루트에서):
  streamlit run mint/dashboard/app.py

기본 주소: http://localhost:8501
"""
import os
import sys
from datetime import datetime, timedelta

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

MINT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, MINT_ROOT)

from config.settings import config
from config.tz import now_kst
from data import kis_client
from data.collector import fetch_bars
from data.market_index import get_market_summary
from engine.signals.exit_strategy import evaluate_position
from engine.signals.rule_scanner import run_rule_scan
from portfolio import db

db.init_db()
db.migrate_db()

st.set_page_config(
    page_title="Mint",
    page_icon="🌿",
    layout="wide",
    initial_sidebar_state="auto",  # 모바일에서 자동 접힘
)

st.markdown(
    """
<style>
@import url('https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;500&family=Pretendard:wght@300;400;500;600&display=swap');
html, body, [class*="css"] { font-family: 'Pretendard', sans-serif; }

/* 모바일 친화: 컴팩트 헤더 */
h2 { margin-top: 0.5rem !important; margin-bottom: 0.5rem !important; }
.block-container { padding-top: 1.5rem; }

.signal-buy { background: rgba(35, 134, 54, 0.15); border: 1px solid rgba(35, 134, 54, 0.4); border-radius: 8px; padding: 12px 16px; margin: 6px 0; }
.signal-hold { background: rgba(120, 120, 120, 0.10); border: 1px solid rgba(150, 150, 150, 0.30); border-radius: 8px; padding: 12px 16px; margin: 6px 0; }
.tag-fresh-window { background: #1e4a2d; color: #7ee787; padding: 2px 8px; border-radius: 4px; font-size: 11px; margin-left: 6px; }
.tag-hold-window { background: #3a3a1e; color: #d4d4a1; padding: 2px 8px; border-radius: 4px; font-size: 11px; margin-left: 6px; }
.tag-kospi { background: #1e3a5f; color: #58a6ff; padding: 2px 8px; border-radius: 4px; font-size: 11px; }
.tag-kosdaq { background: #2d1e5f; color: #d2a8ff; padding: 2px 8px; border-radius: 4px; font-size: 11px; }
.tag-nasdaq { background: #3a2d1e; color: #ffb454; padding: 2px 8px; border-radius: 4px; font-size: 11px; }
.tag-stale { background: #4a1e1e; color: #ff7b72; padding: 2px 8px; border-radius: 4px; font-size: 11px; margin-left: 6px; }
.tag-fresh { background: #1e4a2d; color: #7ee787; padding: 2px 8px; border-radius: 4px; font-size: 11px; margin-left: 6px; }
.advice-sell { background: rgba(248, 81, 73, 0.18); border: 1px solid rgba(248, 81, 73, 0.5); border-radius: 6px; padding: 8px 12px; }
.advice-consider { background: rgba(240, 136, 62, 0.18); border: 1px solid rgba(240, 136, 62, 0.5); border-radius: 6px; padding: 8px 12px; }
.advice-hold { background: rgba(63, 185, 80, 0.10); border: 1px solid rgba(63, 185, 80, 0.35); border-radius: 6px; padding: 8px 12px; }
[data-testid="stSidebar"] { background: #0d1117; border-right: 1px solid #21262d; }

/* 모바일에서 컬럼 간격 */
@media (max-width: 768px) {
    .block-container { padding-left: 0.5rem; padding-right: 0.5rem; }
    h1 { font-size: 1.5rem !important; }
    h2 { font-size: 1.2rem !important; }
}
</style>
""",
    unsafe_allow_html=True,
)


# ── helpers ────────────────────────────────────────────────
def _process_expiries_dashboard():
    """대시보드용 만료 처리 — main.py cmd_scan과 동일 흐름.
    시간 만료 + 가격 도달 만료 + 미발송 만료 카톡.
    """
    try:
        db.expire_stale_signals()
        db.check_price_expiry()
        pending = db.unnotified_expired_signals()
        if pending:
            from notifier import notify_expired_signals
            notify_expired_signals(pending)
            db.mark_expiry_notified([s["id"] for s in pending])
    except Exception as e:
        st.warning(f"만료 처리 실패: {e}")


def _run_scan(include_us: bool = False):
    """대시보드 「지금 스캔」 — main.py cmd_scan과 동일 흐름.

    2026-05-27: dedup 가로채기 fix — 누가 트리거하든 KAKAO_REST_API_KEY 소유자(사용자)에게
    카톡 발송. 이전에는 _run_scan이 run_rule_scan만 호출 → 시그널이 DB에는 들어가지만
    카톡 발송 누락 → has_recent_signal(4h)이 본인 GHA scan을 차단해 가로채기 발생.
    """
    markets = ["KOSPI", "KOSDAQ"]
    if include_us:
        markets.append("NASDAQ")
    sent = 0
    with st.spinner(f"시그널 스캔 중... ({', '.join(markets)})"):
        _process_expiries_dashboard()
        ids = run_rule_scan(markets=markets)
        if ids:
            try:
                from notifier import notify_buy_signals
                sent = notify_buy_signals(ids)
            except Exception as e:
                st.warning(f"카톡 발송 실패: {e}")
    if ids:
        st.success(f"스캔 완료 — 신규 시그널 {len(ids)}건 · 카톡 발송 {sent}건")
    else:
        st.success("스캔 완료 — 신규 시그널 없음")
    st.cache_data.clear()


@st.cache_data(ttl=60)
def _market_summary_cached():
    return get_market_summary()


@st.cache_data(ttl=30)
def _outcome_trend_df(days: int = 30) -> pd.DataFrame:
    """일별 outcome 카운트 + win rate."""
    from sqlalchemy import text
    since = (now_kst() - timedelta(days=days)).isoformat()
    # SUBSTR로 일자 추출 — sqlite/postgres 모두 호환 (DATE() 함수는 입력 타입 의존, 우린 ISO 문자열).
    with db.get_conn() as conn:
        rows = conn.execute(
            text("""SELECT SUBSTR(created_at, 1, 10) AS d, outcome, COUNT(*) AS n
               FROM signals
               WHERE signal_type='BUY' AND created_at >= :since AND outcome IS NOT NULL
               GROUP BY SUBSTR(created_at, 1, 10), outcome ORDER BY d ASC"""),
            {"since": since},
        ).fetchall()
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame([dict(r._mapping) for r in rows])
    pivot = df.pivot_table(index="d", columns="outcome", values="n", fill_value=0).reset_index()
    for col in ("WIN", "LOSS", "TIME_EXIT"):
        if col not in pivot.columns:
            pivot[col] = 0
    pivot["total"] = pivot["WIN"] + pivot["LOSS"] + pivot["TIME_EXIT"]
    pivot["win_rate"] = pivot.apply(
        lambda r: (r["WIN"] / r["total"]) if r["total"] > 0 else 0, axis=1
    )
    return pivot


@st.cache_data(ttl=30)
def _signal_count_trend(days: int = 30) -> pd.DataFrame:
    from sqlalchemy import text
    since = (now_kst() - timedelta(days=days)).isoformat()
    with db.get_conn() as conn:
        rows = conn.execute(
            text("""SELECT SUBSTR(created_at, 1, 10) AS d, COUNT(*) AS n
               FROM signals WHERE signal_type='BUY' AND created_at >= :since
               GROUP BY SUBSTR(created_at, 1, 10) ORDER BY d ASC"""),
            {"since": since},
        ).fetchall()
    return pd.DataFrame([dict(r._mapping) for r in rows])


@st.cache_data(ttl=60)
def _scan_funnel_today():
    try:
        from notifier import get_today_scan_stats
        return get_today_scan_stats()
    except Exception:
        return {}


@st.cache_data(ttl=300)
def _model_confidence_distribution():
    """학습 데이터 CSV에서 confidence 분포 추정 (가장 최근 CSV 사용)."""
    import glob
    csvs = sorted(glob.glob(os.path.join(MINT_ROOT, "data/models/training_data_*.csv")))
    if not csvs:
        return None
    try:
        import joblib
        import numpy as np
        from engine.features import FEATURE_NAMES
        df = pd.read_csv(csvs[-1])
        payload = joblib.load(os.path.join(MINT_ROOT, "data/models/mint_lgbm.joblib"))
        booster = payload["booster"]
        cal = payload.get("calibrator")
        df = df.sort_values("date").reset_index(drop=True)
        n_train = int(len(df) * 0.8)
        val = df.iloc[n_train:].copy()
        X = val[FEATURE_NAMES].values.astype(float)
        raw = booster.predict(X)
        val["prob"] = cal.predict(raw) if cal is not None else raw
        return {
            "df": val[["prob", "label"]],
            "csv_name": os.path.basename(csvs[-1]),
            "trained_at": payload.get("trained_at", ""),
            "val_metrics": payload.get("val_metrics", {}),
            "feature_importance": dict(zip(FEATURE_NAMES, booster.feature_importance(importance_type="gain"))),
        }
    except Exception as e:
        st.warning(f"모델/CSV 로드 실패: {e}")
        return None


# ── 사이드바 ─────────────────────────────────────────────
with st.sidebar:
    st.markdown("## 🌿 Mint")
    st.caption(f"v{now_kst().strftime('%Y-%m-%d %H:%M')} KST")
    st.markdown("---")
    page = st.radio(
        "메뉴",
        ["📊 대시보드", "🎯 추천 시그널", "💼 보유 포지션", "🧠 모델 분석", "📈 매매 이력"],
        label_visibility="collapsed",
    )
    st.markdown("---")
    include_us = st.checkbox("나스닥 포함", value=config.ops.enable_us_market_scan)
    if st.button("🔄 지금 스캔", use_container_width=True):
        _run_scan(include_us=include_us)
    if st.button("⏱️ catch-up (stale 만료)", use_container_width=True):
        n = db.expire_stale_signals()
        st.info(f"시간 만료: {n}건")
        price_expired = db.check_price_expiry()
        if price_expired:
            st.info(f"가격 만료: {len(price_expired)}건")
        # 미발송 만료 카톡 (2026-05-27 가로채기 fix와 동일 사유)
        pending = db.unnotified_expired_signals()
        if pending:
            try:
                from notifier import notify_expired_signals
                notify_expired_signals(pending)
                db.mark_expiry_notified([s["id"] for s in pending])
                st.info(f"만료 카톡: {len(pending)}건 발송")
            except Exception as e:
                st.warning(f"만료 카톡 실패: {e}")
    if st.button("🔬 Outcome 평가 (24h 지난 것)", use_container_width=True):
        n = db.evaluate_pending_outcomes(limit=200)
        st.info(f"평가됨: {n}건")
        st.cache_data.clear()
    st.markdown("---")
    st.caption(
        "운영: 수동 스캔 또는 작업 스케줄러 · "
        "손절/익절은 **권고** — 카카오페이에서 직접 실행"
    )


# ══════════════════════════════════════════════════════════
# 📊 대시보드 — 시장 / 오늘 funnel / 누적 성과 / outcome trend
# ══════════════════════════════════════════════════════════
if page == "📊 대시보드":
    st.markdown("## 📊 대시보드")

    # 시장 지수 (카드 a 활용) — KOSPI/KOSDAQ (Naver) + NASDAQ regime score만
    summary = _market_summary_cached()
    mc1, mc2 = st.columns(2)
    for col, code in zip((mc1, mc2), ("KOSPI", "KOSDAQ")):
        q = summary.get(code)
        if q is not None:
            col.metric(
                f"{q.emoji()} {code}",
                f"{q.value:,.2f}",
                f"{q.change_pct:+.2f}% ({q.change:+,.2f})",
            )
        else:
            col.metric(code, "—", "데이터 없음")

    # 시장 regime (2026-05-22 KR · 2026-05-26 NASDAQ 추가)
    try:
        from engine.market_regime import get_regime
        rc1, rc2, rc3 = st.columns(3)
        for col, code in zip((rc1, rc2, rc3), ("KOSPI", "KOSDAQ", "NASDAQ")):
            ri = get_regime(code)
            if ri is not None:
                col.metric(
                    f"{ri.emoji()} {code} regime",
                    ri.ko(),
                    f"5d {ri.ret_5d*100:+.1f}% / 20d {ri.ret_20d*100:+.1f}%",
                )
            else:
                col.metric(f"{code} regime", "—", "조회 실패")
        st.caption(
            "Regime은 dynamic exit(target/stop/holding)에 반영됨. "
            "강세→길게 잡고 작은 stop / 약세→짧게 자르고 작은 target. "
            "NASDAQ regime은 ^IXIC 일봉 기반 (KST 새벽 종가)."
        )
    except Exception as e:
        st.caption(f"Regime 모듈 미로드: {e}")

    st.markdown("---")

    # 추천 시간(보유 윈도우) 안의 활성 시그널 — 종목명만 (2026-05-27 사용자 요구사항)
    st.markdown("### 🎯 추천 시간 안의 시그널")
    active_sigs = db.get_signals_in_hold_window(limit=50)
    if not active_sigs:
        st.caption("추천 시간(보유 윈도우) 안의 시그널 없음.")
    else:
        fresh_items = [s for s in active_sigs if s.get("window_state") == "fresh"]
        hold_items = [s for s in active_sigs if s.get("window_state") == "hold"]

        def _name(s):
            return s.get("name") or s["ticker"]

        def _market_emoji(m):
            return {"KOSPI": "🇰🇷", "KOSDAQ": "🇰🇷", "NASDAQ": "🇺🇸"}.get(m, "📈")

        col_f, col_h = st.columns(2)
        with col_f:
            st.markdown(f"**🟢 매수 적기 ({len(fresh_items)}건)**")
            if fresh_items:
                lines = [
                    f"- {_market_emoji(s['market'])} {_name(s)} "
                    f"<small>({s.get('window_remaining_hours',0):.1f}h 남음)</small>"
                    for s in fresh_items[:10]
                ]
                st.markdown("\n".join(lines), unsafe_allow_html=True)
                if len(fresh_items) > 10:
                    st.caption(f"외 {len(fresh_items)-10}건 (→ 추천 시그널 페이지)")
            else:
                st.caption("없음 — 30분 안에 발생한 시그널 없음")

        with col_h:
            st.markdown(f"**🟡 보유 윈도우 ({len(hold_items)}건)**")
            if hold_items:
                lines = [
                    f"- {_market_emoji(s['market'])} {_name(s)} "
                    f"<small>({s.get('window_remaining_hours',0):.1f}h 남음)</small>"
                    for s in hold_items[:10]
                ]
                st.markdown("\n".join(lines), unsafe_allow_html=True)
                if len(hold_items) > 10:
                    st.caption(f"외 {len(hold_items)-10}건 (→ 추천 시그널 페이지)")
            else:
                st.caption("없음")

        st.caption("자세한 정보(목표가/손절가/regime 등)는 「🎯 추천 시그널」 페이지에서 확인.")

    st.markdown("---")

    # 오늘 스캔 funnel (카드 b 활용)
    fs = _scan_funnel_today()
    if fs.get("scans"):
        st.markdown("### 🔍 오늘 스캔 funnel")
        stages = [
            ("평가", fs.get("evaluated", 0)),
            ("모멘텀 통과", fs.get("passed_momentum", 0)),
            ("리스크 통과", fs.get("passed_risk", 0)),
            ("거래량 통과", fs.get("passed_volume", 0)),
        ]
        if config.signal.use_ml_confidence:
            stages.append(("ML 통과", fs.get("passed_ml", 0)))
        if config.signal.use_minute_rule:
            stages.append(("분봉 통과", fs.get("passed_minute", 0)))
        stages.append(("시그널", fs.get("signals_created", 0)))

        fig = go.Figure(go.Funnel(
            y=[s[0] for s in stages],
            x=[s[1] for s in stages],
            textposition="inside",
            textinfo="value+percent initial",
            marker={"color": "#3fb950"},
        ))
        fig.update_layout(height=320, margin=dict(l=10, r=10, t=10, b=10),
                          paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)")
        st.plotly_chart(fig, use_container_width=True)
        st.caption(
            f"오늘 {fs.get('scans',0)}회 스캔 · "
            f"중복 skip {fs.get('skipped_dedup',0)}건"
        )
    else:
        st.info("오늘 아직 스캔 기록 없음. 사이드바 「지금 스캔」 또는 작업 스케줄러 첫 트리거 후 표시됩니다.")

    st.markdown("---")

    # 누적 성과 (실 매도 기준)
    perf = db.get_performance_summary()
    st.markdown("### 💰 실 매도 누적 성과")
    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("총 매도", perf["total_trades"])
    c2.metric("승률", f"{perf['win_rate']:.1f}%")
    c3.metric("평균 수익률", f"{perf['avg_return_pct']:+.2f}%")
    c4.metric("평균 보유", f"{perf['avg_hold_hours']:.1f}h")
    c5.metric("누적 손익", f"₩{perf['total_profit']:,.0f}")

    st.markdown("---")

    # Outcome trend (카드 d 핵심)
    st.markdown("### 📈 시그널 Outcome trend (최근 30일)")
    trend = _outcome_trend_df(30)
    if trend.empty:
        st.info("아직 outcome이 평가된 시그널이 없습니다. 24h 지난 시그널부터 누적됩니다.")
    else:
        # 위: 일별 win/loss/time_exit stacked bar
        # 아래: 일별 win rate 선
        c_left, c_right = st.columns([2, 1])
        with c_left:
            fig = go.Figure()
            fig.add_bar(x=trend["d"], y=trend["WIN"], name="WIN", marker_color="#3fb950")
            fig.add_bar(x=trend["d"], y=trend["LOSS"], name="LOSS", marker_color="#f85149")
            fig.add_bar(x=trend["d"], y=trend["TIME_EXIT"], name="TIME_EXIT", marker_color="#8b949e")
            fig.update_layout(
                barmode="stack",
                height=300,
                margin=dict(l=10, r=10, t=30, b=10),
                title="일별 Outcome 분포",
                paper_bgcolor="rgba(0,0,0,0)",
                plot_bgcolor="rgba(0,0,0,0)",
                legend=dict(orientation="h", y=-0.2),
            )
            st.plotly_chart(fig, use_container_width=True)

        with c_right:
            total_win = int(trend["WIN"].sum())
            total_loss = int(trend["LOSS"].sum())
            total_time = int(trend["TIME_EXIT"].sum())
            total_all = total_win + total_loss + total_time
            win_rate = (total_win / total_all) if total_all else 0
            st.metric("누적 Win", total_win)
            st.metric("누적 Loss", total_loss)
            st.metric("누적 TIME_EXIT", total_time)
            st.metric("누적 Win rate", f"{win_rate*100:.1f}%")

        # 일별 win rate 라인
        fig2 = go.Figure()
        fig2.add_scatter(x=trend["d"], y=trend["win_rate"] * 100,
                         mode="lines+markers", line=dict(color="#58a6ff"), name="Win rate %")
        fig2.add_hline(y=50, line_dash="dot", line_color="#8b949e", annotation_text="50%")
        fig2.add_hline(y=78, line_dash="dot", line_color="#f0883e", annotation_text="모델 예상 78%")
        fig2.update_layout(
            height=240, margin=dict(l=10, r=10, t=30, b=10),
            title="일별 Win rate (모델 예상치 대비)",
            yaxis=dict(range=[0, 105], ticksuffix="%"),
            paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
        )
        st.plotly_chart(fig2, use_container_width=True)


# ══════════════════════════════════════════════════════════
# 🎯 추천 시그널
# ══════════════════════════════════════════════════════════
elif page == "🎯 추천 시그널":
    st.markdown("## 🎯 현재 추천 시그널")
    st.caption(
        f"필터: 24h 내 기대 +{config.signal.min_expected_return_1d*100:.0f}% 이상 · "
        f"매수 적기 유효 {config.ops.signal_valid_minutes}분 · "
        f"ML 임계값 {config.signal.min_model_confidence:.2f}"
        + (" · 🔥 분봉 ON" if config.signal.use_minute_rule else "")
    )
    st.caption(
        "🟢 **매수 적기**: 신호 신선도 윈도우(30분) 안 — 지금 매수 적합. "
        "🟡 **보유 윈도우**: 매수 적기는 지났지만 예상 보유 기간(max_hold_hours) 안 — "
        "아직 win/loss 미정. 만료(가격 도달 / acted)된 종목은 제외."
    )

    signals = db.get_signals_in_hold_window(limit=100)
    if not signals:
        st.info("추천 시간(보유 윈도우) 안의 시그널 없음. 아래 「오늘의 시그널 이력」에서 만료된 시그널 확인 가능.")
    else:
        fresh = [s for s in signals if s.get("window_state") == "fresh"]
        hold = [s for s in signals if s.get("window_state") == "hold"]
        st.write(f"🟢 매수 적기 **{len(fresh)}건** · 🟡 보유 윈도우 **{len(hold)}건**")

        # 두 그룹 순차 표시 — 매수 적기 먼저, 보유 윈도우 다음
        for group_label, group_state, group_items, container_class, badge_class, badge_text in [
            ("🟢 매수 적기 (지금 매수 적합)", "fresh", fresh, "signal-buy", "tag-fresh-window", "매수 적기"),
            ("🟡 보유 윈도우 (이미 매수했다면 보유 평가 중)", "hold", hold, "signal-hold", "tag-hold-window", "보유 윈도우"),
        ]:
            if not group_items:
                continue
            st.markdown(f"### {group_label}")

            for s in group_items:
                tag = f"tag-{s['market'].lower()}"
                exp = (s.get("expected_return") or 0) * 100
                ref = s.get("ref_price") or 0
                tgt = s.get("target_price") or 0
                stp = s.get("stop_price") or 0
                created_short = (s.get("created_at") or "")[:16].replace("T", " ")
                remaining_h = s.get("window_remaining_hours") or 0
                hold_h_total = s.get("max_hold_hours") or config.signal.max_hold_hours
                regime = s.get("regime_label") or "—"

                window_badge = f'<span class="{badge_class}">{badge_text} · {remaining_h:.1f}h 남음</span>'

                stale_badge = ""
                live_price = None
                if s["market"] in ("KOSPI", "KOSDAQ"):
                    kp = kis_client.get_current_price(s["ticker"])
                    if kp:
                        live_price = kp.price
                        drift = (live_price / ref - 1) * 100 if ref else 0
                        if kis_client.is_ref_price_stale(ref, live_price):
                            if drift > 0:
                                stale_badge = f'<span class="tag-stale">⚠️ STALE {drift:+.1f}%</span>'
                            else:
                                stale_badge = f'<span class="tag-stale">💡 {drift:+.1f}%</span>'
                        else:
                            stale_badge = f'<span class="tag-fresh">✓ 신선 {drift:+.1f}%</span>'

                cur_sym = "$" if s["market"] == "NASDAQ" else "₩"
                ref_fmt = f"{cur_sym}{ref:,.2f}" if s["market"] == "NASDAQ" else f"{ref:,.0f}원"
                tgt_fmt = f"{cur_sym}{tgt:,.2f}" if s["market"] == "NASDAQ" else f"{tgt:,.0f}원"
                stp_fmt = f"{cur_sym}{stp:,.2f}" if s["market"] == "NASDAQ" else f"{stp:,.0f}원"
                target_pct = ((tgt / ref - 1) * 100) if (ref and tgt) else 0
                stop_pct = ((stp / ref - 1) * 100) if (ref and stp) else 0
                live_fmt = (
                    f"{cur_sym}{live_price:,.2f}" if (live_price and s["market"] == "NASDAQ")
                    else (f"{live_price:,.0f}원" if live_price else "")
                )
                live_part = f" · 현재가 {live_fmt}" if live_price else ""

                st.markdown(
                    f"""
                <div class="{container_class}">
                    <span class="{tag}">{s['market']}</span>
                    <strong>{s.get('name') or s['ticker']}</strong>
                    <code>{s['ticker']}</code>{window_badge}{stale_badge}
                    — 모멘텀 +{exp:.1f}% · 리스크 {s.get('risk_score', 0):.0f}
                    · 기준가 {ref_fmt}{live_part}
                    <br>🎯 {tgt_fmt} ({target_pct:+.2f}%) / 손절 {stp_fmt} ({stop_pct:+.2f}%)
                    · 보유 {hold_h_total:.0f}h · regime <em>{regime}</em>
                    · 신뢰도 {(s.get('confidence') or 0)*100:.0f}%
                    · 발생 <em>{created_short}</em>
                </div>
                """,
                    unsafe_allow_html=True,
                )

                # 보유 윈도우 시그널은 폼 펼침 기본 false (매수 적기만 expanded=True 권장)
                expander_label = (
                    f"✅ 카카오페이에서 매수 후 체결 기록 — {s.get('name', s['ticker'])}"
                    if group_state == "fresh"
                    else f"📝 늦은 매수 기록 — {s.get('name', s['ticker'])} (보유 윈도우)"
                )
                with st.expander(expander_label):
                    with st.form(f"fill_{s['id']}"):
                        price = st.number_input(
                            "체결가", min_value=0.0,
                            value=float(ref) if ref else 0.0, step=100.0,
                            key=f"price_{s['id']}",
                        )
                        qty = st.number_input("수량", min_value=1, value=1, step=1, key=f"qty_{s['id']}")
                        fee = st.number_input("수수료", min_value=0.0, value=0.0, step=100.0, key=f"fee_{s['id']}")
                        if st.form_submit_button("체결함 — 포지션 등록"):
                            try:
                                pid = db.open_position_from_signal(s["id"], price, int(qty), fee)
                                st.success(f"포지션 #{pid} 등록 완료")
                                st.rerun()
                            except Exception as e:
                                st.error(str(e))

    # ── 오늘의 시그널 이력 (만료 포함, 2026-05-24 추가) ──────
    st.markdown("---")
    st.markdown("### 📜 오늘의 시그널 이력")
    st.caption(
        "오늘 발생한 모든 시그널 — 만료(expired)·체결(acted) 포함. "
        "유효시간(30분) 지나면 자동 expired. 발급 시점의 target/stop/hold/regime/모델 점수 보존."
    )

    from config.tz import today_kst
    _today = today_kst()
    _since = f"{_today}T00:00:00"
    today_signals = db.get_signals_since(_since)

    if not today_signals:
        st.info(f"오늘({_today}) 발생한 시그널 없음. funnel(대시보드)에 카운트가 있는데 이력이 없다면 다른 GHA scan에서 dedup 처리됐을 수 있음.")
    else:
        st.write(f"**{_today}** — 총 **{len(today_signals)}건**")
        for s in today_signals:
            status = s.get("status", "?")
            tag = f"tag-{s['market'].lower()}"
            ref = s.get("ref_price") or 0
            tgt = s.get("target_price") or 0
            stp = s.get("stop_price") or 0
            hold_h = s.get("max_hold_hours") or 24
            regime = s.get("regime_label") or "—"
            exp_pct = (s.get("expected_return") or 0) * 100
            conf_pct = (s.get("confidence") or 0) * 100
            ml_pct = (s.get("model_score") or 0) * 100
            target_pct = ((tgt / ref - 1) * 100) if (ref and tgt) else 0
            stop_pct = ((stp / ref - 1) * 100) if (ref and stp) else 0
            created = (s.get("created_at") or "")[:19].replace("T", " ")
            expiry_reason = s.get("expiry_reason") or ""

            # status별 아이콘/색
            if status == "active":
                status_badge = "🟢 active"
                bg = "rgba(63, 185, 80, 0.08)"
            elif status == "acted":
                status_badge = "📦 acted"
                bg = "rgba(31, 119, 200, 0.08)"
            elif status == "expired":
                reason_label = {"TIME": "시간만료", "TARGET_HIT": "목표가 도달", "STOP_HIT": "손절가 터치"}.get(
                    expiry_reason, expiry_reason or "만료"
                )
                status_badge = f"⏱ expired ({reason_label})"
                bg = "rgba(160, 160, 160, 0.08)"
            else:
                status_badge = status
                bg = "rgba(160, 160, 160, 0.08)"

            currency = "$" if s["market"] == "NASDAQ" else "₩"
            st.markdown(
                f"""
            <div style="background:{bg}; padding:10px 14px; border-radius:8px; margin-bottom:8px;">
                <span class="{tag}">{s['market']}</span>
                <strong>{s.get('name') or s['ticker']}</strong>
                <code>{s['ticker']}</code>
                · #{s['id']} · {status_badge}
                <br>
                🎯 <strong>{currency}{tgt:,.0f} ({target_pct:+.2f}%)</strong>
                / 손절 {currency}{stp:,.0f} ({stop_pct:+.2f}%)
                · ⏱ {hold_h:.0f}h
                · 시장 <em>{regime}</em>
                <br>
                기준가 {currency}{ref:,.0f}
                · 모멘텀 {exp_pct:+.1f}%
                · ML {ml_pct:.0f}% (전체 conf {conf_pct:.0f}%)
                · 발생 <em>{created}</em>
            </div>
            """,
                unsafe_allow_html=True,
            )

    # 어제~7일 누적 (요약)
    with st.expander("📊 최근 7일 시그널 이력 (요약)"):
        _week_since = (now_kst() - timedelta(days=7)).isoformat()
        week_signals = db.get_signals_since(_week_since, limit=300)
        if not week_signals:
            st.write("최근 7일 시그널 없음")
        else:
            import pandas as pd
            wdf = pd.DataFrame(week_signals)
            wdf["일자"] = wdf["created_at"].str[:10]
            summary = wdf.groupby(["일자", "status"]).size().unstack(fill_value=0).reset_index()
            st.dataframe(summary, use_container_width=True, hide_index=True)
            st.caption(f"총 {len(week_signals)}건 · 종목 유일 {wdf['ticker'].nunique()}개")


# ══════════════════════════════════════════════════════════
# 💼 보유 포지션 — P&L 게이지 추가 (카드 e)
# ══════════════════════════════════════════════════════════
elif page == "💼 보유 포지션":
    st.markdown("## 💼 보유 포지션")
    positions = db.get_open_positions()
    if not positions:
        st.info("보유 포지션 없음")

    for p in positions:
        advice = evaluate_position(p)
        cur = advice.current_price
        pct = advice.profit_pct
        buy = p["buy_price"]
        target = p.get("target_price") or 0
        stop = p.get("stop_loss") or 0

        emoji = "🟢" if pct >= 0 else "🔴"
        with st.expander(
            f"{emoji} {p.get('name')} ({p['ticker']}) {pct:+.1f}% — {advice.reason}",
            expanded=True,
        ):
            c1, c2 = st.columns([2, 1])
            with c1:
                # P&L 진행 게이지 — edge case 방어
                valid_range = (
                    target is not None and stop is not None
                    and target > stop > 0 and buy > 0
                )
                gauge_kwargs = {
                    "mode": "gauge+number+delta",
                    "value": cur,
                    "delta": {"reference": buy, "valueformat": ",.0f"},
                    "number": {"valueformat": ",.0f"},
                    "title": {"text": f"현재가 (매수 {buy:,.0f})"},
                }
                if valid_range:
                    gauge_kwargs["gauge"] = {
                        "axis": {"range": [stop * 0.99, target * 1.01]},
                        "bar": {"color": "#3fb950" if pct >= 0 else "#f85149"},
                        "steps": [
                            {"range": [stop, buy], "color": "rgba(248, 81, 73, 0.2)"},
                            {"range": [buy, target], "color": "rgba(63, 185, 80, 0.2)"},
                        ],
                        "threshold": {
                            "line": {"color": "white", "width": 2},
                            "thickness": 0.75,
                            "value": buy,
                        },
                    }
                else:
                    # target/stop 데이터 이상 시 단순 number indicator로 폴백
                    gauge_kwargs["mode"] = "number+delta"
                    st.warning(
                        "포지션의 target/stop 데이터에 이상이 있어 게이지를 표시할 수 없습니다."
                    )
                fig = go.Figure(go.Indicator(**gauge_kwargs))
                fig.update_layout(height=240, margin=dict(l=10, r=10, t=30, b=10),
                                  paper_bgcolor="rgba(0,0,0,0)")
                st.plotly_chart(fig, use_container_width=True)
            with c2:
                st.metric("매수가", f"{buy:,.0f}")
                st.metric("현재가", f"{cur:,.0f}", delta=f"{pct:+.2f}%")
                st.metric("목표가", f"{target:,.0f}")
                st.metric("손절가", f"{stop:,.0f}")
                st.caption(f"수량 {p.get('remaining_qty', p['quantity'])} · 보유 {advice.hold_hours:.1f}h")

            advice_css = {
                "SELL_NOW": "advice-sell",
                "CONSIDER_SELL": "advice-consider",
                "HOLD": "advice-hold",
            }.get(advice.action, "advice-hold")
            advice_label = {
                "SELL_NOW": "🚨 지금 매도 권고",
                "CONSIDER_SELL": "⚠️ 매도 고려",
                "HOLD": "🟢 보유 유지",
            }.get(advice.action, advice.action)
            st.markdown(
                f'<div class="{advice_css}"><strong>{advice_label}</strong> — '
                f'사유: <code>{advice.reason}</code>'
                + (f" · {advice.note}" if advice.note else "")
                + " · 실행은 카카오페이 앱에서 직접</div>",
                unsafe_allow_html=True,
            )

            with st.form(f"sell_{p['id']}"):
                st.markdown("**부분/전량 매도 기록**")
                sp = st.number_input("매도 체결가", value=float(cur), key=f"sp_{p['id']}")
                sq = st.number_input(
                    "매도 수량", min_value=1,
                    max_value=int(p.get("remaining_qty", p["quantity"])),
                    value=int(p.get("remaining_qty", p["quantity"])),
                    key=f"sq_{p['id']}",
                )
                reason = st.selectbox(
                    "사유", ["TARGET", "STOP_LOSS", "TIME", "MANUAL"],
                    key=f"sr_{p['id']}",
                )
                if st.form_submit_button("매도 체결함"):
                    db.close_position_partial(p["id"], sp, int(sq), exit_reason=reason)
                    st.success("매도 기록 완료")
                    st.rerun()


# ══════════════════════════════════════════════════════════
# 🧠 모델 분석 — confidence 슬라이더 + feature importance (카드 f)
# ══════════════════════════════════════════════════════════
elif page == "🧠 모델 분석":
    st.markdown("## 🧠 모델 / 시그널 분석")

    bundle = _model_confidence_distribution()
    if bundle is None:
        st.warning("학습 데이터/모델을 찾을 수 없습니다. `python mint/main.py train` 실행 필요.")
    else:
        m = bundle["val_metrics"] or {}
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Val AUC", f"{m.get('val_auc', 0):.3f}")
        c2.metric("Val LogLoss", f"{m.get('val_logloss', 0):.4f}")
        c3.metric("Train n", f"{m.get('n_train', 0):,}")
        c4.metric("Val n", f"{m.get('n_val', 0):,}")

        st.caption(
            f"데이터셋: `{bundle['csv_name']}` · 학습 시각: {bundle['trained_at'][:19]}"
        )

        st.markdown("---")
        st.markdown("### 임계값 시뮬레이션")
        st.caption(
            "슬라이더를 움직이면 해당 임계값에서의 시그널 수, precision, "
            "lift를 미리 볼 수 있습니다. (validation set 기준)  \n"
            "⚠️ 이 수치는 **분봉 룰·dedup·장중 stale 미반영**입니다. "
            "실 운영 카톡 도착 수와 다를 수 있어요."
        )

        thr = st.slider("ML confidence 임계값", 0.30, 0.95,
                        float(config.signal.min_model_confidence), 0.01)
        val = bundle["df"]
        sel = val[val["prob"] >= thr]
        base = val["label"].mean()
        n_total = len(val)
        n_sel = len(sel)
        prec = sel["label"].mean() if n_sel > 0 else 0
        lift = (prec / base) if base > 0 else 0
        rate = (n_sel / n_total) if n_total > 0 else 0

        sc1, sc2, sc3, sc4 = st.columns(4)
        sc1.metric("통과 시그널", f"{n_sel}")
        sc2.metric("통과율", f"{rate*100:.1f}%")
        sc3.metric("Precision", f"{prec:.3f}")
        sc4.metric("Lift", f"{lift:.2f}×")

        # Confidence 분포 히스토그램
        fig = go.Figure()
        fig.add_histogram(
            x=val[val["label"] == 1]["prob"],
            name="WIN", marker_color="#3fb950",
            opacity=0.7, nbinsx=40,
        )
        fig.add_histogram(
            x=val[val["label"] == 0]["prob"],
            name="LOSS", marker_color="#f85149",
            opacity=0.7, nbinsx=40,
        )
        fig.add_vline(x=thr, line_dash="dash", line_color="white",
                      annotation_text=f"임계값 {thr:.2f}")
        fig.update_layout(
            barmode="overlay", height=320,
            margin=dict(l=10, r=10, t=30, b=10),
            title="Confidence 분포 (validation set)",
            paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
            legend=dict(orientation="h", y=-0.2),
        )
        st.plotly_chart(fig, use_container_width=True)

        st.markdown("---")
        st.markdown("### 피처 중요도 (gain)")
        fi = bundle["feature_importance"]
        fi_df = pd.DataFrame([
            {"feature": k, "gain": v} for k, v in fi.items()
        ]).sort_values("gain", ascending=True)
        fi_df["pct"] = fi_df["gain"] / fi_df["gain"].sum() * 100
        fig2 = go.Figure()
        fig2.add_bar(
            x=fi_df["pct"], y=fi_df["feature"],
            orientation="h", marker_color="#58a6ff",
            text=[f"{p:.1f}%" for p in fi_df["pct"]],
            textposition="outside",
        )
        fig2.update_layout(
            height=480, margin=dict(l=10, r=80, t=30, b=10),
            title="피처 기여도 (gain %)",
            paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
        )
        st.plotly_chart(fig2, use_container_width=True)


# ══════════════════════════════════════════════════════════
# 📈 매매 이력
# ══════════════════════════════════════════════════════════
elif page == "📈 매매 이력":
    st.markdown("## 📈 매매 이력")
    trades = db.get_trade_history(100)
    if not trades:
        st.info("거래 이력 없음")
    else:
        df = pd.DataFrame(trades)
        show = df[
            ["created_at", "name", "ticker", "market", "action",
             "price", "quantity", "profit_pct", "exit_reason"]
        ]
        show.columns = ["시각", "종목", "코드", "시장", "구분",
                        "가격", "수량", "수익률%", "사유"]
        st.dataframe(show, use_container_width=True, height=400)
