# Mint — NASDAQ 확장 인수인계 (별도 Claude Code Chat 세션 용)

> **목표**: 현재 KOSPI/KOSDAQ 동급 수준으로 NASDAQ 운영 가능하게.
> **작성일**: 2026-05-24
> **상태 (2026-05-27)**: **Stage 1+2 완료** (`9311065` + 본 commit). Stage 3 (백테스트 + 1주 시범 운영) 진행 가능.
> **작업 대상**: 별도 Claude Code Chat 세션. 본 문서는 self-contained — 다른 세션이 이 문서만 읽어도 즉시 작업 시작 가능.
> **선행 학습**: `OPERATION_WEEK1.md`(현재 KR 운영 상태) + `CLAUDE.md` 픽업 가이드.

---

## ✅ 진행 상태 (2026-05-27)

| Stage | 상태 | 결과 |
|---|---|---|
| **Stage 1 인프라** | ✅ 완료 (`9311065`) | universe NASDAQ-100 동적, regime ^IXIC, dynamic exit·outcome 평가 NASDAQ 분기, 카톡 currency 분기, 대시보드 regime 3개 |
| **Stage 2 ML 학습** | ✅ 완료 | `mint_lgbm_us.joblib` (171종목, 24h +2%/-2%, AUC 0.553, best_iter 31, 임계값 0.55에서 precision 0.636·일평균 0.22건). 라벨 변경 사용자 (B) 합의 |
| **scan-us.yml** | ✅ 활성화 | `*/10 13-21 * * 1-5` UTC (NY 정규장 DST/비DST 모두). ML ON · 분봉 OFF (Alpaca 미도입) |
| Stage 2.5 분봉 (Alpaca) | ⏳ 보류 | 사용자 (3) Alpaca 결정. 가입·키 발급 후 도입 |
| Stage 3 백테스트·시범 | ⏳ 다음 | NASDAQ 백테스트 + 1주 시범 운영 outcome 측정 |

---

## 🎯 한 줄 요약

**NASDAQ을 "그냥 켜기"는 가능하나 ML 모델·분봉·regime·outcome 평가 모두 KR 분포에 묶여 있어 신뢰도 미달. 인프라 보강 + 전용 학습으로 KR 동급(val AUC 0.58+ / precision 0.7+) 달성이 본 작업의 정의.**

---

## 🔍 현재 NASDAQ 상태 진단 (2026-05-24)

| 컴포넌트 | KOSPI/KOSDAQ | NASDAQ 현재 | 보강 필요? |
|---|---|---|---|
| 워치리스트 | Naver 시총 상위 200 (24h 캐시) | `config/markets.py` 정적 15종목 | ✅ |
| 일봉 데이터 | pykrx (안정) | yfinance | 🟡 |
| ML 모델 | 200×730d 학습, AUC 0.582 | **학습 데이터 0건**. 추론 시 KR 모델 그대로 적용 | ✅ |
| 분봉 룰 | KIS 5분봉 (`engine/signals/minute_rule.py`) | KIS 미지원 → 적용 안 됨 | ✅ |
| STALE 마커 | KIS 현재가 (`data/kis_client.py`) | 미지원 | 🟡 |
| Regime | yfinance `^KS11`/`^KQ11` (`engine/market_regime.py`) | NASDAQ 미적용 | ✅ |
| Dynamic Exit | ATR + regime → target/stop/hold | rule_scanner에서 NASDAQ은 기존 고정값 fallback | ✅ |
| Outcome 평가 | `_evaluate_single_outcome` if market in KR | `if sig.get("market") not in ("KOSPI","KOSDAQ"): return None` → **미평가** | ✅ |
| GHA cron | `scan-kr.yml` 활성 | `scan-us.yml` schedule **주석** (workflow_dispatch만) | ✅ |
| Currency | KRW 표기 | mixed (코드 곳곳에 ₩ 하드코딩) | 🟡 |

---

## 🏗️ 작업 분해 — Stage 1~3

### Stage 1 — 인프라 (4~6h) — ML 학습 전 모든 인프라 갖춰야 학습 의미 있음

