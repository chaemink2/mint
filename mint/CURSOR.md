# Mint — Cursor 수정·추가 기록

> **용도**: Claude Code / Claude App이 이후 작업·검토할 때, Cursor 세션에서 바뀐 점만 빠르게 파악하기 위한 문서.  
> **전체 맥락·로드맵**은 `CLAUDE.md`를 먼저 읽을 것.

**마지막 업데이트**: 2026-05-19 (Claude — Naver universe 폴백, 16피처, 카카오톡 알림 일체, 분봉 룰, 만료 알림, outcome 자동 평가)

---

## 📌 이 문서를 읽는 순서

1. `CLAUDE.md` — 프로젝트 목표·사용자 결정·현재 로드맵  
2. **`CURSOR.md` (본 문서)** — Cursor가 바꾼 코드·정책·미해결 이슈  
3. `git diff` 또는 아래 「변경 파일 목록」

---

## 🧭 Cursor 세션 요약

| 일시 | 내용 |
|------|------|
| 2026-05-16 | 사용자 요구·Claude Step 1 아키텍처 **교차 검토** (액션 없이 검토만) |
| 2026-05-16 | Claude 앱 장애 → 사용자 요청으로 **합의 사항 코드 반영** (Step 2 KR E2E) |
| 2026-05-16 | `CURSOR.md` 생성, 알림톡 **미승인** 상태 반영 |
| 2026-05-17 | **Claude 세션 — Cursor 권고 1~7번 + Step 3b LightGBM까지 구현** (아래 「Claude 추가 작업」) |

---

## ✅ 사용자 결정 (Cursor 세션에서 확정·반영)

| 항목 | 결정 |
|------|------|
| **+3% 의미** | 24h 내 +3%를 **장담 못 하면 추천하지 않음** (시그널 필터). 익절은 별도(`target_return` 3.5% 권고) |
| **실매매** | 카카오페이증권 수동. KIS는 데이터 전용 |
| **DB 동기화** | 대시보드 **「체결함」** / **「매도 체결함」** 폼 |
| **모델 스택** | 룰 → LightGBM 단독. Qlib/LSTM 앙상블 **보류** |
| **알림** | 카카오 알림톡 유지하되 **비즈 채널·템플릿 미승인** → Step 6까지 **구현 보류** |
| **운영** | PC 간헐 실행 → 기본 `scan` 단발, US 야간 스캔 OFF |

---

## 🔧 Cursor가 구현·수정한 것

### 신규 파일

| 파일 | 역할 |
|------|------|
| `data/schema.py` | canonical OHLCV (`ts_utc`, `source`, `currency` 등) |
| `data/krx_client.py` | pykrx 일봉 → canonical bars |
| `data/collector.py` | 시장별 라우팅 (Step 2: KR만) |
| `data/__init__.py` | 패키지 |
| `engine/signals/rule_scanner.py` | 룰 기반 BUY 스캔 → `signals` 테이블 |
| `engine/__init__.py`, `engine/signals/__init__.py` | 패키지 |
| `portfolio/__init__.py` | 패키지 |
| `tests/test_rule_scan.py` | 룰 스캐너 단위 테스트 (네트워크 없음) |
| **`CURSOR.md`** | 본 문서 |

### 수정·대폭 변경 파일

| 파일 | 변경 요약 |
|------|-----------|
| `main.py` | `scan` / `catch-up` / `daemon` CLI. 기본 단발 스캔. US cron은 `MINT_US_SCAN=true`일 때만 |
| `config/settings.py` | `OperationConfig` 추가. `use_ml_confidence` 기본 false. 시그널 유효 30분·디덤 4h |
| `portfolio/db.py` | v2 스키마 + `migrate_db()`. `signal_id` FK, `valid_until`, 부분매도, 수동 체결 API |
| `dashboard/app.py` | mock 제거 → DB. 스캔 버튼, 시그널별 체결 폼, 포지션 매도 기록 |
| `CLAUDE.md` | 교차 검토·Step 2 완료 상태로 갱신 |
| `.env.example` | `MINT_*` 운영 변수 추가 |

