"""
Mint Dashboard - Streamlit
실행: streamlit run mint/dashboard/app.py  (workspace 루트에서)
"""
import streamlit as st
import pandas as pd
import plotly.graph_objects as go
from datetime import datetime
import sys
import os

MINT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, MINT_ROOT)

from config.settings import config
from portfolio import db
from engine.signals.rule_scanner import run_rule_scan
from engine.signals.exit_strategy import evaluate_position
from data.collector import fetch_bars
from data import kis_client

db.init_db()
db.migrate_db()

st.set_page_config(page_title="Mint", page_icon="🌿", layout="wide", initial_sidebar_state="expanded")

st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;500&family=Pretendard:wght@300;400;500;600&display=swap');
html, body, [class*="css"] { font-family: 'Pretendard', sans-serif; }
.signal-buy {
    background: rgba(35, 134, 54, 0.15);
    border: 1px solid rgba(35, 134, 54, 0.4);
    border-radius: 8px; padding: 12px 16px; margin: 6px 0;
}
.tag-kospi { background: #1e3a5f; color: #58a6ff; padding: 2px 8px; border-radius: 4px; font-size: 11px; }
.tag-kosdaq { background: #2d1e5f; color: #d2a8ff; padding: 2px 8px; border-radius: 4px; font-size: 11px; }
.tag-nasdaq { background: #3a2d1e; color: #ffb454; padding: 2px 8px; border-radius: 4px; font-size: 11px; }
.tag-stale { background: #4a1e1e; color: #ff7b72; padding: 2px 8px; border-radius: 4px; font-size: 11px; margin-left: 6px; }
.advice-sell { background: rgba(248, 81, 73, 0.18); border: 1px solid rgba(248, 81, 73, 0.5); border-radius: 6px; padding: 8px 12px; }
.advice-consider { background: rgba(240, 136, 62, 0.18); border: 1px solid rgba(240, 136, 62, 0.5); border-radius: 6px; padding: 8px 12px; }
.advice-hold { background: rgba(63, 185, 80, 0.10); border: 1px solid rgba(63, 185, 80, 0.35); border-radius: 6px; padding: 8px 12px; }
[data-testid="stSidebar"] { background: #0d1117; border-right: 1px solid #21262d; }
</style>
""", unsafe_allow_html=True)


def _latest_close(ticker: str, market: str):
    try:
        bars = fetch_bars(ticker, market, days=5)
        if bars.empty:
            return None
        return float(bars["close"].iloc[-1])
    except Exception:
        return None


def _run_scan(include_us: bool = False):
    markets = ["KOSPI", "KOSDAQ"]
    if include_us:
        markets.append("NASDAQ")
    with st.spinner(f"시그널 스캔 중... ({', '.join(markets)})"):
        ids = run_rule_scan(markets=markets)
    st.success(f"스캔 완료 — 신규 시그널 {len(ids)}건")
    st.cache_data.clear()


# ── 사이드바 ─────────────────────────────────────────────
with st.sidebar:
    st.markdown("## 🌿 Mint")
    st.markdown("---")
    page = st.radio(
        "메뉴",
        ["📊 대시보드", "🎯 추천 시그널", "💼 보유 포지션", "📈 매매 이력"],
        label_visibility="collapsed",
    )
    st.markdown("---")
    st.caption("운영: 수동 스캔 · 손절/익절은 **권고** (카카오페이에서 실행)")
    include_us = st.checkbox("나스닥 포함", value=config.ops.enable_us_market_scan)
    if st.button("🔄 지금 스캔", use_container_width=True):
        _run_scan(include_us=include_us)
    if st.button("⏱️ catch-up (stale 만료)", use_container_width=True):
        n = db.expire_stale_signals()
        st.info(f"만료 처리: {n}건")

perf = db.get_performance_summary()

# ══════════════════════════════════════════════════════════
if page == "📊 대시보드":
    st.markdown("## 📊 대시보드")
    st.caption(f"업데이트: {datetime.now().strftime('%Y-%m-%d %H:%M')}")

    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("총 매도 거래", perf["total_trades"])
    c2.metric("승률", f"{perf['win_rate']:.1f}%")
    c3.metric("평균 수익률", f"{perf['avg_return_pct']:+.2f}%")
    c4.metric("평균 보유", f"{perf['avg_hold_hours']:.1f}h")
    c5.metric("누적 손익", f"₩{perf['total_profit']:,.0f}")

    trades = db.get_trade_history(30)
    sells = [t for t in trades if t["action"] == "SELL"]
    if sells:
        df = pd.DataFrame(sells)
        fig = go.Figure()
        colors = ["#3fb950" if x >= 0 else "#f85149" for x in df["profit_pct"]]
        fig.add_bar(x=list(range(len(df))), y=df["profit_pct"], marker_color=colors)
        fig.add_hline(y=3.0, line_dash="dot", line_color="#f0883e")
        fig.add_hline(y=-2.0, line_dash="dot", line_color="#f85149")
        fig.update_layout(height=280, margin=dict(l=0, r=0, t=10, b=10),
                          paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)")
        st.plotly_chart(fig, use_container_width=True)
    else:
        st.info("아직 체결 기록이 없습니다. 시그널 탭에서 스캔 후 「체결함」을 입력하세요.")

elif page == "🎯 추천 시그널":
    st.markdown("## 🎯 현재 추천 시그널")
    st.caption(
        f"필터: 24h 내 기대 +{config.signal.min_expected_return_1d*100:.0f}% 미만이면 미추천 · "
        f"유효 {config.ops.signal_valid_minutes}분 · "
        f"손절 {config.signal.stop_loss*100:.0f}%는 **권고** (자동 실행 아님)"
    )

    signals = db.get_active_signals()
    if not signals:
        st.warning("활성 시그널 없음. 사이드바에서 「지금 스캔」을 실행하세요.")
    else:
        for s in signals:
            tag = f"tag-{s['market'].lower()}"
            exp = (s.get("expected_return") or 0) * 100
            ref = s.get("ref_price") or 0
            tgt = s.get("target_price") or 0
            stp = s.get("stop_price") or 0
            valid = (s.get("valid_until") or "")[:16].replace("T", " ")

            # KIS 현재가가 있으면 stale 판정 + 표시
            stale_badge = ""
            live_price = None
            if s["market"] in ("KOSPI", "KOSDAQ"):
                kp = kis_client.get_current_price(s["ticker"])
                if kp:
                    live_price = kp.price
                    if kis_client.is_ref_price_stale(ref, live_price):
                        drift = (live_price / ref - 1) * 100 if ref else 0
                        stale_badge = f'<span class="tag-stale">STALE {drift:+.1f}%</span>'

            live_part = f" · 현재가 {live_price:,.0f}" if live_price else ""
            st.markdown(f"""
            <div class="signal-buy">
                <span class="{tag}">{s['market']}</span>
                <strong>{s.get('name') or s['ticker']}</strong>
                <code>{s['ticker']}</code>{stale_badge}
                — 예상 +{exp:.1f}% · 리스크 {s.get('risk_score', 0):.0f}
                · 기준가 {ref:,.0f}{live_part} · 유효 ~{valid}
            </div>
            """, unsafe_allow_html=True)

            with st.expander(f"✅ 카카오페이에서 매수 후 체결 기록 — {s.get('name', s['ticker'])}"):
                with st.form(f"fill_{s['id']}"):
                    price = st.number_input(
                        "체결가",
                        min_value=0.0,
                        value=float(ref) if ref else 0.0,
                        step=100.0,
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

elif page == "💼 보유 포지션":
    st.markdown("## 💼 보유 포지션")
    positions = db.get_open_positions()
    if not positions:
        st.info("보유 포지션 없음")
    for p in positions:
        advice = evaluate_position(p)
        cur = advice.current_price
        pct = advice.profit_pct
        with st.expander(f"{'🟢' if pct >= 0 else '🔴'} {p.get('name')} ({p['ticker']}) {pct:+.1f}% — {advice.reason}", expanded=True):
            c1, c2, c3, c4 = st.columns(4)
            c1.metric("매수가", f"{p['buy_price']:,.0f}")
            c2.metric("현재가(참고)", f"{cur:,.0f}", delta=f"{pct:+.1f}%")
            c3.metric("목표가", f"{(p.get('target_price') or 0):,.0f}")
            c4.metric("손절 권고", f"{(p.get('stop_loss') or 0):,.0f}")
            st.caption(f"수량 {p.get('remaining_qty', p['quantity'])} · 출처 {p.get('source')} · {p['buy_time'][:16]} · 보유 {advice.hold_hours:.1f}h")

            advice_css = {
                "SELL_NOW": "advice-sell",
                "CONSIDER_SELL": "advice-consider",
                "HOLD": "advice-hold",
            }[advice.action]
            advice_label = {
                "SELL_NOW": "🚨 지금 매도 권고",
                "CONSIDER_SELL": "⚠️ 매도 고려",
                "HOLD": "🟢 보유 유지",
            }[advice.action]
            st.markdown(
                f'<div class="{advice_css}"><strong>{advice_label}</strong> — '
                f'사유: <code>{advice.reason}</code>'
                + (f' · {advice.note}' if advice.note else "")
                + ' · 실행은 카카오페이 앱에서 직접</div>',
                unsafe_allow_html=True,
            )

            with st.form(f"sell_{p['id']}"):
                st.markdown("**부분/전량 매도 기록**")
                sp = st.number_input("매도 체결가", value=float(cur), key=f"sp_{p['id']}")
                sq = st.number_input(
                    "매도 수량",
                    min_value=1,
                    max_value=int(p.get("remaining_qty", p["quantity"])),
                    value=int(p.get("remaining_qty", p["quantity"])),
                    key=f"sq_{p['id']}",
                )
                reason = st.selectbox("사유", ["TARGET", "STOP_LOSS", "TIME", "MANUAL"], key=f"sr_{p['id']}")
                if st.form_submit_button("매도 체결함"):
                    db.close_position_partial(p["id"], sp, int(sq), exit_reason=reason)
                    st.success("매도 기록 완료")
                    st.rerun()

elif page == "📈 매매 이력":
    st.markdown("## 📈 매매 이력")
    trades = db.get_trade_history(100)
    if not trades:
        st.info("거래 이력 없음")
    else:
        df = pd.DataFrame(trades)
        show = df[["created_at", "name", "ticker", "market", "action", "price", "quantity", "profit_pct", "exit_reason"]]
        show.columns = ["시각", "종목", "코드", "시장", "구분", "가격", "수량", "수익률%", "사유"]
        st.dataframe(show, use_container_width=True, height=400)