#### 1-1. 워치리스트 동적화 (`data/universe.py`)
- 현재: KR만 `_fetch_top_n_naver` 동적, NASDAQ은 static 15종목
- 작업: NASDAQ 시총 상위 N(200) 자동 추출
- 데이터 소스 옵션:
  - (a) **Wikipedia NASDAQ-100/500 스크래핑** — 가장 단순. 시총 정렬은 X(인덱스 구성종목만). 100종목 보장.
  - (b) **`nasdaqtrader.com/nasdaqlisted.txt`** — 무료 공식. 전체 NASDAQ 종목 리스트. 시총 정렬 X.
  - (c) **yfinance Tickers `info` 1개씩 호출** — `marketCap` 필드 있음. 200종목 = 200 API call. 캐시 24h면 일회성 부담.
  - (d) **Alpaca `/v2/assets`** — 무료, fast. 다만 시총 정렬 X. Alpaca 가입 필요.
- **권장 (a)+(c) 결합**: NASDAQ-100을 시드 + yfinance로 marketCap 정렬해 상위 N. 캐시 24h.

#### 1-2. Market Regime 모듈 보강 (`engine/market_regime.py`)
```python
def _market_index_yfinance(market: str) -> Optional[str]:
    return {
        "KOSPI": "^KS11",
        "KOSDAQ": "^KQ11",
        "NASDAQ": "^IXIC",   # NASDAQ Composite (또는 ^NDX = NASDAQ-100)
    }.get(market.upper())
```
- `both_regimes_line()`을 `regimes_line(markets: List[str])`로 확장. 카톡/대시보드에 3개 표시
- composite_score 임계값 (±0.04, ±0.01)이 NASDAQ에도 적정인지 — 미국 시장은 변동성 다름. 1주 데이터로 cut 재조정 검토

#### 1-3. Dynamic Exit NASDAQ 지원 (`engine/signals/rule_scanner.py:evaluate_ticker`)
```python
# 현재
if market in ("KOSPI", "KOSDAQ"):
    _de = compute_dynamic_exit(...)
else:
    # NASDAQ — 기존 고정값 fallback
    target_price = ref_price * (1 + sig.target_return)
    ...

# 변경 후
if market in ("KOSPI", "KOSDAQ", "NASDAQ"):
    _de = compute_dynamic_exit(...)
```
- market_regime이 NASDAQ 지원하면 자동 동작 (Stage 1-2 선행)

#### 1-4. Outcome 평가 NASDAQ 지원 (`portfolio/db.py:_evaluate_single_outcome`)
```python
# 현재
if sig.get("market") not in ("KOSPI", "KOSDAQ"):
    return None
bars = _krx.fetch_daily_bars(sig["ticker"], sig["market"], days=5)

# 변경 후
market = sig.get("market", "")
if market not in ("KOSPI", "KOSDAQ", "NASDAQ"):
    return None
if market == "NASDAQ":
    from data import us_client as _us
    bars = _us.fetch_daily_bars(sig["ticker"], market, days=5)
else:
    bars = _krx.fetch_daily_bars(sig["ticker"], market, days=5)
```
- `us_client.fetch_daily_bars` 시그니처가 canonical(`ts_local`, `high`, `low`, `close`) 호환인지 확인
- 일봉 first-hit 로직은 동일하게 동작

#### 1-5. GHA `scan-us.yml` 활성화
- 현재: `schedule` 주석, `workflow_dispatch`만
- 변경:
  ```yaml
  on:
    schedule:
      - cron: '*/10 13-19 * * 1-5'   # UTC 13:30~19:50 = KST 22:30~04:50 (NY 정규장)
    workflow_dispatch: {}
  ```
- 또는 daylight savings 고려 — DST/Standard time 사이 cron 시각 1h 차이. `pandas_market_calendars` 도입 검토 또는 두 시각 모두 cron
- env에 `MINT_WATCHLIST_SIZE`, `MINT_MAX_RISK_SCORE` 등 KR과 동일 환경변수 추가

#### 1-6. 카톡 메시지 currency 분기 (`notifier/__init__.py:_format_buy_signal`)
- `f"{ref:,.0f}원"`, `f"{target:,.0f} / 손절 {stop:,.0f}"` 등 ₩ 하드코딩
- NASDAQ이면 `f"${ref:,.2f}"` 형식
- helper 함수 `_format_price(value, market)` 도입 권장

#### 1-7. STALE 마커 (선택, 1-3 완료 후)
- KIS 현재가 → yfinance/Alpaca 현재가 분기
- yfinance는 15분 지연, Alpaca free는 실시간
- 다만 KST 새벽 NASDAQ 운영 시 사용자 즉시 매매 어려워 STALE 의미 작음 — 일단 OFF로 시작 가능