### 의도적으로 하지 않은 것

- `notifier/kakao.py` — 알림톡 **미승인**
- `data/kis_client.py`, `data/us_client.py` — Step 2b/c
- Qlib/LSTM 학습 파이프라인
- Telegram 등 **다른 알림 채널** (사용자가 카카오로 결정)

---

## ⚖️ Claude 원설계 대비 변경 (검토용)

| Claude Step 1 | Cursor 변경 | 이유 |
|---------------|-------------|------|
| `main.py` 상시 스케줄러 + US 10분 스캔 | 기본 `scan` 단발, US OFF | PC 간헐 운영·CLAUDE.md와 불일치 해소 |
| 4중 AND + ML confidence 70% | 룰 3조건 + ML confidence **OFF** | confidence 정의 전 70%는 무의미 |
| Qlib + LGBM + LSTM 60/40 | Step 2는 `rule_scanner`만 | E2E·데이터 없이 ML 선행 방지 |
| Step 2 첫 작업 `kis_client` | **schema → krx → collector** | API 토큰/한도에서 막히지 않게 |
| 손절 -2% “즉시 매도” | **권고** (`stop_loss_is_advisory`) | 카카오페이 수동·PC off |
| 포트폴리오 자동 동기화 | **체결함 폼** | 카카오페이 매매 반영 경로 |

---

## 🐛 알려진 이슈 / 관찰

1. **`python mint/main.py scan` → 0건**  
   - 대형주 위주 워치리스트 + `min_expected_return_1d=3%` 조합이면 **평소 0건이 정상에 가깝다**.  
   - 필터 완화 vs 워치리스트 확대 vs 룰/heuristic 조정은 **백테스트 후** 결정 권장.

2. **pykrx KRX 로그인 경고**  
   - `KRX_ID` / `KRX_PW` 없어도 일봉 조회는 동작함(삼성전자 30일봉 확인).  
   - 일부 API만 로그인 필요 시 `.env`에 추가.

3. **`ref_price` = 전일 종가(일봉 close)**  
   - 장중 “조금 더 싸게” 매수는 아직 **미모델링**. Step 2b `kis_client`로 현재가·지정가 권고 보강 예정.

4. **기존 `mint.db`가 Step 1 스키마만 있으면**  
   - `migrate_db()`가 컬럼 추가. 새 설치는 `init_db()`로 v2 전체 생성.

---

## 📋 Claude 검토 시 체크리스트

- [ ] `rule_scanner._estimate_expected_return_1d` heuristic이 사용자 “24h +3% 장담”과 맞는지  
- [ ] 시그널 0건 빈도 — 필터·워치리스트 튜닝안  
- [ ] `db.open_position_from_signal` — 익절/손절가를 **실체결가** 기준으로 재계산할지  
- [ ] Step 2b `kis_client` 우선순위·인터페이스  
- [ ] Step 6 알림톡: 승인 후 `notifier/kakao.py` 스펙 (지금은 스킵 OK)

---

## 🛣️ Cursor가 제안하는 다음 작업

| 우선순위 | 작업 |
|----------|------|
| 1 | `kis_client` — 장중 `ref_price`, stale 판정 (`MINT_REF_STALE_PCT`) |
| 2 | 체결가 기준 `target_price` / `stop_loss` **재계산** (매수가 대비 %) |
| 3 | `us_client` (yfinance) |
| 4 | 룰 백테스트 스크립트 → 3% 필터 빈도·승률 측정 |
| 5 | 알림톡 승인 후 `notifier/kakao.py` |

---

## 💬 Claude에게 넘길 때 예시 프롬프트

