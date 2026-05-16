# Mint 프로젝트 — 핸드오프 / 결정 기록

> **마지막 업데이트**: 2026-05-17 (Claude — Step 2b/2c/3b/4/7 + 동적 워치리스트 + LightGBM)
> **다음 세션 픽업 시**: 아래 [🔁 다음 세션 픽업 가이드](#-다음-세션-픽업-가이드) 부터 읽으세요.
> **Cursor 변경 이력**: `CURSOR.md`

---

## 🔁 다음 세션 픽업 가이드 (2026-05-17 → 2026-05-18 이후)

### 한 줄 요약
**LightGBM Step 3b까지 코드는 완성. 1회 학습 결과 AUC 0.528 = 노이즈 수준. 데이터 확대가 필수인데 KRX cross-sectional API 장애로 동적 워치리스트가 일시 막힘.**

### 어디까지 왔나
- ✅ Step 1, 2, 2b(kis_client), 2c(us_client), 3b(LightGBM), 4(exit_strategy), 7(backtest)
- ⚠️ Step 3b 학습은 **돌렸지만 결과가 약함** — 아래 학습 결과 기록 참조
- ⏳ Step 5, 6 (알림톡), 8 미착수

### 무엇이 막혔나
1. **KRX 데이터 시스템 장애** (2026-05-17 발생) — `Service unavailable` HTML 응답
   - `pykrx.stock.get_market_cap_by_ticker`, `get_market_ohlcv_by_ticker`, `get_market_ticker_list` 모두 `Expecting value: line 16 column 3` 에러
   - 개별 종목 일봉(`get_market_ohlcv_by_date`)은 다른 엔드포인트라 **정상**
   - `FinanceDataReader.StockListing` 도 같은 KRX 엔드포인트 사용 → 함께 실패
   - 복구 확인 명령: `python -c "from pykrx import stock; print(stock.get_market_cap_by_ticker('20260515', market='KOSPI').head())"`

### 사용자가 원하는 다음 방향 (2026-05-17 명시)

**모두 동시 진행 의향.** 우선순위는 사용자와 재확인.

1. **데이터 양 확대 (필수)** — 현재 20종목×1년=4617샘플. ML에 너무 적음.
   - KRX 복구 후 `--watchlist-size 100`으로 재학습 (이미 인프라 준비됨, [data/universe.py](data/universe.py))
   - 또는 curated 하드코딩 fallback 리스트 (~60종목) 추가 — 사용자가 보류 선택했었음 (KRX 복구 우선)

2. **1일 +3% 전략 재검토** — 단기 노이즈가 너무 커서 ML이 학습할 신호가 부족.
   - `max_hold_days` 1→3~5일로 늘리기
   - `target_return` / `stop_loss` 비대칭 해소 (현재 +3.5%/-2% → 백테스트에서 손절 79 vs 익절 37로 손절 우세)
   - `min_expected_return_1d` 임계값 재고
   - **중요**: 이 결정은 사용자 확정 사안이었으므로 변경 전 재확인 필요. memory `project_mint.md` 의 "+3% 24h" 룰도 함께 업데이트.

3. **피처 확장** — 현재 11개 (모두 기술적 지표). 더 다양한 신호 필요.
   - Bollinger Band 위치, OBV, gap (시가/전일종가), 시장 regime (KOSPI 지수 모멘텀), 섹터 모멘텀, 거래대금 백분위
   - 파일: [engine/features.py](engine/features.py) 확장

### 첫 행동 (새 세션 시작 시)
```bash
# 1) KRX 복구 확인
python -X utf8 -c "from pykrx import stock; df=stock.get_market_cap_by_ticker('20260518', market='KOSPI'); print(len(df) if df is not None else 'still down')"

# 2) 현재 모델/데이터 상태
ls mint/data/models/

# 3) CLAUDE.md 「로드맵」 + 「학습 결과 기록」 확인 후 사용자와 우선순위 합의
```

---

## 🎯 프로젝트 개요

**Mint** — 단기 주식 매매 **추천** 시스템 (자동 주문 아님)

### 수익 구조 (사용자 확정 — 2026-05-17 재검토 의향 있음)
- **24시간 내 +3%를 장담 못 하면 추천하지 않음** → `min_expected_return_1d` (시그널 **필터**)
- 실제 수익은 **높을수록 좋음** → `target_return` (+3.5% 익절 **권고**)
- 리스크 최소화: **포지션 크기·손실 한도**로 보수성 확보 (임계값만으로 X)
- 실매매: **카카오페이증권** / 시세·학습: **KIS + pykrx** (데이터 전용)

### 정책 (필수)
- **손절 -2%는 Mint가 보장하지 않음** — 권고만. 실행은 카카오페이 앱(지정가/손절 주문 권장)
- **ML 신뢰도 70%** — 현재 모델 AUC 0.528이라 켜면 시그널 거의 0건. 데이터 확대 후 재학습 권장.
- **기본 실행**: `python mint/main.py scan` (단발). 상시 스케줄러는 `MINT_DAEMON=1` + `daemon` 명령
- **US 야간 스캔**: 기본 **OFF** (`MINT_US_SCAN=false`)

---

## 🏗️ AI / 데이터 스택

| 단계 | 내용 | 상태 |
|------|------|------|
| Step 2 | `schema` → `krx_client` → `collector` → `rule_scanner` → SQLite | ✅ |
| Step 2b | `kis_client` (실시간 현재가, 토큰 캐시) | ✅ |
| Step 2c | `us_client` (yfinance) — NASDAQ 라우팅 | ✅ |
| Step 3a | 룰 고도화 | ✅ (rule_scanner 휴리스틱) |
| Step 3b | **LightGBM 단독** (캘리브레이션된 confidence) | ✅ 코드, ⚠️ 결과 약함 |
| 이후 | Qlib 팩터, LSTM — 데이터 부족으로 보류 | - |

---

## 📂 코드 구조 (2026-05-17 기준)

```
mint/
├── main.py                        # scan | catch-up | daemon | backtest | train
├── config/
│   ├── settings.py                # SignalConfig + OperationConfig (+watchlist_size)
│   └── markets.py                 # KOSPI/KOSDAQ/NASDAQ static watchlist (10/10/15)
├── data/
│   ├── schema.py                  # ✅ canonical OHLCV
│   ├── krx_client.py              # ✅ pykrx 일봉 + stdout silence
│   ├── kis_client.py              # ✅ 현재가 + stale 판정 + 토큰 캐시
│   ├── us_client.py               # ✅ yfinance
│   ├── universe.py                # ✅ 동적 워치리스트 (시총 상위 N) + JSON 캐시 24h
│   └── collector.py               # ✅ 시장별 라우팅 (n 인자 지원)
├── engine/
│   ├── features.py                # ✅ 11개 피처 (ret/vol/atr/rsi/ma/high)
│   ├── backtest.py                # ✅ 룰 시뮬레이션 백테스트
│   ├── training.py                # ✅ 데이터셋 빌드 + LightGBM 학습 + isotonic
│   ├── models/lgbm.py             # ✅ TrainedModel + save/load + 캐시
│   └── signals/
│       ├── rule_scanner.py        # ✅ 룰 + ML 필터 통합
│       └── exit_strategy.py       # ✅ TARGET/STOP/TIME/HOLD 권고
├── portfolio/db.py                # ✅ v2 스키마 + 체결가 기준 target/stop 재계산
├── dashboard/app.py               # ✅ 시그널 STALE 배지 + 포지션 매도 권고 박스
├── notifier/                      # ⏳ Step 6 (알림톡 미승인)
└── tests/
    ├── test_rule_scan.py
    ├── test_exit_strategy.py
    └── test_features.py
```

---

## 🛣️ 로드맵

- [x] Step 1: 구조 + 대시보드 뼈대
- [x] Step 2: KR E2E (schema → krx → rule scan → DB → 대시보드 체결)
- [x] Step 2b: `kis_client` (현재가 + stale 판정, 토큰 캐싱)
- [x] Step 2c: `us_client` (yfinance) + NASDAQ 룰 스캔 라우팅
- [x] Step 3b: LightGBM + isotonic calibration — **결과 약함, 재학습 필요**
- [x] Step 4: `exit_strategy` + `catch-up` 권고 + 대시보드 표시
- [ ] Step 5: portfolio manager (현재는 db.py 단독, 분리 안 해도 무방)
- [ ] Step 6: 카카오 알림톡 (채널·템플릿 **미승인** — 보류)
- [x] Step 7: 룰 백테스트
- [ ] Step 8: 페이퍼 트레이딩

### 동적 워치리스트 (2026-05-17 추가)
- [x] `data/universe.py` — pykrx 시총 상위 N 추출 + JSON 캐시 24h + 정적 폴백
- [x] CLI: `python mint/main.py train --watchlist-size 100`
- [x] env: `MINT_WATCHLIST_SIZE=100`
- [ ] 실제 100종목 재학습 — **KRX 장애로 차단됨**

---

## 📊 학습 결과 기록

| 일자 | 워치리스트 | 기간 | max_hold | 샘플 | Pos rate | Val AUC | Val LogLoss | 비고 |
|------|------------|------|----------|------|----------|---------|-------------|------|
| 2026-05-17 | 20 (static) | 365d | 1d | 4,617 | 0.465 | **0.528** | 0.6860 | 노이즈 수준. Best iter 7. |

**해석**: AUC 0.528은 거의 무작위(0.5). 1일 예측의 본질적 노이즈 + 데이터 부족(20종목)이 주원인. 임계값 0.70으로 ML 필터 켜면 시그널 0건. 데이터 확대 + 전략 재검토 필요.

---

## ✅ 사용자 결정 (최신)

| 날짜 | 결정 | 비고 |
|------|------|------|
| 2026-05-16 | +3% 24h 필터, 카카오페이 수동 매매, KIS 데이터 전용 | [[user-trading-setup]] |
| 2026-05-16 | 알림톡(미승인) / Alpaca·Polygon(US) / PC 간헐 실행 | [[project-mint-decisions]] |
| 2026-05-17 | 체결가 기준 target/stop **항상** 재계산 (시그널 ref_price 무시) | [portfolio/db.py:264](portfolio/db.py:264) |
| 2026-05-17 | exit_strategy `STOP_LOSS`는 **advisory** (CONSIDER_SELL), `TARGET`만 SELL_NOW | [engine/signals/exit_strategy.py](engine/signals/exit_strategy.py) |
| 2026-05-17 | **+3%/1d 전략은 재검토 후보** (ML 결과 보고) | 다음 세션에서 사용자와 확정 |

---

## 🚀 실행 방법

```bash
# 1) 의존성 (최소 — 학습 제외)
pip install pandas pykrx yfinance streamlit plotly apscheduler requests

# 2) KR 시그널 스캔 (단발)
python mint/main.py scan

# 3) PC 다시 켰을 때 — stale 만료 + 보유 포지션 매도 권고
python mint/main.py catch-up

# 4) 룰 백테스트
python mint/main.py backtest --days 180
python mint/main.py backtest --markets KOSPI KOSDAQ NASDAQ --days 365

# 5) LightGBM 학습 (추가 의존성: pip install lightgbm scikit-learn joblib finance-datareader)
python mint/main.py train --days 365                          # static 20종목
python mint/main.py train --days 365 --watchlist-size 100     # KRX 복구 시 시총 상위 100
# 출력: AUC, Pos rate, 모델/데이터셋 경로

# 6) 대시보드
streamlit run mint/dashboard/app.py
```

---

## 🔑 환경변수 (.env.example 참고)

```bash
MINT_DB_PATH=mint/data/mint.db
MINT_SIGNAL_VALID_MIN=30
MINT_SIGNAL_DEDUP_H=4
MINT_US_SCAN=false

# 워치리스트
MINT_WATCHLIST_SIZE=              # 비우면 static 10. 100 등 지정 시 동적 (KR만)

# ML
MINT_USE_ML_CONFIDENCE=false      # true면 LightGBM 확률 필터
MINT_MIN_ML_CONFIDENCE=0.70       # P(win) 임계값
MINT_MODEL_PATH=mint/data/models/mint_lgbm.joblib

# 외부
KIS_APP_KEY=                      # 없어도 동작 (None 폴백)
KAKAO_TEMPLATE_ID=                # Step 6 (미승인)
MINT_DAEMON=0
```

---

## 💬 다음 세션 시작 프롬프트 예시

```
mint/CLAUDE.md 「다음 세션 픽업 가이드」 섹션 읽고 시작해줘.
오늘은:
1. KRX 복구 됐는지 확인
2. 복구됐으면 --watchlist-size 100으로 재학습
3. 안 됐으면 max_hold_days 3으로 재학습 (1일 전략 재검토)
4. 결과 보고 피처 확장 여부 결정
이 순서로 가자.
```