---

### Stage 2 — ML 학습 (6~10h)

#### 2-1. 학습 데이터 구축
- 200종목 × 730일 일봉 fetch (yfinance)
- 200종목 × 730일 = 시간 부담 — yfinance batch API (`yf.download(tickers, ...)`)로 batch fetch 가능
- 캐시 권장 (parquet 등)
- feature 16개 KR과 동일 (atr_pct, rsi_14, gap_pct, bb_position 등)
- 라벨: 24h 내 +3% 도달 (KR과 동일 기준 — 시장 비교 위해)

#### 2-2. 모델 선택 (사용자 결정 사안)
- **Option A (권장)**: NASDAQ 전용 `mint_lgbm_us.joblib`. 시장 분포 분리. 정직한 평가.
- **Option B**: KR+US 통합 + `market_id` feature. 데이터 양 ↑이나 분포 mismatch로 AUC 깨질 위험.
- **Option C**: KR 모델로 임시 시작 → 1개월 후 재학습. 초기 precision 보장 X.

#### 2-3. 학습 (`engine/training.py` 시장 분기 추가)
- KR과 동일 LightGBM + isotonic calibration
- val AUC, precision, 일평균 시그널 수 측정
- **합격 기준**: val AUC ≥ 0.55, precision @ 0.60 ≥ 0.7. 미달 시 feature 보강 또는 데이터 확대

#### 2-4. 모델 파일 commit
- `mint/data/models/mint_lgbm_us.joblib` repo 포함 (KR 모델과 동일 패턴)
- `engine/models/lgbm.py`에 시장 분기 로더 추가 (`get_cached_model(market="KR" or "US")`)

---

### Stage 3 — 검증 + 운영 (1~2주)

#### 3-1. 백테스트 (`engine/backtest.py`)
- NASDAQ 종목 backtest 인프라 보강 (`fetch_watchlists_by_markets`에 NASDAQ 지원)
- KR baseline (AUC 0.582) 대비 결과 표 — `mint/CLAUDE.md`의 「학습 결과 기록」에 추가

#### 3-2. 시범 운영 (1주)
- GHA scan-us cron 활성화 후 1주 운영
- outcome 누적 → live precision vs val precision 비교
- 격차가 0.1 이하면 OK, 그 이상이면 회귀 분석

#### 3-3. 사용자 액션
- 카카오페이증권 해외주식 매매 환경 확인 (FX, 수수료, 거래시간)
- 카톡 새벽 알림 — 사용자 수면 영향 검토 (silent 시간대 옵션 추가 검토)

---

## 🧠 분봉 룰 NASDAQ 적용 (선택, Stage 2.5)

- **Option 1**: OFF로 일관 — KR과 차이. precision ↓ 가능.
- **Option 2**: yfinance 1m interval (`yf.download(ticker, period="1d", interval="1m")`) — 60일 내 데이터 제공. KR `minute_rule` 패턴(vol_spike + 양봉) 그대로 적용 가능.
- **Option 3**: Alpaca real-time WebSocket — 가입 필수, 실시간이지만 setup 비용.

**권장 Stage 2.5 (option 2)**: yfinance 1m 분봉 + 동일 vol_spike 임계값. 추후 outcome으로 임계값 calibration.

---

## 🚨 정직한 평가 — 위험 신호

| 우려 | 평가 / 대응 |
|---|---|
| NASDAQ에서 24h +3% 빈도 | KR보다 변동 ↑이지만 야간(KST)에 사용자 매매 못 함 → 실 익절 어려움. 라벨 정의에 영향 |
| 분봉 룰 부재 시 | KR은 분봉으로 false positive ↓. NASDAQ 도입 보수적 진행 |
| 사용자 시차 매매 한계 | KST 22:30~05:00 알림 → 매수 즉시 반응 어려움. "검토 모드" 옵션 검토 |
| yfinance 일봉 안정성 | pykrx보다 가끔 split 오류, missing day. outcome 평가 robust 처리 필요 |
| 동시 매매 가능성 | 카카오페이증권 해외주식 매매 환경 사용자 확인 필요 |

---

## 📋 별도 세션 시작 절차