```
CURSOR.md와 CLAUDE.md를 읽고 Cursor가 Step 2에서 한 변경을 검토해줘.
특히 rule_scanner의 3% heuristic과 시그널 0건 문제,
체결가 대비 익절/손절 재계산이 필요한지 의견 줘.
알림톡은 아직 미승인 — notifier는 건드리지 마.
```

---

## 📝 변경 이력

| 날짜 | 작성자 | 내용 |
|------|--------|------|
| 2026-05-16 | Cursor | 최초 작성 — Step 2 E2E, 교차 검토 반영, 알림톡 미승인 |
| 2026-05-17 | Claude | Step 2b/2c/3b/4/7 + 동적 워치리스트. LightGBM Val AUC 0.528 (데이터 부족). 자세한 내용은 `CLAUDE.md` 「학습 결과 기록」 / 「다음 세션 픽업」 |
| 2026-05-18 | Claude | KRX 인증 우회(Naver Finance), 100종목 학습 → AUC 0.594, 16피처 확장(+0.002), 필터 날카로움 검증, 카카오톡 '나에게 보내기' 알림 + 하트비트 + 일일 요약, 종목명 fetch Naver 폴백, 메시지 표기 정직화, Windows 작업 스케줄러 자동화 |
| 2026-05-19 | Claude | 카드 A 완료(KIS 현재가 신선도 마커), 카드 B1(분봉 룰)/B2(시그널 만료 알림)/B3(outcome 자동 평가 + 누적 win rate) 완료. CURSOR 검토 위임 준비. |

---

## 🤖 Claude 추가 작업 (2026-05-17)

Cursor가 제안했던 다음 우선순위(1~5번)를 Claude 세션에서 실행. + LightGBM(Step 3b) 추가 도입.

### 신규 파일

| 파일 | 역할 |
|------|------|
| `data/kis_client.py` | KIS REST 현재가 + stale 판정 + 토큰 캐시 (`.kis_token.json`) |
| `data/us_client.py` | yfinance 일봉 → canonical bars (NASDAQ) |
| `data/universe.py` | 시총 상위 N 동적 워치리스트 + JSON 캐시 24h + 정적 폴백 |
| `engine/features.py` | LightGBM 피처 11개 (ret/vol/atr/rsi/ma/high) |
| `engine/backtest.py` | 룰 시뮬레이션 백테스트 (TARGET/STOP/TIME 청산) |
| `engine/training.py` | 데이터셋 빌드 + LightGBM + isotonic calibration |
| `engine/models/lgbm.py` | TrainedModel + save/load + 모듈 캐시 |
| `engine/signals/exit_strategy.py` | 보유 포지션 매도 권고 |
| `tests/test_features.py`, `tests/test_exit_strategy.py` | 단위 테스트 |

### 수정 파일

| 파일 | 변경 요약 |
|------|-----------|
| `portfolio/db.py` | `open_position_from_signal`: 시그널 ref_price 무시, **체결가 기준** target/stop 항상 재계산 |
| `data/collector.py` | NASDAQ 라우팅 (us_client), 동적 워치리스트(`n` 인자) 통합 |
| `data/krx_client.py` | pykrx stdout silence (`Error occurred in get_stock_name` 등 차단) |
| `engine/signals/rule_scanner.py` | NASDAQ 시장 일반화, ML 필터 통합, 종목명 캐시 |
| `engine/backtest.py` | 동적 워치리스트 연결 |
| `main.py` | `backtest`/`train` CLI, `--watchlist-size`, root 로거 WARNING으로 pykrx 노이즈 차단 |
| `config/settings.py` | `MINT_WATCHLIST_SIZE`, `MINT_USE_ML_CONFIDENCE`, `MINT_MIN_ML_CONFIDENCE`, `MINT_MODEL_PATH` |
| `dashboard/app.py` | 「나스닥 포함」 토글, STALE 배지, 포지션 매도 권고 박스 |
| `CLAUDE.md` | 핸드오프 + 학습 결과 + 다음 세션 가이드 |

