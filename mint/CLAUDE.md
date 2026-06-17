# Mint 프로젝트 — 핸드오프 / 결정 기록

> **마지막 업데이트**: 2026-06-16 (성능 회복 sprint — N1·N2·N3+ A/B/C/D · P1b · P1e · M1 재학습)
> **다음 세션 픽업 시**: 아래 [📌 2026-06-17 검증 체크리스트](#-2026-06-17-검증-체크리스트) 최우선

---

## 📌 2026-06-17 검증 체크리스트

**오늘 (2026-06-16) sprint 요약 — 7개 commit, 격차 진단·픽스 셔틀.**

### 다음 cron 직후 (2026-06-17 09:07 KST) 확인 — 즉시
1. **GHA scan-kr 실행 로그**
   - `_enabled()` 사유 메시지 — env disabled/API key 없음/토큰 없음 중 어느 것? (N1 진단)
   - `Catch-up notify: N unnotified BUY signal(s) (active=X, expired=Y)` 로그 라인 (N1)
   - `funnel`에 `skipped_etf`, `skipped_exp_cap` 카운트 보임 (P1b, N3+ A)
2. **첫 BUY 시그널 카톡 메시지**
   - target % = +3% / stop % = -2% / hold = 24h (dynamic exit OFF 적용 확인, N3+ C)
   - regime_label 표시는 유지됨 (정보용)
   - ETF 종목 없음 (P1b 확인)
3. **DB signals 테이블 (audit-once workflow `gh workflow run audit-once.yml -f days=2`)**
   - target_price/ref_price ratio = 1.035 일관 (fixed 환원 확인)
   - notified=1 비율 ≥ 80%
   - 같은 종목 24h 안 반복 없음 (B 확인)

### 1주 후 (2026-06-23 ±2일) 평가 — 핵심 검증
**outcome 30~50건 누적 후 audit-once 재실행 (`gh workflow run audit-once.yml -f days=7`).**

기준 비교:
| 지표 | 6월 (적용 전) | 가설 (N3+ 후) | 실제 |
|---|---|---|---|
| decisive win_rate | 19.6% | 30~40% | TBD |
| LOSS rate | 48.4% | 25~30% | TBD |
| TIME_EXIT rate | 39.8% | 30% 이하 | TBD |
| 일평균 BUY | 5건 (한도) | 1~3건 | TBD |
| EV/거래 | −0.38% | +0.20%~ | TBD |

판단 분기:
- **가설 달성 (≥+10%p)**: M7 카드 C (외국인/기관 수급) 진입 — 진짜 도약
- **부분 달성 (+5~10%p)**: M4 dynamic exit calibration (REGIME_MULT를 6월 outcome 기반 재정의)
- **격차 그대로**: ML calibration 깨짐이 핵심 → live outcome으로 isotonic refit (cards E)

### 1개월 후 (2026-07-15) — 모델 진화 결정
- KR outcome 100건+ 누적되면 M1 v3 학습 (실 운영 분포 학습)
- 사용자 보류 액션 #5 카카오 refresh_token 재발급 (5/18 발급 → 7월 중순 만료)

### 🛑 롤백 절차 (성능이 오히려 악화 시)
1. `cp mint/data/models/mint_lgbm_kr_v1_519c_backup.joblib mint/data/models/mint_lgbm.joblib && git commit && git push`
2. scan-kr.yml에서 `MINT_USE_DYNAMIC_EXIT=true`, `MINT_SIGNAL_DEDUP_H=4`, `MINT_MAX_EXPECTED_RETURN` 제거, `MINT_MIN_ML_CONFIDENCE=0.60`
3. settings.py max_daily_buys 5 → 30 환원 (단, 사용자 합의 후)

---

## 2026-06-16 sprint — 7 commits 요약

| Commit | 카드 | 변경 |
|---|---|---|
| `5ce41d5` | (인프라) | audit-once workflow 추가 |
| `e6a0625` | P1e | MAX_DAILY_BUYS 30→5 환원 (6/1 28f36a6 미합의 픽스) |
| `ad9d03e` | N1 | 카톡 발송율 진단·픽스 (4h expired catch-up + stale 라벨 + _enabled 로그) |
| `e5bc28d` | N2+P1b | ML 임계값 0.60→0.70 (실 효과 작음 — score saturate) + KR ETF prefix 12개 제외 |
| `2ef85ed` | M1 | v2a 재학습 (regime feature, AUC 0.582→0.597) — 라이브 도달률은 격차 미해결 |
| `0e63dca` | **N3+ A/B/C/D** | 6월 outcome 격차 진단 기반 4종 fix (아래) |
| `a5517a3` | (docs) | CLAUDE.md 검증 체크리스트 |
| `ac4324b` | N3+ C hotfix | use_dynamic_exit default true→false (GHA 외 트리거 환경 cover) |
| `8b71ae9` | UI | 추천 시그널 탭 현재가 표시 (KR Naver 모바일 API + NASDAQ yfinance) + target/stop 거리 |
| `4d2a161` | UI hotfix | ImportError(PEP 585) 해소 + light/dark 모두 가독성 테마 (WCAG AA) |
| `06c4201` | UI | import getattr 패턴으로 stale cache 내성 |
| `30fa78f` | UI | Linear/Plausible 스타일 — st.metric stat card + 보유 윈도우 mini card |

### N3+ 격차 5-layer 메커니즘 (2026-06-16 분석)
6월 outcome 186건에서 학습 79% vs 실 19.6% 격차의 원인:

| Layer | 원인 | 데이터 근거 | 픽스 |
|---|---|---|---|
| 1 | Dynamic exit이 target 3.5배(+10.4%)로 키움 | learning label과 mismatch (-50%p) | C: OFF |
| 2 | ML calibration 깨짐 (score 95%가 1.0) | 임계값 무력 | N2(부분), 추후 E recalibrate |
| 3 | STRONG_BULL retracement | 86건 dec 11.5% vs BEAR 31% | D: REGIME_MULT 보수화 |
| 4 | expected_return 15%+ 역신호 | 47건 거의 전멸 (0~7%) | A: cap 12% |
| 5 | 같은 종목 STRONG_BULL 반복 발급 | NAVER 4/0/4, 삼성생명 4/0/4 | B: dedup 4h→24h |

### N3+ 부분 결론 — 카드 우선순위 갱신
- **승률에 직접**: A·B·C·D는 가설 +10~20%p 효과. M7 카드 C는 격차 해소 후 진입.
- **M4 dynamic exit calibration**: D로 임시 보수화했으나 6월 outcome 기반 grid search는 별도.
- **E (ML live recalibration)**: 격차 layer 2 직격. A/B/C 결과 본 후 진입 결정.

### 보존된 운영 변경 (2026-06-16)
- ML 운영 모델: v1 5/19c (138KB) → v2a (174KB, regime feature 포함)
- backup: `mint_lgbm_kr_v1_519c_backup.joblib` (gitignore, 로컬 보관 — 롤백 1cp)
- v2 (regime+dynamic 라벨, AUC 0.549 미채택) 별도 파일 `mint_lgbm_v2.joblib`

---
> **Cursor 변경 이력**: `CURSOR.md` · **Cursor 검토 결과**: `REVIEW_CURSOR.md` · **Cloud 이전 가이드**: `CLOUD_MIGRATION.md` · **사용자 액션 가이드**: `CLOUD_MIGRATION_USER_GUIDE.md` · **1주 운영 플레이북**: `OPERATION_WEEK1.md` · **NASDAQ 확장 인수인계**: `HANDOFF_NASDAQ.md`

---

## 🔁 다음 세션 픽업 가이드 (2026-05-27 이후 — KR + NASDAQ 양면 운영)

### 한 줄 요약
**KOSPI/KOSDAQ Cloud Migration + NASDAQ Stage 1+2+3 완료. 양면 자동 운영 진입 단계.**
- KR: Cloud Migration (`b7afcc1`, `4fb61ec`, `649c4cd`) 완료, 5/22~28 1주 검증 진행 중
- NASDAQ: Stage 1 인프라 (`9311065`) + Stage 2 ML 학습 (`e8d793c`) + Stage 3 백테스트 (`d77d7e4`) 완료. GHA scan-us cron 활성화 (KST 22:30~05:50)

### 첫 행동 (3가지 시나리오)

**A) 사용자가 신규 요구사항을 가지고 옴**
1. 요구사항을 KR / NASDAQ / 공통 / 인프라로 분류
2. 작업량 추정 (<30분 즉시 / 30분~2h 분해 / 2h+ Stage 분해)
3. 사용자 결정 필요 사안은 `AskUserQuestion`으로 합의 후 시작
4. 「⚙️ 변경 금지 사항」 (아래) 위반 시 사용자 명시 합의 필요

