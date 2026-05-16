# Mint — Cursor 수정·추가 기록

> **용도**: Claude Code / Claude App이 이후 작업·검토할 때, Cursor 세션에서 바뀐 점만 빠르게 파악하기 위한 문서.  
> **전체 맥락·로드맵**은 `CLAUDE.md`를 먼저 읽을 것.

**마지막 업데이트**: 2026-05-17 (Claude — Step 2b/2c/3b/4/7 + 동적 워치리스트)

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

