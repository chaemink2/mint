"""
Rule-based signal scanner (Step 2 E2E).
ML confidence is NOT used until LightGBM is calibrated (Step 3b).
"""
import logging
from datetime import datetime, timedelta
from typing import List, Optional

import pandas as pd

from config.settings import config
from data import krx_client, us_client
from data.collector import fetch_watchlists_by_markets
from engine.features import compute_features
from engine.models.lgbm import get_cached_model
from portfolio import db

log = logging.getLogger("mint.rule_scanner")


def _volume_ratio(df: pd.DataFrame, window: int = 20) -> float:
    if len(df) < window + 1:
        return 0.0
    vol = df["volume"].astype(float)
    recent = vol.iloc[-1]
    avg = vol.iloc[-window - 1 : -1].mean()
    if avg <= 0:
        return 0.0
    return float(recent / avg)


def _risk_score(df: pd.DataFrame, window: int = 14) -> float:
    """0–100: higher = riskier (ATR% scaled)."""
    if len(df) < window + 1:
        return 100.0
    high = df["high"].astype(float)
    low = df["low"].astype(float)
    close = df["close"].astype(float)
    tr = pd.concat(
        [
            high - low,
            (high - close.shift(1)).abs(),
            (low - close.shift(1)).abs(),
        ],
        axis=1,
    ).max(axis=1)
    atr = tr.rolling(window).mean().iloc[-1]
    last = close.iloc[-1]
    if last <= 0:
        return 100.0
    atr_pct = float(atr / last)
    return min(100.0, atr_pct * 500)


def _estimate_expected_return_1d(df: pd.DataFrame) -> float:
    """
    Heuristic proxy for 'can we expect +3% within ~1 trading day'.
    Not ML — replaced in Step 3b.
    """
    if len(df) < 6:
        return 0.0
    close = df["close"].astype(float)
    ret_5d = close.iloc[-1] / close.iloc[-6] - 1
    ret_1d = close.iloc[-1] / close.iloc[-2] - 1
    vol_r = _volume_ratio(df)
    # Momentum + volume participation proxy
    est = ret_5d * 0.35 + ret_1d * 0.25 + max(0, vol_r - 1) * 0.04
    return float(est)


def _rule_score(df: pd.DataFrame, expected: float, risk: float, vol_ratio: float) -> float:
    """0–1 rule confidence (stored in model_score; NOT calibrated ML probability)."""
    score = 0.0
    sig = config.signal
    if expected >= sig.min_expected_return_1d:
        score += 0.4
    if risk <= sig.max_risk_score:
        score += 0.3
    if vol_ratio >= sig.min_volume_ratio:
        score += 0.3
    return min(1.0, score)


_NAME_CACHE: dict[tuple[str, str], str] = {}


def _resolve_name(ticker: str, market: str) -> str:
    """ticker → 종목명. 백테스트는 같은 ticker를 수십번 평가하므로 캐시."""
    key = (ticker, market)
    cached = _NAME_CACHE.get(key)
    if cached is not None:
        return cached
    if market in ("KOSPI", "KOSDAQ"):
        name = krx_client.get_stock_name(ticker)
    elif market == "NASDAQ":
        name = us_client.get_stock_name(ticker)
    else:
        name = ticker
    _NAME_CACHE[key] = name or ticker
    return _NAME_CACHE[key]


def _ml_probability(df: pd.DataFrame) -> Optional[float]:
    """ML confidence (캘리브레이션된 P(win)). 비활성/모델없음/추론실패 시 None."""
    if not config.signal.use_ml_confidence:
        return None
    model = get_cached_model()
    if model is None:
        log.warning(
            "MINT_USE_ML_CONFIDENCE=true지만 모델 미로드 — `python mint/main.py train` 먼저 실행"
        )
        return None
    feats = compute_features(df)
    if feats is None:
        return None
    return model.predict_proba(feats)