**B) 운영 결과 점검 (1주 누적 후)**
- KR (5/29 이후): `mint/OPERATION_WEEK1.md` 끝 「📌 다음 세션 픽업」 절차
- NASDAQ (6/3 이후): outcome 누적 후 재학습 검토 (현재 AUC 0.553 → 도약 기대)

**C) 카드 진행 (사용자 신규 요구사항 없을 때)**
- 「다음 카드 우선순위」 (아래) 참조

### ⚙️ 변경 금지 사항 (KR + NASDAQ 양 운영 보호)
| 영역 | 보호 대상 | 변경 조건 |
|---|---|---|
| ML 모델 | `mint_lgbm.joblib` (KR), `mint_lgbm_us.joblib` (US) | 재학습 시 사용자 합의 + 별도 commit |
| DB 스키마 | `portfolio/db.py` | backwards-compatible 변경만 (ALTER ADD COLUMN OK, DROP은 사용자 합의) |
| GHA workflow | `scan-kr.yml`, `scan-us.yml`, `daily-summary.yml`, `outcomes.yml` | env / cron 변경 시 사용자 명시 합의 |
| 운영 임계값 | KR ML 0.60 / US ML 0.55 / KR 분봉 ON / US 분봉 OFF | 사용자 결정 사안 — 변경 시 명시 합의 |
| 라벨 정의 | KR 24h +3% / NASDAQ 24h +2% | 재학습 동기와 함께 사용자 합의 |
| Risk/Trade 제한 | `max_position_pct=20%`, `max_daily_buys=5` | 사용자 결정 — 변경 시 합의 |