### 의도적으로 안 한 것

- 알림톡 — 채널 승인 여전히 없음
- 페이퍼 트레이딩 모드 — 아직 백테스트 비용 대비 가치 낮음
- Qlib/LSTM — LightGBM AUC 0.528 보면서, 더 무거운 모델 도입은 데이터 확대 이후

### 미해결 이슈 (2026-05-17 시점)

1. **KRX cross-sectional API 장애** — `get_market_cap_by_ticker` 등이 `Service unavailable`. 동적 워치리스트 실패. 개별 OHLCV는 정상.
2. **LightGBM AUC 0.528** — 사실상 노이즈. 데이터 확대 + 전략 재검토 필요. (`CLAUDE.md` 「학습 결과 기록」)
3. **백테스트 손익비 비대칭** — 손절 79건 vs 익절 37건. `target_return=+3.5%` vs `stop_loss=-2%`의 비대칭(0.57:1) 검토 필요.

---

## 🤖 Claude 추가 작업 (2026-05-18 ~ 2026-05-19)

### 핵심 변경 요약

| 영역 | 변경 |
|---|---|
| **데이터** | Naver Finance 폴백 (universe, 종목명) — pykrx 1.2.8 KRX 인증 도입 우회 |
| **피처** | 11 → 16 (bb_position, obv_slope, gap_pct, regime_trend, turnover_pct60). gap_pct만 의미 기여, 나머지 4개는 기존과 정보 중복 |
| **모델** | 100종목·365일 재학습 — AUC 0.528 → 0.594, Best iter 7 → 85. Confidence 0.70 임계값에서 매일 6.4개·precision 0.78·lift 1.88× |
| **알림** | 카카오톡 "나에게 보내기" (talk_message scope) — 비즈 알림톡 보류는 유지. 토큰 자동 refresh. 하트비트 + 일일 요약 |
| **신선도** | 매수 메시지에 KIS 현재가 + drift 마커 (⚠️ 엔트리 늦음 / 💡 더 좋은 진입 / ✓ 신선) |
| **분봉** | KIS 5분봉 룰 — 거래량 spike + 단기 모멘텀 + 양봉. 일봉 룰+ML 통과한 종목만 평가 (AND) |
| **만료** | 시그널 만료 카톡 (TIME / TARGET_HIT / STOP_HIT) — '죽은 시그널 매수' 방지 |
| **Outcome** | 24h 후 시그널 outcome 자동 평가 (WIN/LOSS/TIME_EXIT). 일일 요약에 누적 win rate. 재학습 데이터 자동 축적 |
| **운영** | Windows 작업 스케줄러 평일 08:30 + 10분 간격 scan + 15:35 daily-summary |

### 신규 파일 (5/18~5/19)

| 파일 | 역할 |
|---|---|
| `notifier/kakao.py` | 카카오톡 '나에게 보내기' 클라이언트 + 토큰 자동 refresh |
| `notifier/setup_kakao.py` | 1회 인가 헬퍼 |
| `engine/signals/minute_rule.py` | KIS 분봉 룰 (거래량 spike + 모멘텀 + 양봉 AND) |

### 수정 파일 (5/18~5/19)

| 파일 | 변경 |
|---|---|
| `data/universe.py` | Naver Finance HTML 스크래핑 추가 (KRX_ID 있으면 pykrx, 없으면 Naver) |
| `data/krx_client.py` | `get_stock_name`에 Naver 폴백 + 캐시 (`.stock_names.json`) |
| `data/kis_client.py` | `get_minute_bars(ticker)` 추가 (분봉 fetch) |
| `engine/features.py` | 11 → 16 피처 |
| `engine/signals/rule_scanner.py` | 분봉 룰 AND 결합 (use_minute_rule=True 시) |
| `notifier/__init__.py` | notify_buy_signals/exit_advices/expired_signals + heartbeat + daily_summary + freshness + minute marker |
| `portfolio/db.py` | 마이그레이션 추가: expiry_reason/notified/price, outcome/max/min/evaluated_at. check_price_expiry, evaluate_pending_outcomes, get_outcome_stats |
| `main.py` | `daily-summary` / `outcomes` 명령, `_process_expiries`, daemon에 15:35 cron 추가 |
| `config/settings.py` | KakaoConfig 확장(redirect_uri, token_path), use_minute_rule + min_minute_vol_spike + short/long window |
| `.gitignore` | `.kakao_token.json`, `.notifier_state.json`, `.stock_names.json` 추가 (보안) |