```
mint 프로젝트 NASDAQ 확장 작업 진행합니다.

먼저 다음 문서 순서로 읽어주세요:
1. mint/HANDOFF_NASDAQ.md (본 문서) — Stage 1~3 작업 분해
2. mint/OPERATION_WEEK1.md — 현재 KR 운영 상태 (5/22~28)
3. mint/CLAUDE.md 「픽업 가이드」
4. mint/REVIEW_CURSOR.md 끝부분 4차 검토 응답

핵심 컨텍스트:
- KR (KOSPI/KOSDAQ)은 Cloud Migration 완료, 5/24부터 GHA 자동 운영
- NASDAQ은 인프라/ML/regime/outcome 모두 미흡 — 본 문서 Stage 1~3 따라 보강
- 사용자 결정 대기 사항 4개 (ML 전략 / 분봉 / 진입 시점 / 운영 의향)
  → 본 세션에서 먼저 합의 후 작업 시작

작업 git base: HEAD (main 최신).
```

---

## 🤔 진행 전 사용자 합의 필요 (4가지)

본 세션이 별도로 처리:

| 결정 사항 | 옵션 |
|---|---|
| **ML 모델** | (A) NASDAQ 전용 / (B) KR+US 통합 / (C) KR 모델 재사용 |
| **분봉 룰** | (1) OFF / (2) yfinance 1m / (3) Alpaca |
| **진입 시점** | (i) 즉시 Stage 1 / (ii) KR 1주 운영 후 / (iii) outcome 30건 후 |
| **운영 의향** | (a) 실 카카오페이 매매 / (b) 데이터 수집·조회만 / (c) KR 결과 보고 결정 |

각 항목에 사용자 답변 받은 후 Stage 1부터 코드 변경 시작.

---

## ⚙️ 변경 시 주의사항

### KR 운영 보호
- mint/data/models/mint_lgbm.joblib (KR 모델) 변경 X
- portfolio/db.py 스키마 마이그레이션은 backwards-compatible
- GHA scan-kr / daily-summary / outcomes workflow는 무수정
- Streamlit Cloud 대시보드는 KR + NASDAQ 모두 표시되게 보강 (KR-only가 깨지면 안 됨)

### 환경변수
- `MINT_WATCHLIST_SIZE` — KR/US 분리 검토 (`MINT_KR_WATCHLIST_SIZE`, `MINT_US_WATCHLIST_SIZE`)
- `MINT_US_SCAN=true` (이미 존재) — GHA에서 enable

### 사용자 결정 사안 변경 금지
- 1일 +3% 라벨 정의 (KR과 동일 유지 — 비교 가능성)
- max_position_pct 20% / max_daily_buys 5건 (KR과 동일)

### commit message 패턴
- `feat(us): ...` — NASDAQ 신규 기능
- `feat(us,ml): ...` — ML 관련
- `feat(us,gha): ...` — workflow 관련

---

## 📊 예상 결과

| 지표 | KR baseline (5/19c) | NASDAQ 목표 |
|---|---|---|
| 학습 샘플 | 21,822 | 25,000+ (200종 × 730일 × 라벨 분포) |
| Val AUC | 0.582 | ≥ 0.55 |
| 임계값 0.60 일평균 | 1.3건 | 1~3건 |
| Precision @ 0.60 | 0.79 | ≥ 0.70 |
| 운영 일평균 (분봉 ON) | 0~2건 | 0~3건 |

**달성 조건**: 시범 운영 1주 후 outcome 10건+ 누적 + val precision 재현률 70%+

---

## 🔗 관련 파일 (변경/신규 예상)

```
변경:
  mint/data/universe.py            (NASDAQ 동적 워치리스트)
  mint/engine/market_regime.py     (NASDAQ regime 매핑)
  mint/engine/signals/rule_scanner.py (NASDAQ dynamic exit)
  mint/portfolio/db.py             (outcome 평가 NASDAQ 분기)
  mint/notifier/__init__.py        (currency 분기)
  mint/engine/training.py          (NASDAQ 학습 분기)
  mint/engine/models/lgbm.py       (시장별 모델 로더)
  .github/workflows/scan-us.yml    (cron 활성화)
  mint/dashboard/app.py            (NASDAQ regime 카드)

신규:
  mint/data/models/mint_lgbm_us.joblib (NASDAQ 학습 모델)
  mint/engine/signals/minute_rule_us.py (선택, yfinance 분봉)
```

---

*본 문서는 2026-05-24 작성. NASDAQ 작업이 완료되면 본 파일 `완료` 표시 + OPERATION_WEEK1.md / CLAUDE.md 갱신.*
