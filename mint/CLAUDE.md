# Mint 프로젝트 — 핸드오프 / 결정 기록

> **마지막 업데이트**: 2026-05-20 (5/20 운영 첫날 약세장 0건 → 운영 가시성 강화 a/b/c + 대시보드 리프레시 d/e/f/g 완료. Cloud Migration 가이드 작성. Cursor 3차 검토 요청 대기.)
> **다음 세션 픽업 시**: 아래 [🔁 다음 세션 픽업 가이드](#-다음-세션-픽업-가이드) 부터 읽으세요.
> **Cursor 변경 이력**: `CURSOR.md` · **Cursor 검토 결과**: `REVIEW_CURSOR.md` · **Cloud 이전 가이드**: `CLOUD_MIGRATION.md`

---

## 🔁 다음 세션 픽업 가이드 (2026-05-21 이후)

### 한 줄 요약
**5/20 운영 첫날 약세장(KOSPI -0.86%, KOSDAQ -2.61%)으로 시그널 0건 — 시스템 보수적 회피 성공. 운영 가시성(시장지수/funnel/미드데이) + 대시보드 통합 리프레시 완료. Cloud Migration 가이드 작성. Cursor 3차 검토 요청 대기 중 (REVIEW_CURSOR.md 끝 부분).**

### 첫 행동 (다음 세션 시작 시)
```powershell
# 1) 어제~오늘 시그널 + outcome 조회
python -X utf8 mint\main.py outcomes
python -X utf8 -c "import sys; sys.path.insert(0,'mint'); from portfolio.db import get_conn; from datetime import datetime, timedelta;
since = (datetime.now() - timedelta(days=3)).isoformat();
with get_conn() as c:
    rows = c.execute('SELECT id,ticker,name,status,outcome,expiry_reason,created_at FROM signals WHERE created_at >= ? ORDER BY created_at DESC', (since,)).fetchall();
    for r in rows: print(dict(r))"

# 2) Cursor 3차 검토 결과가 REVIEW_CURSOR.md에 있는지 확인
#    있으면 그 권고 사항 P1/P2... 식으로 분류해서 사용자 승인 받기

# 3) 사용자 피드백 — 5/21 시그널 받았는지, 어떤 메시지 도착했는지, 매수까지 갔는지
```

### 5/20까지 작업한 것 (현재 운영 상태)
- ✅ 운영 안정 (Cursor 검토 P1~P3 반영, 5/19)
- ✅ 데이터 확대 카드 E (200종목 × 730일, AUC 0.582)
- ✅ 운영 가시성 카드 a/b/c (시장 지수, 스캔 funnel, 미드데이 ping)
- ✅ 대시보드 통합 리프레시 d/e/f/g
- ✅ Cloud Migration 가이드 (`CLOUD_MIGRATION.md`)

### 사용자 운영 환경 (Claude 확인 완료)
- `MINT_USE_ML_CONFIDENCE=true`, `MINT_USE_MINUTE_RULE=true`, `MINT_MIN_ML_CONFIDENCE=0.60`
- Windows 작업 스케줄러: `Mint Signal Scan` 1개 (평일 08:30~15:20 10분 간격)
- ⏳ **사용자 잔여 작업**: `Mint 일일 요약` (15:35) 트리거 미등록 — 이거 등록해야 outcome 자동 평가 + win rate 누적 동작

### 다음 카드 우선순위
1. **운영 데이터 1~2주 수집** — 진짜 평상시 시그널 패턴 보기
2. **Cursor 3차 검토 응답 반영** — REVIEW_CURSOR.md 새 섹션 보고 P-항목 분류
3. **카드 C** — 시장 regime/섹터 독립 신호 (AUC 0.582 추가 도약)
4. **카드 D** — 페이퍼 트레이딩 인프라 (실제 win rate 측정)
5. **카드 m** — outcome 누적 후 자동 재학습 (1~2주 후)
6. **Cloud Migration** — `CLOUD_MIGRATION.md` 가이드 따라 단계별 진행 (4~8시간). 트리거: PC 24/7 불편 or NASDAQ 야간 활성화 필요 시.

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
2. ~~**B. KIS 분봉 룰 + 만료 노티 + Outcome 트래킹**~~ ✅ 2026-05-19 완료
   - **B1**: [engine/signals/minute_rule.py](engine/signals/minute_rule.py) — 거래량 spike + 단기 모멘텀 + 양봉 AND
     - 일봉 룰+ML 통과 종목만 분봉 fetch (호출 한도 안전)
     - 활성화: `MINT_USE_MINUTE_RULE=true` (기본 false)
   - **B2**: 시그널 만료 카톡 (TIME / TARGET_HIT / STOP_HIT) — scan/catch-up 시작 시 자동
     - [portfolio/db.py](portfolio/db.py): `expire_stale_signals`, `check_price_expiry`, `unnotified_expired_signals`, `mark_expiry_notified`
   - **B3**: Outcome 자동 평가 + 누적 win rate 일일 요약 표시
     - [portfolio/db.py](portfolio/db.py): `evaluate_pending_outcomes`, `get_outcome_stats`
     - `python mint/main.py outcomes` 단발 명령 또는 daily-summary 시 자동
     - **재학습 데이터 자동 축적** — 실 운영 데이터로 모델 개선 가능
   - KIS endpoint: `inquire-time-itemchartprice` (1/3/5/10/15/30/60분봉)
   - 룰 후보: 5분봉 거래량 spike(20봉 평균 ×3), 5/10일선 돌파, 갭상승 후 보합/상승
   - 일봉 룰과 AND 조건으로 결합 → 신호 폭 ↓ 정밀도 ↑
   - 분봉 데이터 캐싱·라우팅·collector 라우팅 새로 필요
3. **C. 진짜 독립 신호** — KOSPI/KOSDAQ 지수 regime, 섹터 모멘텀, 수급. 단일 종목 파생은 5/18c에서 포화 확인.
4. **D. 페이퍼 트레이딩 (Step 8)** — `MINT_USE_ML_CONFIDENCE=true` + `MINT_MIN_ML_CONFIDENCE=0.70` 로 1개월 운영, 실 win rate 측정.
5. **E. 데이터 확대** — 200종목 (Naver 페이지 4) or 730일.
6. **F. 중복 피처 4개(bb/obv/turnover/regime_trend) 정리** — AUC 유지하면서 단순화.
7. **G. target/stop 대칭화 검토** — 사용자 확정사항 변경 필요.

### 다음에 검토할 카드 (5/20 운영 시작 후 우선순위)

**상태**: 사용자 운영 시작 — ML 임계값 0.60 + 분봉 ON. Windows 작업 스케줄러 평일 08:30~15:20 10분 간격.
**남은 사용자 작업**: 작업 스케줄러에 **`Mint 일일 요약` 트리거 (15:35) 추가** — outcome 평가가 돌게 하는 핵심. (현재 미등록, CLAUDE.md 픽업 가이드의 단계 보면 됨)

1. **운영 데이터 수집 (즉시)** — 1~2주 운영하면서 outcome (WIN/LOSS/TIME_EXIT) DB에 자동 축적. 일일 요약 카톡으로 누적 win rate 확인. 모델 예상(precision 0.79)과 실제 격차 측정.
2. **카드 C — 진짜 독립 신호 (4~6h)** — KOSPI/KOSDAQ 지수 regime, 섹터 모멘텀. 데이터 확대(카드 E) 끝났으니 다음 도약 카드. AUC 0.582 → 0.6+ 가능성.
3. **카드 D — 페이퍼 트레이딩 인프라 (3~5h)** — 실제 매수 시뮬레이션 + 누적 수익률 일일 요약. Cursor #7 (outcome 일봉 기준 한계) 자연 해결.
4. **Cursor #6 — 분봉 룰 임계값 분포 검증 (2~3h)** — KIS 분봉 일주일치 fetch해서 vol_spike 3.0이 적절한지 분포 확인. 1~2주 운영 후 결과 보고 결정.
5. **카드 F — target/stop 대칭화 검토** — 사용자 결정 사안. 운영 outcome에서 LOSS 비율이 높으면 재고.
6. **outcome 누적 후 모델 재학습 (1~2주 후)** — 실 운영 분포 vs 백테스트 분포 비교. 가장 흥미로운 학습 시점.

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
- **ML 신뢰도 — 2026-05-19 카드 E 후**: AUC 0.582, 임계값 0.60에서 매일 1.3개·precision 0.79.
  - 임계값 0.60 = **매일 1.3개** (precision 0.79, lift 1.87×) — 디폴트 권장
  - 임계값 0.75 = 매일 0.9개 (precision 0.83) — 보수적
  - 분봉 ON이면 분봉까지 통과한 것만 카톡 → 실제는 1.3개의 일부
  - 진짜 도약은 **카드 C (시장 regime/섹터 등 독립 신호)** 또는 outcome 데이터로 재학습
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
| 2026-05-18c | 100 (Naver) | 365d | 1d | 47,440 | 0.443 | **0.596** | 0.6598 | 59 | **+5 피처**(bb_position, obv_slope, gap_pct, regime_trend, turnover_pct60). AUC +0.002 — 의미 없음. ⚠️ **5/19 수정 사항**: 학습 분포에 룰 외 시점이 섞여 있어 운영(룰+ML 통과)과 분포 mismatch. 5/18d/e 수치는 운영에서 재현 안 됨. |
| 2026-05-19a | 100 (Naver) | 365d | 1d | **6,267** | 0.419 | 0.551 | 0.6701 | 16 | **P1 학습-추론 정합 수정** — build_ticker_dataset에 룰 필터(expected/risk/vol) 추가. 데이터 ÷7.6로 줄어 AUC 하락(-0.045) 노이즈 근처. 진짜 운영 동작은 이 모델 기준. |
| 2026-05-19c | **200 (Naver)** | **730d** | 1d | **21,822** | 0.414 | **0.582** | 0.6689 | 39 | **카드 E: 데이터 ×3.5 확대 (정합 유지)**. AUC +0.031 회복, Best iter 16→39, 모델 안정성 ↑. 사용자 임계값 0.60에서 **일평균 1.3개·precision 0.79**. Top-1/day win 0.745. atr_pct 비중 22.9%로 1위, gap_pct 7.2% 신 피처 가치 확인. |

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

### 5/18e 필터 날카로움 (val n=9,488, 49일) — ⚠️ DEPRECATED
| 운영 모드 | 시그널/일 | Win rate | Avg/trade* | Lift |
|---|---|---|---|---|
| 룰 only (ML off) | many | 0.416 | +0.29% | 1.00× |
| 룰 + ML 0.70 | 6.4 | 0.780 | +2.29% | 1.88× |
| 룰 + ML 0.75 | 1.8 | 0.988 | +3.44% | 2.38× |
| Top-1/day | 1 | 0.980 | +3.40% | 2.36× |

⚠️ **이 수치는 학습-추론 분포 mismatch가 있는 5/18c 모델 기준이라 운영에서 재현 안 됨.** Cursor 검토(5/19) 발견. 정정된 P1 수치는 아래 5/19b 참조.

### 5/19b 필터 날카로움 (P1 모델, val n=1,254, 66일) — DEPRECATED by 5/19c
(데이터 부족 노출 단계)

### 5/19c 필터 날카로움 (카드 E 모델, val n=4,365, 94일)
| 운영 모드 | 일평균 | Precision | Lift |
|---|---|---|---|
| 룰 + ML 0.50 | 6.4 | 0.577 | 1.36× |
| 룰 + ML 0.55 | 2.4 | 0.686 | 1.62× |
| **룰 + ML 0.60** ⭐ | **1.3** | **0.792** | **1.87×** |
| 룰 + ML 0.65 | 1.3 | 0.792 | 1.87× |
| 룰 + ML 0.70 | 1.3 | 0.795 | 1.88× |
| 룰 + ML 0.75 | 0.9 | 0.828 | 1.95× |
| Top-1/day | 1 | 0.745 | 1.76× |
| Top-3/day | 3 | 0.620 | 1.46× |
| Top-5/day | 5 | 0.573 | 1.35× |

**해석**:
- 사용자 디폴트 **0.60에서 일평균 1.3개·precision 0.79·lift 1.87×** — 운영 가능 수준 도달
- 0.60~0.74 구간은 모두 동일 결과 (분포 plateau) — 0.60이 안전한 디폴트
- 보수적이면 0.75 (precision 0.83, 일평균 0.9개)
- 분봉 룰까지 ON이면 추가 필터 — 실제 카톡은 1.3개의 일부만 도달 (분봉 통과율 미검증)
- AUC 0.582는 여전히 낮은 절대치 — 다음 의미 있는 도약은 **카드 C (시장 regime/섹터/수급 같은 독립 신호)** 또는 **outcome 누적 후 실 분포 재학습**

### 5/19c 피처 중요도 (gain Top 7)
| 순위 | 피처 | gain % |
|---|---|---|
| 1 | atr_pct | 22.9 |
| 2 | rsi_14 | 11.4 |
| 3 | ret_1d | 8.7 |
| 4 | **gap_pct** ⭐ | 7.2 |
| 5 | dist_high60 | 6.3 |
| 6 | bb_position | 6.2 |
| 7 | ret_5d | 5.9 |

→ 데이터 늘면서 피처 분포가 더 골고루. atr_pct 절대 1위. gap_pct는 5/18c (5위 5.9%) → 5/19c (4위 7.2%) 로 가치 입증.

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
| 2026-05-19 | 카드 B1 완료: KIS 분봉 룰 신설 (거래량 spike + 단기 모멘텀 + 양봉) | [engine/signals/minute_rule.py](engine/signals/minute_rule.py) |
| 2026-05-19 | 카드 B2 완료: 시그널 만료 카톡 (TIME/TARGET_HIT/STOP_HIT) — '죽은 시그널 매수' 방지 | [portfolio/db.py:check_price_expiry](portfolio/db.py), [notifier:notify_expired_signals](notifier/__init__.py) |
| 2026-05-19 | 카드 B3 완료: 시그널 outcome 자동 평가 + 일일 요약에 누적 win rate | [portfolio/db.py:evaluate_pending_outcomes](portfolio/db.py) |
| 2026-05-19 | **Cursor 검토 P1 반영**: training.py에 룰 필터 추가 — 학습-추론 분포 정합. AUC 0.596 → 0.551 (현실 반영, 데이터 부족 노출) | [engine/training.py:build_ticker_dataset](engine/training.py) |
| 2026-05-19 | **Cursor 검토 P2 반영**: cmd_scan_us 만료 처리 추가, rule_scanner에 max_daily_buys 한도 적용 | [main.py:cmd_scan_us](main.py), [rule_scanner.run_rule_scan](engine/signals/rule_scanner.py) |
| 2026-05-19 | **Cursor 검토 P3 반영**: 매수 메시지 핵심 정보 위로 + 라인 단위 truncate (200자 안전) | [notifier/kakao.py:_truncate](notifier/kakao.py), [notifier/__init__.py:_format_buy_signal](notifier/__init__.py) |
| 2026-05-19 | **카드 E 완료**: 200종목 × 730일 학습 → AUC 0.551→0.582, 임계값 0.60 일평균 0.7→1.3 (운영 가능 수준) | 학습결과 5/19c |
| 2026-05-20 | **카드 a 완료**: KOSPI/KOSDAQ 지수 등락률 (Naver 모바일 API) — 일일 요약/하트비트/미드데이에 한 줄 추가 | [data/market_index.py](data/market_index.py) |
| 2026-05-20 | **카드 b 완료**: 스캔 funnel 통계 — 매 scan 단계별 통과 카운트 누적 → 일일 요약에 "평가 X → 모멘텀 Y → … → 시그널 Z" 표시 | [engine/signals/rule_scanner.py](engine/signals/rule_scanner.py), [notifier:accumulate_scan_stats](notifier/__init__.py) |
| 2026-05-20 | **카드 c 완료**: 미드데이 ping (12:00 한 번) — 약세장 등 시그널 0건 사유 자동 진단 | [notifier:maybe_send_midday_ping](notifier/__init__.py) |
| 2026-05-20 | **카드 d/e/f/g 완료**: 대시보드 통합 리프레시 — 시장지수+funnel+outcome trend(d), 보유 포지션 P&L 게이지(e), 모델 분석 페이지+confidence 슬라이더+feature importance(f), 모바일 친화 레이아웃(g) | [dashboard/app.py](dashboard/app.py) |

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

# 분봉 룰 (장중 시그널 정밀도)
MINT_USE_MINUTE_RULE=false        # true면 KIS 분봉 룰 AND 결합 (KIS 키 필수)
MINT_MIN_MINUTE_VOL_SPIKE=3.0
MINT_MINUTE_SHORT_WINDOW=5
MINT_MINUTE_LONG_WINDOW=20

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
