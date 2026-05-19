# Mint 프로젝트 — 핸드오프 / 결정 기록

> **마지막 업데이트**: 2026-05-18 (Claude — Naver 폴백 + 100종목 + 16피처 → AUC 0.596 / Confidence·필터 검증(0.70 매일 6.4개 precision 0.78) / 카카오톡 알림+하트비트+일일요약 / Windows 작업 스케줄러 자동화)
> **다음 세션 픽업 시**: 아래 [🔁 다음 세션 픽업 가이드](#-다음-세션-픽업-가이드) 부터 읽으세요.
> **Cursor 변경 이력**: `CURSOR.md`

---

## 🔁 다음 세션 픽업 가이드 (2026-05-19 이후)

### 한 줄 요약
**100종목·16피처 LightGBM(AUC 0.596) + 카카오톡 자동 알림(하트비트/시그널/매도권고/일일요약) + 평일 작업 스케줄러로 자동 운영. 필터 검증(룰 only 0.42 → ML 0.70 0.78 / ML 0.75 0.99)으로 ML 필터가 실제로 효과 있음 확인. 사용자는 데이터는 풍부하길 원하고 일봉 한계 아쉬워함 — 다음 카드 1순위: KIS 현재가로 일봉 시그널 신선도 검증(저비용 분봉 흉내), 2순위: KIS 분봉 룰 신설.**

### 어디까지 왔나
- ✅ Step 1, 2, 2b(KIS), 2c, 3a, 3b, 4, 6(카카오톡 나에게보내기), 7
- ⏳ Step 5(분리 미실시 — db.py 단독으로 충분), 8(페이퍼 트레이딩) 미착수
- ✅ **2026-05-18 작업 일체**: 픽업 가이드 + 학습 결과 기록 + 사용자 결정 표 참조

### 5/18 신규 추가/검증 사항 요약
| 항목 | 결과 | 코드/문서 위치 |
|---|---|---|
| Naver Finance 폴백 (시총 랭킹) | KRX 인증 우회. KOSPI/KOSDAQ 각 100종목 정상 fetch | [data/universe.py:_fetch_top_n_naver](data/universe.py) |
| 100종목 재학습 | AUC 0.528 → 0.594 (샘플 ×10.3, Best iter 7→85) | 학습결과 5/18b |
| 피처 11→16 | AUC +0.002 (gap_pct만 기여, 나머지 4개는 중복) | [engine/features.py](engine/features.py) |
| Confidence 분포 검증 | val 9,488: p99 0.702, 0.70 매일 6.4개·precision 0.78 | 학습결과 5/18d |
| 필터 날카로움 검증 | 룰 only=0.42, 룰+ML 0.70=0.78, 0.75=0.99, Top-1/day=0.98 | 학습결과 5/18e |
| 카카오톡 "나에게 보내기" | 시그널/매도권고 발송 + 토큰 자동 refresh | [notifier/kakao.py](notifier/kakao.py), [setup_kakao.py](notifier/setup_kakao.py) |
| 하트비트 + 일일 요약 | 오늘 첫 scan에서 1통, 15:35 별도 명령 1통 | [notifier/__init__.py](notifier/__init__.py) `maybe_send_heartbeat`, `send_daily_summary` |
| `daily-summary` 명령 | `python mint/main.py daily-summary` | [main.py:cmd_daily_summary](main.py) |
| Windows 작업 스케줄러 | 사용자 셋업 완료 (08:30 + 10분 간격, 평일) | 환경변수: User scope |

### 다음에 검토할 카드 (우선순위)
1. ~~**A. 일봉 시그널 + KIS 현재가 신선도 검증**~~ ✅ 2026-05-19 완료
   - [notifier/__init__.py `_freshness_line`](notifier/__init__.py) — 카톡 메시지에 KIS 현재가 + drift 마커
   - 위로 stale → ⚠️ 엔트리 늦음, 아래로 stale → 💡 더 좋은 진입, 그 사이 → ✓ 신선
   - 임계값: `MINT_REF_STALE_PCT` (기본 0.008 = 0.8%)
   - KIS 키 없으면 graceful no-op (기존 메시지 유지)
2. **B. KIS 분봉 룰 신설 (1~2주 작업)** — 진정한 장중 시그널. **1순위로 승격.**
   - KIS endpoint: `inquire-time-itemchartprice` (1/3/5/10/15/30/60분봉)
   - 룰 후보: 5분봉 거래량 spike(20봉 평균 ×3), 5/10일선 돌파, 갭상승 후 보합/상승
   - 일봉 룰과 AND 조건으로 결합 → 신호 폭 ↓ 정밀도 ↑
   - 분봉 데이터 캐싱·라우팅·collector 라우팅 새로 필요
3. **C. 진짜 독립 신호** — KOSPI/KOSDAQ 지수 regime, 섹터 모멘텀, 수급. 단일 종목 파생은 5/18c에서 포화 확인.
4. **D. 페이퍼 트레이딩 (Step 8)** — `MINT_USE_ML_CONFIDENCE=true` + `MINT_MIN_ML_CONFIDENCE=0.70` 로 1개월 운영, 실 win rate 측정.
5. **E. 데이터 확대** — 200종목 (Naver 페이지 4) or 730일.
6. **F. 중복 피처 4개(bb/obv/turnover/regime_trend) 정리** — AUC 유지하면서 단순화.
7. **G. target/stop 대칭화 검토** — 사용자 확정사항 변경 필요.

### 다음 세션 시작 시 첫 행동
```powershell
# 1) 현재 상태 점검
git log -5 --oneline
ls mint/data/models/

# 2) 사용자 의사 확인:
#    "A(현재가 검증) / B(분봉 룰) / D(페이퍼 운영부터) 중 무엇 먼저?"
#
# 3a) A 선택 시:
#    engine/signals/rule_scanner.py 에 KIS fetch + stale 페널티 추가
#    notifier 메시지 포맷에 STALE 마커 추가
#
# 3b) B 선택 시:
#    data/kis_client.py 에 get_minute_bars() 추가
#    config/settings.py 에 분봉 룰 임계값
#    engine/signals/ 에 minute_rule.py 신규
#
# 3c) D 선택 시:
#    daily-summary 카톡 받으면서 1개월 누적
#    실제 win rate vs 모델 예상치 비교 보고서
```

### Windows 작업 스케줄러 — 일일 요약 트리거 추가 (사용자 작업)
이미 등록한 `Mint 시그널 스캔` 외에 별도로:

1. 작업 스케줄러 → **작업 만들기**
2. [일반] 이름: `Mint 일일 요약`, 가장 높은 권한
3. [트리거] 매주 · 월·화·수·목·금 · **15:35:00** · 1주마다
4. [동작] 프로그램: `C:\Python313\python.exe`, 인수: `-X utf8 mint\main.py daily-summary`, 시작 위치: `C:\Users\USER\OneDrive\바탕 화면\workspace`
5. [조건] 절전 모드에서 깨우기 체크
6. [설정] 놓친 작업 빨리 시작, 새 인스턴스 시작 안 함

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
- **ML 신뢰도 70%** — 100종목 모델(AUC 0.596) 기준 val set에서 매일 평균 6.4개 시그널, precision 0.78, lift 1.88×. 임계값 0.70 합리적. 더 보수적으로 0.75 가면 매일 1.8개·precision 0.988 (trade-off).
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
├── notifier/
│   ├── __init__.py                # ✅ notify_buy_signals / notify_exit_advices
│   ├── kakao.py                   # ✅ 카카오톡 '나에게 보내기' + 토큰 자동 refresh
│   └── setup_kakao.py             # ✅ 1회 인가 → 토큰 발급 헬퍼
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
- [x] Step 6: 카카오톡 "나에게 보내기" 알림 (2026-05-18) — 비즈 알림톡은 여전히 보류, 개인용 talk_message scope로 우회
  - `notifier/kakao.py` + `notifier/__init__.py` + `notifier/setup_kakao.py`
  - scan/catch-up 명령 자동 통합. 토큰 미설정 시 자동 no-op
- [x] Step 7: 룰 백테스트
- [ ] Step 8: 페이퍼 트레이딩

### 동적 워치리스트 (2026-05-17 추가, 2026-05-18 Naver 폴백)
- [x] `data/universe.py` — 시총 상위 N 추출 + JSON 캐시 24h + 정적 폴백
- [x] **2026-05-18**: Naver Finance 스크래핑 1차 소스 (`_fetch_top_n_naver`) — KRX 인증 불필요
- [x] pykrx는 `KRX_ID`/`KRX_PW` 환경변수 있을 때만 시도
- [x] CLI: `python mint/main.py train --watchlist-size 100`
- [x] env: `MINT_WATCHLIST_SIZE=100`
- [x] **100종목 재학습 완료** (5/18, 47,440 샘플, AUC 0.594)

---

## 📊 학습 결과 기록

| 일자 | 워치리스트 | 기간 | max_hold | 샘플 | Pos rate | Val AUC | Val LogLoss | Best iter | 비고 |
|------|------------|------|----------|------|----------|---------|-------------|-----------|------|
| 2026-05-17 | 20 (static) | 365d | 1d | 4,617 | 0.465 | 0.528 | 0.6860 | 7 | 노이즈 수준. |
| 2026-05-18a | 20 (static) | 365d | 3d | 4,636 | 0.441 | 0.538 | 0.6793 | 3 | 1d→3d 확장만으로는 효과 없음. |
| 2026-05-18b | 100 (Naver) | 365d | 1d | 47,440 | 0.443 | **0.594** | 0.6608 | 85 | 데이터 ×10.3 → AUC +0.066. 노이즈 탈출. (11 피처) |
| 2026-05-18c | 100 (Naver) | 365d | 1d | 47,440 | 0.443 | **0.596** | 0.6598 | 59 | **+5 피처**(bb_position, obv_slope, gap_pct, regime_trend, turnover_pct60). AUC +0.002 — 의미 없음. |

**해석**:
- 5/17→5/18a: holding window 1d→3d 변경만으로는 AUC 노이즈 범위(+0.010). 보유기간이 문제는 아님.
- 5/18a→5/18b: 워치리스트 20→100, 샘플 ×10.3 → AUC 0.594, Best iter 85. 모델이 실제로 수렴 — 신호는 있었으나 데이터 부족이 진짜 원인.
- 5/18b→5/18c: 피처 11→16. AUC +0.002 = 노이즈. **5개 중 gap_pct(gain 5.9%) 하나만 실질 기여**. 나머지 4개(bb_position, obv_slope, turnover_pct60, regime_trend)는 기존 피처(dist_ma20, vol_ratio_*)와 정보 중복.

### 5/18c 학습된 모델 피처 중요도 (gain 기준 Top 7)
| 순위 | 피처 | Gain % |
|---|---|---|
| 1 | rsi_14 | 20.7 |
| 2 | atr_pct | 19.6 |
| 3 | dist_ma5 | 9.7 |
| 4 | ret_1d | 6.7 |
| 5 | **gap_pct** ⭐ | 5.9 |
| 6 | dist_ma20 | 4.9 |
| 7 | vol_ratio_5d | 4.3 |

→ 단일 종목의 가격/거래량 파생 지표는 거의 포화. 다음 의미 있는 도약은 **진짜 독립 신호**(시장 지수 regime, 섹터, 외국인/기관 수급, 뉴스) 또는 **추가 데이터 양**(200종목·730일).

### 5/18e 필터 날카로움 검증 (val n=9,488, 49일)
| 운영 모드 | 시그널/일 | Win rate | Avg/trade* | Lift |
|---|---|---|---|---|
| 룰 only (ML off) | many | 0.416 | +0.29% | 1.00× |
| 룰 + ML 0.70 | 6.4 | **0.780** | +2.29% | 1.88× |
| 룰 + ML 0.75 | 1.8 | **0.988** | +3.44% | 2.38× |
| Top-1/day | 1 | 0.980 | +3.40% | 2.36× |
| Top-3/day | 3 | 0.823 | +2.55% | 1.98× |

*win=+3.5%/loss=-2% 단순 가정, 슬리피지 미반영.

**핵심**: 룰 only는 win 0.416(<0.5)으로 사실상 무작위 — **ML 필터가 진짜 일하고 있음**. 0.75는 precision 0.988이지만 86 샘플밖에 안 돼 overfitting 위험. 0.70이 sweet spot. **다른 시기 데이터로 재검증 필요** (val 49일이 학습 데이터 직후 시기).

### 5/18d Confidence 분포 (val n=9,488)
| Metric | 값 |
|---|---|
| mean / std | 0.416 / 0.102 |
| p50 / p90 / p99 | 0.422 / 0.465 / 0.702 |

| 임계값 | 통과 | 비율 | Precision | Lift | 운영 환산 |
|---|---|---|---|---|---|
| 0.50 | 436 | 4.6% | 0.729 | 1.75× | — |
| 0.65 | 314 | 3.3% | 0.780 | 1.88× | — |
| **0.70** | **314** | **3.3%** | **0.780** | **1.88×** | **매일 6.4개, 49/49일 시그널** |
| 0.75 | 86 | 0.9% | 0.988 | 2.38× | 매일 1.8개 |

→ 5/18c 모델은 0.70 임계값에서 **매일 시그널이 나오고** precision 0.78. 옛 메모(0.70 = 시그널 0건)는 5/17 모델 기준 — 갱신 완료. 더 보수적이면 0.75 권장 (precision 0.988, 거의 확정 win).

---

## ✅ 사용자 결정 (최신)

| 날짜 | 결정 | 비고 |
|------|------|------|
| 2026-05-16 | +3% 24h 필터, 카카오페이 수동 매매, KIS 데이터 전용 | [[user-trading-setup]] |
| 2026-05-16 | 알림톡(미승인) / Alpaca·Polygon(US) / PC 간헐 실행 | [[project-mint-decisions]] |
| 2026-05-17 | 체결가 기준 target/stop **항상** 재계산 (시그널 ref_price 무시) | [portfolio/db.py:264](portfolio/db.py:264) |
| 2026-05-17 | exit_strategy `STOP_LOSS`는 **advisory** (CONSIDER_SELL), `TARGET`만 SELL_NOW | [engine/signals/exit_strategy.py](engine/signals/exit_strategy.py) |
| 2026-05-17 | **+3%/1d 전략은 재검토 후보** (ML 결과 보고) | 다음 세션에서 사용자와 확정 |
| 2026-05-18 | KRX 인증 도입 우회 → Naver Finance 스크래핑 추가 | [data/universe.py:_fetch_top_n_naver](data/universe.py) |
| 2026-05-18 | 데이터 확대가 우선 (vs holding window 조정) — 100종목 학습으로 AUC 0.528→0.594 검증 | 학습 결과 기록 참조 |
| 2026-05-18 | 알림 채널: **카카오톡 나에게 보내기** (talk_message scope). 비즈 알림톡은 계속 보류. | [notifier/kakao.py](notifier/kakao.py) |
| 2026-05-18 | ML 임계값 0.70 유지 (precision 0.78, 매일 6.4개) — 더 보수적 원하면 0.75 권장 | 학습 결과 기록 5/18d |
| 2026-05-18 | KIS 키 없어도 시스템 동작 — 장중 매도/STALE 정밀도만 손해. 사용 패턴 정해진 뒤 신청 결정 | [data/kis_client.py](data/kis_client.py) |
| 2026-05-19 | 종목명 fetch에 Naver 폴백 (pykrx 인증 영향) | [data/krx_client.py:get_stock_name](data/krx_client.py) |
| 2026-05-19 | 카톡 메시지 표기 정직성 개선 — "예상" → "모멘텀", action/reason 한국어 | [notifier/__init__.py](notifier/__init__.py) |
| 2026-05-19 | 카드 A 완료: KIS 현재가 신선도 마커 (⚠️/💡/✓) 카톡에 추가 | [notifier/__init__.py:_freshness_line](notifier/__init__.py) |

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

# 7) 카카오톡 '나에게 보내기' 알림 1회 설정 (개인용)
#    카카오 디벨로퍼스 앱 만들고 KAKAO_REST_API_KEY 설정 후:
python mint/notifier/setup_kakao.py
#    이후 scan/catch-up 명령 시 자동으로 카톡 발송.
#    토큰은 mint/data/.kakao_token.json 에 캐시되고 만료 시 자동 refresh.
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
KIS_APP_KEY=                      # 없어도 동작. 장중 매도/STALE 정밀도용 (선택)
KIS_APP_SECRET=

# 카카오톡 나에게 보내기 (개인용 알림)
KAKAO_REST_API_KEY=               # 카카오 디벨로퍼스 앱 REST API 키
KAKAO_REDIRECT_URI=https://localhost  # 카카오 콘솔 등록 URL과 동일해야 함
KAKAO_TOKEN_PATH=mint/data/.kakao_token.json
MINT_NOTIFY_ENABLED=true
MINT_NOTIFY_MAX_PER_RUN=5         # 1회 스캔당 개별 발송 최대 건수

# (보류) 비즈 알림톡
KAKAO_TEMPLATE_ID=

MINT_DAEMON=0
```

---

## 💬 다음 세션 시작 프롬프트 예시

### (a) 작업 이어가기 — 분봉/현재가 검증으로 필터 더 날카롭게
```
mint/CLAUDE.md 「다음 세션 픽업 가이드」 섹션 먼저 읽어줘.
오늘은 1순위 카드 A (일봉 + KIS 현재가 신선도 검증) 진행하자.
- rule_scanner에서 시그널 생성 직후 KIS 현재가 fetch
- drift > stale_pct면 메시지에 ⚠️ STALE 마커 + ML score 옵션
- 카톡 메시지 포맷에 STALE 표기 추가
- 테스트 후 CLAUDE.md 갱신 + git commit
```

### (b) 분봉 룰 신설로 진정한 장중 시그널
```
mint/CLAUDE.md 픽업 가이드 읽어줘.
2순위 카드 B (KIS 분봉 룰) 시작하자.
- data/kis_client.py 에 get_minute_bars(ticker, period='5m', count=120) 추가
- config/settings.py 에 분봉 룰 임계값(거래량 spike 배수, 이평선 등)
- engine/signals/minute_rule.py 신규 — 5분봉 거래량 폭증 + 이평선 돌파 룰
- 일봉 룰과 AND 조건으로 결합 (먼저 일봉 통과한 종목만 분봉 평가)
- 백테스트가 분봉엔 안 되니까 일단 룰만 + 카톡으로 후보 받아보기
```

### (c) 페이퍼 트레이딩 운영 시작
```
mint/CLAUDE.md 픽업 가이드 읽어줘.
카드 D 페이퍼 트레이딩 시작. 1개월 운영 + 결과 분석 인프라:
- ML 필터 0.70 켠 상태로 매일 시그널 자동 발송 중 (작업 스케줄러)
- portfolio/db.py 에 paper_position 자동 가상매수/매도 로직 (체결가 = 다음날 시가 가정)
- 일일 요약 카톡에 가상 누적 수익률 추가
- 4주 후 실제 win rate vs 모델 예상치(0.78) 비교 보고서
```