### 👤 사용자 보류 액션 (항상 추적·noti)
| # | Action | 시기 | 비고 |
|---|---|---|---|
| 1 | **Alpaca 가입 + 키 발급** (Stage 2.5 NASDAQ 분봉) | 분봉 룰 도입 결정 시 | 사용자 (3) 결정 |
| 2 | **카카오페이증권 해외주식 매매 환경** 확인 (FX/수수료/거래시간) | NASDAQ 첫 실 매수 전 | 사용자 (a) 결정 |
| 3 | **카톡 새벽 알림 수면 영향** 검토 | NASDAQ 1주 시범 운영 중 | silent 시간대 옵션 검토 |
| 4 | **NASDAQ 1주 시범 outcome 확인** | ~2026-06-03 | get_outcome_stats(7) |
| 5 | **카카오 refresh_token 만료 대비** (5/18 발급 → 7월 중순) | 7월 초 | `python mint/notifier/setup_kakao.py` 재실행 |
| 6 | **Windows 작업 스케줄러 Disable** | 5/28+ KR 검증 종료 후 | GHA 안정 확인 시 |

### 📊 운영 컴포넌트 (KR + NASDAQ 양면)
| 컴포넌트 | 트리거 | 무엇 | 상태 |
|---|---|---|---|
| Neon Postgres | 24/7 | DB | ✅ |
| scan-kr | 평일 KST 09:00~15:50 (UTC `*/10 0-6 * * 1-5`) | KOSPI/KOSDAQ 200종 룰+ML+분봉 | ✅ 1주 검증 중 (5/22~28) |
| scan-us | 평일 KST 22:30~05:50 (UTC `*/10 13-21 * * 1-5`) | NASDAQ 171종 룰+ML (분봉 OFF) | ✅ 5/27 활성화 |
| daily-summary | 평일 KST 15:35 | outcome 평가 + 카톡 일일 요약 | ✅ |
| outcomes | 평일 KST 23:30 | 24h 경과 outcome 평가 | ✅ |
| Streamlit Cloud | 24/7 | 대시보드 (KR + NASDAQ regime 3개 카드) | ✅ |
| Windows 스케줄러 | backup | 5/28+ Disable 예정 | ⏳ |