def evaluate_ticker(ticker: str, market: str, df: pd.DataFrame) -> Optional[dict]:
    if df is None or len(df) < 25:
        return None

    sig = config.signal
    expected = _estimate_expected_return_1d(df)
    risk = _risk_score(df)
    vol_ratio = _volume_ratio(df)
    rule_conf = _rule_score(df, expected, risk, vol_ratio)
    ref_price = float(df["close"].iloc[-1])

    if expected < sig.min_expected_return_1d:
        return None
    if risk > sig.max_risk_score:
        return None
    if vol_ratio < sig.min_volume_ratio:
        return None

    # ML 필터 — use_ml_confidence=True일 때만. None이면 룰만으로 통과.
    ml_conf = _ml_probability(df)
    if ml_conf is not None and ml_conf < sig.min_model_confidence:
        return None

    # 분봉 룰 (use_minute_rule=True일 때만, 일봉+ML 통과 후 AND 결합)
    minute_info = None
    if sig.use_minute_rule and market in ("KOSPI", "KOSDAQ"):
        from engine.signals.minute_rule import fetch_and_evaluate
        minute_info = fetch_and_evaluate(ticker)
        if minute_info is None:
            log.debug("Skip %s — 분봉 룰 미통과 또는 KIS 분봉 fetch 실패", ticker)
            return None

    target_price = ref_price * (1 + sig.target_return)
    stop_price = ref_price * (1 + sig.stop_loss)

    # 최종 confidence: ML 있으면 ML, 없으면 룰
    final_conf = ml_conf if ml_conf is not None else rule_conf

    result = {
        "ticker": ticker,
        "market": market,
        "name": _resolve_name(ticker, market),
        "expected_return": expected,
        "risk_score": risk,
        "model_score": final_conf,
        "ml_confidence": ml_conf,
        "rule_confidence": rule_conf,
        "ref_price": ref_price,
        "target_price": target_price,
        "stop_price": stop_price,
        "volume_ratio": vol_ratio,
    }
    if minute_info:
        result.update(minute_info)
    return result


def run_rule_scan(markets: Optional[List[str]] = None) -> List[int]:
    """
    Scan KR watchlists, log BUY signals to DB.
    Returns list of new signal IDs.
    하루 한도(max_daily_buys) 도달 시 신규 시그널 발급 중단.
    """
    db.init_db()
    db.migrate_db()
    db.expire_stale_signals()

    markets = markets or ["KOSPI", "KOSDAQ"]
    bars_map = fetch_watchlists_by_markets(markets, days=60)

    # 오늘 이미 발생한 BUY 카운트 → max_daily_buys 한도
    from datetime import datetime as _dt
    today_start = _dt.now().strftime("%Y-%m-%d") + "T00:00:00"
    with db.get_conn() as conn:
        today_count = conn.execute(
            "SELECT COUNT(*) FROM signals WHERE signal_type='BUY' AND created_at >= ?",
            (today_start,),
        ).fetchone()[0]
    daily_limit = config.signal.max_daily_buys
    remaining = max(0, daily_limit - today_count)
    if remaining == 0:
        log.info("Daily BUY limit reached (%d) — skipping new signals", daily_limit)
        return []

    new_ids: List[int] = []
    dedup_hours = config.ops.signal_dedup_hours

    for ticker, df in bars_map.items():
        if len(new_ids) >= remaining:
            log.info("Daily BUY limit hit (%d) — stopping scan", daily_limit)
            break
        if df.empty:
            continue
        market = df["market"].iloc[-1]
        if market not in markets:
            continue

        candidate = evaluate_ticker(ticker, market, df)
        if not candidate:
            continue

        if db.has_recent_signal(ticker, "BUY", hours=dedup_hours):
            log.debug("Skip %s — recent BUY within %sh", ticker, dedup_hours)
            continue

        valid_until = (
            datetime.now() + timedelta(minutes=config.ops.signal_valid_minutes)
        ).isoformat()

        sid = db.log_signal(
            ticker=candidate["ticker"],
            market=candidate["market"],
            name=candidate["name"],
            signal_type="BUY",
            confidence=candidate["model_score"],
            expected_return=candidate["expected_return"],
            risk_score=candidate["risk_score"],
            model_score=candidate["model_score"],
            ref_price=candidate["ref_price"],
            valid_until=valid_until,
            target_price=candidate["target_price"],
            stop_price=candidate["stop_price"],
        )
        new_ids.append(sid)
        ml_info = (
            f" ML={candidate['ml_confidence']:.2f}"
            if candidate.get("ml_confidence") is not None
            else ""
        )
        log.info(
            "BUY signal #%s %s (%s) exp=%.2f%% risk=%.0f ref=%.0f%s",
            sid,
            candidate["name"],
            ticker,
            candidate["expected_return"] * 100,
            candidate["risk_score"],
            candidate["ref_price"],
            ml_info,
        )

    log.info("Rule scan done — %s new signal(s)", len(new_ids))
    return new_ids