### Cursor가 검토하면 좋은 핵심 항목

1. **운영 안정성** — 작업 스케줄러에서 매 10분 호출 시 다음 사항이 견고한가:
   - `_process_expiries()` 가 부분 실패해도 scan 본체는 진행되는가
   - KIS 토큰 자동 재발급 race condition (`_TOKEN_LOCK` 보호 충분한가)
   - 카카오 send 실패 시 비즈니스 로직(시그널 DB 저장)에는 영향 없는가
2. **보안** — `data/.kakao_token.json` / `.kis_token.json` / `.stock_names.json` 가 모두 `.gitignore` 에 들어있는가. log에 토큰 노출이 없는가.
3. **데이터 정합** — `evaluate_pending_outcomes` 의 first-hit 판정:
   - 같은 봉에서 high≥target & low≤stop이면 LOSS로 보수적 판정 (의도). 사용자 정책에 맞는가?
   - `created_at` 시점에 이미 일봉이 있을 수 있는데 (시그널이 장 마감 직전 발생) — `bars[ts_local > created]` 필터가 첫 봉을 누락시키지 않는가?
4. **메시지 200자 제한** — freshness line 추가로 매수 메시지가 늘어남. KIS 응답 길어지면 truncate 가능성?
5. **`_estimate_expected_return_1d`** 휴리스틱과 사용자가 받는 메시지 "모멘텀" 사이 정직성. 이미 표기는 정직화했으나 사용자 멘탈모델과 일치하는지 점검.
6. **분봉 룰 임계값 검증 부재** — `vol_spike ≥ 3.0` 등은 단위 테스트만으로 가정. 실제 KOSPI/KOSDAQ 분봉에서 적절한 값인지 백테스트 필요. (현재 KIS 분봉 백테스트 인프라 없음)
7. **outcome 평가 KRX 일봉 의존** — pykrx의 개별 일봉은 인증 불필요로 동작 중이지만, KRX 정책 추가 변경 시 영향 평가.
8. **사용자 외출 시나리오** — 만료 알림이 새 시그널 알림보다 *먼저* 가야 함. 현재 `_process_expiries()`가 `run_rule_scan()` 앞에 있음. OK.

### Cursor 검토 결과 출력 위치

`mint/REVIEW_CURSOR.md` (새 파일)에 정리해주면 됨. CLAUDE.md/CURSOR.md는 핸드오프 문서이므로 직접 수정은 자제 — 변경 제안만 REVIEW에 적고, 사용자가 승인 시 Claude/Cursor가 반영.

### Cursor에게 권장 작업 (CLAUDE.md 다음 카드 외)

| 우선 | 작업 |
|---|---|
| 1 | 위 검토 항목 8가지 audit |
| 2 | 분봉 룰 임계값 백테스트 — KIS 분봉 1주일치 다운로드해서 vol_spike 분포 확인 |
| 3 | catch-up 시점에 `_process_expiries()`도 자동 호출 중인지 main.py 흐름 재검토 |
| 4 | 카카오 send 메시지 sequence (heartbeat → expiry → buy → daily_summary) 의 순서 일관성 검증 |
| 5 | CLAUDE.md 「학습 결과 기록」의 5/18b/c/d/e 수치 재현 가능한지 확인 (training_data CSV가 git ignored이므로 재학습 + 재계산 필요할 수 있음) |