### 🎯 운영 임계값 / 학습 결과 baseline
| 시장 | 모델 | AUC | 임계값 | Precision | 일평균 |
|---|---|---|---|---|---|
| KR (5/19c) | `mint_lgbm.joblib` (200×730d, 24h +3%) | 0.582 | 0.60 | 0.79 | 1.3건 |
| NASDAQ (exp3) | `mint_lgbm_us.joblib` (171×730d, 24h +2%) | 0.553 | 0.55 | 0.636 | 0.22건 |
| NASDAQ 백테스트 | 730일 sliding | — | 0.55 | 84.4% win | 0.18건/일 (월 5.4) |

### 다음 카드 우선순위 (1주 운영 + 사용자 요구사항 수렴 후 결정)
1. **NASDAQ outcome 30건+ 누적 → 재학습** (KR 5/17→5/19c 패턴 따라 도약 가능)
2. **Stage 2.5 NASDAQ Alpaca 분봉** (사용자 Action 1 후) — KR 동급 정밀도 회복 핵심
3. **KR outcome 30건+ → 카드 m 재학습** (regime feature + dynamic exit 라벨)
4. **카드 N — Dynamic Exit calibration** (REGIME_MULT grid search, outcome 20건+ 후)
5. **카드 D — 페이퍼 트레이딩 인프라** (ML 0.79 vs live 검증)
6. ~~**P1 — 시장 지수 표시 오류**~~ ✅ 2026-06-02 closed (재검증 결과 코드 정상 — OPERATION_WEEK1.md P1 참조)
7. **Step 8 — Windows 작업 스케줄러 Disable** (사용자 Action 6)

### 📝 신규 요구사항 진행 패턴
```
1. 요구사항 분류 (KR / NASDAQ / 공통 / 인프라)
2. 작업 분해 + 우선순위
3. 사용자 결정 필요 사안 AskUserQuestion으로 합의
4. 「변경 금지 사항」 위반 시 사용자 명시 합의
5. Stage 별 commit (commit message 패턴 준수)
6. 작업 완료 후 CLAUDE.md「사용자 결정」「학습 결과」갱신
7. 사용자 Action 발생 시 「사용자 보류 액션」 표에 추가 + noti
```

### Commit message 패턴
- `feat(kr): ...` / `feat(us): ...` — 신규 기능
- `feat(kr,ml): ...` / `feat(us,ml): ...` — ML 관련
- `feat(kr,gha): ...` / `feat(us,gha): ...` — workflow
- `fix(...) / docs(...) / refactor(...)` — 의미 그대로

---

## 📦 NASDAQ 완료 작업 요약 (5/26~27, 3 commits)

**`9311065` Stage 1 — 인프라**:
- `data/universe.py`: Wikipedia NASDAQ-100 동적 워치리스트 (24h 캐시)
- `engine/market_regime.py`: ^IXIC 매핑, `regimes_line(markets)` 확장
- `engine/signals/rule_scanner.py`: dynamic exit NASDAQ 분기 (SUPPORTED_REGIME_MARKETS)
- `portfolio/db.py`: `_evaluate_single_outcome` NASDAQ 분기 (us_client)
- `notifier/__init__.py`: `_format_price(value, market)` helper, currency 분기
- `dashboard/app.py`: regime 3개 카드 + 시그널 currency
- `.github/workflows/scan-us.yml`: env 정비 (cron은 주석 유지)

**`e8d793c` Stage 2 — ML 학습 + GHA 활성화**:
- 4회 실험: exp1(100종 24h+3%, AUC 0.544) → exp2(171종 +3%, AUC 0.545) → **exp3(171종 24h+2%, AUC 0.553, best_iter 31) 채택** → exp4(171종 48h+3%, AUC 0.545 미채택)
- `engine/models/lgbm.py`: MODEL_PATHS, `model_path_for_market()`, `get_cached_model(market=)`
- `engine/training.py`: `target_return/stop_loss` override, NASDAQ-only 학습 시 us 경로 자동
- `engine/signals/rule_scanner.py`: `_ml_probability(df, market)` 시장 분기
- `mint/data/models/mint_lgbm_us.joblib` (93KB) repo 포함
- `scan-us.yml` schedule 활성화 (`*/10 13-21 * * 1-5` UTC)

**`d77d7e4` Stage 3 — 백테스트**:
- NASDAQ 171종목 730일 백테스트: 135건 시그널, 승률 84.4%, 평균 +1.77%, σ 2.43%
- Exit 분포: TIME 83% / TARGET 10% / STOP 7%
- Val 영역(2026-02~05, 16건)만 보면 75%, +0.7% (표본 작음)

---

## 5/21~22 작업 요약 (KR Cloud Migration 운영 상태)

**5/21 진단 픽스 (`aaae6e7`)**:
- TZ 비교 버그 픽스, Universe 정적 폴백 → default 200, Risk 게이트 30→45
- Cursor 3차 검토 응답 본문(R0~R6 + 결론 H) commit

**5/21 Cloud Migration 코드 (`b7afcc1`, `4fb61ec`, `465731d`)**:
- Phase 1: SQLAlchemy 추상화 (sqlite/postgres 양쪽 호환). DATABASE_URL env.
- Phase 2: auth_tokens + app_state 테이블. 토큰/state 자동 DB 마이그레이션.
- Phase 4: GHA workflow 4개 (scan-kr/scan-us/daily-summary/outcomes). 모델 파일 repo commit. `scan-us` CLI 명령 추가.
- GHA용 requirements-runtime.txt 분리 (qlib/torch 제외)

**5/22 배포 (`649c4cd`)**:
- Streamlit Cloud용 mint/dashboard/requirements.txt 분리 (plotly ModuleNotFoundError fix)
- 사용자 액션 8단계 중 1~6 완료 (KIS IP OFF, Neon, Secrets, 토큰 복사, GHA Daily Summary, Streamlit Cloud)
- 대시보드 정상 가동: https://chaemink2-mint.streamlit.app
- 5/22 첫 funnel: 평가 392 → 모멘텀 53 → 리스크 27 → 거래량 16 → 시그널 0 (universe 200 효과 확인)

### 다음 카드 우선순위 (1주 운영 후 결정)
1. **outcome 30건 이상 누적 시 → 카드 m (재학습)**
2. **GHA 안정 확인 시 → Step 8 (Windows 작업 스케줄러 Disable)**
3. **알려진 이슈 처리**: ~~P1 시장 지수 표시 오류~~ (6/2 closed), ~~P2 UTC vs KST dedup~~ (5/23 closed), P3 mint/requirements.txt qlib 청소 (상세는 OPERATION_WEEK1.md)
4. **카드 C** — KOSPI/KOSDAQ regime/섹터 독립 신호
5. **카드 D** — 페이퍼 트레이딩 인프라
6. **NASDAQ 야간** — scan-us.yml cron 주석 해제

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
| 2026-05-26 NASDAQ exp1 | 100 (Wikipedia NASDAQ-100) | 730d | 1d | 4,514 | 0.480 | 0.544 | 0.6911 | 3 | **NASDAQ 첫 학습** (KR과 동일 라벨 24h +3%/-2%). AUC 합격선(0.55) 미달, best_iter 3은 모델이 어떤 신호도 못 찾았다는 의미. p99=0.535로 임계값 0.55 이상 시그널 0건. 데이터 부족 의심. |
| 2026-05-26 NASDAQ exp2 | 171 (NASDAQ-100 + S&P NASDAQ) | 730d | 1d | 7,767 | 0.476 | 0.545 | 0.6897 | 6 | **데이터 확대 (+72%)**. AUC 무변화(+0.001). 종목 수 확대만으로 한계 — 시장 분포 자체가 단순 OHLCV 피처로 24h +3% 예측 어려움 (효율적 시장). |
| **2026-05-26 NASDAQ exp3** ⭐ | **171** | **730d** | **1d** | **7,767** | **0.486** | **0.553** | **0.6885** | **31** | **라벨 변경: 24h +2%/-2%** (사용자 (B) 결정). AUC +0.008 · best_iter 31로 학습 깊이 ↑. 임계값 0.55에서 precision 0.636 · 일평균 0.22건. **운영 모델 채택 → mint_lgbm_us.joblib**. dynamic exit max_hold(BULL 30h)와 정합. KR 동급(precision 0.79) 미달 → outcome 누적 후 재학습 전제. |
| 2026-05-27 NASDAQ exp4 | 171 | 730d | 2d | 7,770 | 0.460 | 0.545 | 0.6817 | 14 | 비교 실험: 48h +3%/-2%. AUC 0.545 · best_iter 14로 exp3보다 낮음. 임계값 0.60에서 precision 0.636 · 일평균 0.11건. 보유 48h는 dynamic exit(30h)과 mismatch → **미채택**. |

### NASDAQ 모델 필터 날카로움 (exp3 = 운영 모델, val n=1,554, 101일)
| 임계값 | 통과 | 일평균 | Precision | Lift |
|---|---|---|---|---|
| 0.40 | 1,428 | 14.1 | 0.499 | 1.03× |
| 0.50 | 638 | 6.3 | 0.549 | 1.13× |
| **0.55** ⭐ | **22** | **0.22** | **0.636** | **1.31×** |
| 0.60 | 4 | 0.04 | 1.000 | 2.06× (n=4 noise) |
| Top-1/day | 101 | 1.0 | 0.485 | 1.00× |
| Top-2/day | 202 | 2.0 | 0.533 | 1.10× |

→ 운영 임계값 **0.55** (1주 1~2건). KR(0.60에서 1.3건/0.79)와는 격차. 분봉 룰 OFF (Alpaca 미도입) + outcome 누적 후 재학습 시 도약 기대.

### NASDAQ exp3 피처 중요도 (gain Top 7)
| 순위 | 피처 | Gain % |
|---|---|---|
| 1 | ret_1d | 10.9 |
| 2 | ret_5d | 10.5 |
| 3 | obv_slope | 8.3 |
| 4 | gap_pct | 8.3 |
| 5 | dist_high60 | 6.7 |
| 6 | rsi_14 | 6.6 |
| 7 | atr_pct | 6.5 |

→ KR과 다르게 atr_pct 비중 ↓ (22.9% → 6.5%). NASDAQ은 변동성 자체보다 **단기 모멘텀(ret_1d/5d)과 OBV 흐름**이 더 강한 신호. 피처 중요도가 KR보다 더 평탄 (rsi_14 20.7% → 6.6%) — 한 피처에 의존하지 않는 분포.

### NASDAQ Stage 3 백테스트 (2026-05-27, 171종목 × 730일, ML 임계값 0.55)
| 지표 | 값 |
|---|---|
| 시그널/거래 | 135건 (월평균 5.4, 일평균 0.18 — val 추정 0.22와 일치) |
| **승률** | **84.4%** (114/135) |
| 평균 수익 | +1.77% / median +1.23% |
| 평균 보유 | 1.0일 (max_hold_days=1 cap) |
| Exit 분포 | TIME 112 (83%) / TARGET 13 (10%) / STOP 10 (7%) |
| Win/Loss/std | 114/21 / σ 2.43% |
| Val 영역만 (2026-02~05) | 16건, 승률 ≈ 75%, 평균 +0.7% (표본 작음) |

**정직성**:
- 84.4% 승률은 학습 train 영역 일부 포함된 in-sample. 엄밀 평가는 val 영역(16건, ~75%).
- val precision 0.636 vs backtest win rate 0.844 격차는 라벨 정의 차이 — 학습은 "24h +2% 도달", 백테스트는 "profit > 0 with TIME 청산 포함".
- TIME 청산이 83%로 dominant. dynamic exit target(ATR×1.5×regime_mult ≈ +3~5%)이 24h 내 거의 도달 X. **TIME 청산 평균이 +이라 net positive**.
- 2026-02 단일 손실 달(-0.99%, 6건)은 표본 작아 noise 가능. 시계열 안정성은 1주 시범 운영 outcome으로 추가 검증.

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
| 2026-05-20 | **Cursor 3차 검토 R2~R6 반영**: 대시보드 caption 보강(R2), P&L gauge edge case 가드(R3), accumulate_scan_stats file lock(R4), validate_filters.py 스크립트(R5), TZ 유틸 Cloud 선행(R6) | [REVIEW_CURSOR.md](REVIEW_CURSOR.md) Section G |
| 2026-05-20 | **mock state cleanup**: `.notifier_state.json`의 `scan_stats_2026-05-21`은 카드 c 검증 시 잔여 mock 데이터. 실제 5/21 시그널 0건 (DB 확인). 정리 완료 | data/.notifier_state.json |
| 2026-05-26 | **NASDAQ Stage 1 완료** (`9311065`): 동적 워치리스트(Wikipedia NASDAQ-100), regime ^IXIC, dynamic exit·outcome 평가 NASDAQ 분기, 카톡 currency 분기, 대시보드 regime 3개. KR 운영 무영향. | HANDOFF_NASDAQ.md |
| 2026-05-26 | **NASDAQ 학습 결정 사안**: ML 전용 모델(A) / 분봉 Alpaca(3) / 즉시 Stage 1(i) / 실 카카오페이 매매(a). 4가지 합의 후 Stage 1 진행. | 별도 세션 |
| 2026-05-26 | **NASDAQ ML 라벨 사안 (B)**: KR 24h +3% 동일 라벨로 AUC 0.545 무변화 → **24h +2%/-2%로 변경**. AUC 0.553 best_iter 31 (운영 가능 수준). KR과 비교 가능성 일부 손실 인정. | 학습결과 NASDAQ exp3 |
| 2026-05-27 | **NASDAQ Stage 2 완료**: `mint_lgbm_us.joblib` (24h +2% exp3 모델 채택). 임계값 0.55 운영 (precision 0.636 · 일평균 0.22건). 48h +3% 비교실험은 미채택. | [engine/models/lgbm.py:MODEL_PATHS](engine/models/lgbm.py) |
| 2026-05-27 | **scan-us.yml schedule 활성화**: `*/10 13-21 * * 1-5` UTC (NY 정규장 DST/비DST 모두 커버). ML 활성화·분봉 OFF (Alpaca 미도입). | [.github/workflows/scan-us.yml](.github/workflows/scan-us.yml) |
| 2026-05-27 | **카톡 가로채기 fix**: dashboard `_run_scan`이 `_notify_buys` 누락 → 다른 사용자가 대시보드에서 트리거한 시그널이 카톡 발송 없이 DB만 채워서 `has_recent_signal(4h)`이 본인 GHA scan을 차단했음. main.py cmd_scan과 동일 흐름(만료 처리 + 카톡)으로 통일. catch-up 버튼도 동일 fix. | [dashboard/app.py:_run_scan](mint/dashboard/app.py) |
| 2026-05-27 | **추천 시그널 페이지 hold window 표시**: `valid_until`(30분)만 보던 `get_active_signals` 대신 `get_signals_in_hold_window` 신설 — `max_hold_hours` 안 시그널 모두. 매수 적기(fresh, ≤30분) vs 보유 윈도우(hold, ≤max_hold_hours) 두 카테고리로 구분 표시 + 메인 대시보드에 종목명 리스트. 가격 만료(TARGET_HIT/STOP_HIT)·acted는 제외. | [portfolio/db.py:get_signals_in_hold_window](mint/portfolio/db.py), [dashboard/app.py](mint/dashboard/app.py) |
| 2026-05-27 | **타임스탬프 KST 통일**: 신규 timestamp 저장은 모두 `now_kst().isoformat()` (+09:00 포함). config/tz.py에 `now_kst_iso()` helper. portfolio/db.py·rule_scanner·exit_strategy·kis_client·notifier/kakao·dashboard·main 모든 호출지. 기존 데이터(tz-naive)와 비교 시 `to_kst()` 정규화. 운영 임계값·라벨·모델은 무변경 (변경 금지 사항 보호). | [config/tz.py](mint/config/tz.py) |

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
