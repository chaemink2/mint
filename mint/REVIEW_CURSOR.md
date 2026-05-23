# Mint — Cursor 2차 검토 (Claude Code 5/17~5/19)

> **검토일**: 2026-05-19  
> **입력**: `mint/CLAUDE.md`, `mint/CURSOR.md`, 저장소 코드 (commit `79da7f9` 기준 로컬 워크스페이스)  
> **범위**: CURSOR.md 「Cursor가 검토하면 좋은 핵심 항목」8개 audit + 추가 risk + 학습 수치 재현 + 다음 카드 ROI  
> **원칙**: `CLAUDE.md` 「사용자 결정」 변경 제안 없음. 코드 수정은 사용자 승인 후.

---

## 0. 한 줄 평가

**운영 가능한 베타(MVP+)** — Windows 스케줄러 + 카카오 알림 + 100종목 ML + 만료/신선도/분봉 옵션까지 갖춘 **추천·기록 시스템**.  
다만 **학습 데이터와 실시간 추론의 분포 불일치**, **페이퍼/실성과 검증 부재**, **일부 운영·보안 마무리**가 남아 있어 “실전 자동 수익” 단계는 아님.

| 영역 | 성숙도 (5단계) |
|------|----------------|
| 데이터 (KR 일봉·universe·KIS) | 4 |
| 시그널 (룰+ML+옵션 분봉) | 3.5 |
| 알림·운영 | 4 |
| 포트폴리오·수동 체결 | 3.5 |
| 검증 (백테스트·아웃오브샘플·페이퍼) | 2 |

---

## 1. CURSOR.md 8개 항목 Audit

### 1) 운영 안정성

| 등급 | 판정 |
|------|------|
| 🟡 | 대체로 견고. 몇 가지 운영 구멍 있음 |

**🟢 그대로 OK**
- `_process_expiries()` → `run_rule_scan()` **순서** (`main.py:95-100`) — 만료 알림이 신규 BUY보다 먼저. CURSOR 8번 요구 충족.
- 만료/카카오 실패는 `try/except` + `log.warning` — **DB 시그널 저장과 분리** (`_notify_buys`, `_process_expiries`).
- `catch-up`도 `_process_expiries()` 호출 (`main.py:118`).
- 카카오·KIS HTTP `timeout=5s` — 스케줄러 hang 위험 낮음.

**🟡 권장 변경**
- **`cmd_scan_us()`는 `_process_expiries()` 미호출** (`main.py:104-111`). US만 스캔할 때 만료 알림·가격 만료 누락.
- **`max_daily_buys=5`가 `settings`에만 있고 `rule_scanner`에서 미적용** — 하루 10통 이상 BUY 가능.
- Windows 작업 스케줄러 + `daemon` 15:35 `daily-summary` **이중 실행** 시 요약 카톡 중복 가능 (`notifier` state로 1일 1회 방지는 있으나, **서로 다른 프로세스·state 파일**이면 중복).
- 10분마다 **전 워치리스트(최대 100×2)** 스캔 — 장 시작 직후·Naver/pykrx 지연 시 **한 run이 5분 초과**할 수 있음. “놓친 작업 빨리 시작” + 겹침 실행이면 **중복 scan** 가능.

**🔴 진짜 문제 (수정안)**
- 없음 (치명적 크래시 경로는 보호됨). 다만 위 🟡는 운영 2~4주 후 체감될 수 있음.

**구체 수정안 (승인 시)**
```python
# main.py cmd_scan_us 상단에 cmd_scan과 동일하게:
_process_expiries()

# rule_scanner.run_rule_scan 마지막에:
# 오늘 BUY signal_type 카운트 >= config.signal.max_daily_buys 이면 break/return
```

---

### 2) 보안

| 등급 | 판정 |
|------|------|
| 🟡 | gitignore 양호. 로컬·로그·스크래핑 리스크 |

**🟢 그대로 OK**
- `.gitignore`에 `.env`, `data/.kakao_token.json`, `data/.kis_token.json`, `training_data_*.csv` 포함.
- `kakao.py` / `kis_client.py` — 실패 시 **응답 body 전체를 INFO가 아닌 warning**에만 일부; access token을 log에 print하는 코드 없음.
- Kakao refresh는 `threading.Lock()` (`kakao._LOCK`) — 동시 refresh race 완화.

**🟡 권장 변경**
- 워크스페이스에 **`.kakao_token.json` 실파일 존재** — gitignore 되어 있으나, OneDrive 동기화·백업·스크린샷 유출 주의 (문서/사용자 교육).
- `setup_kakao.py` redirect `https://localhost` — 로컬 MITM 환경에서는 표준적이나, **토큰 파일 권한**(Windows ACL) 미제한.
- `universe.py` Naver HTML 스크래핑 — **약관/차단** 리스크 (기능 보안이 아닌 가용성).

**🔴 진질 문제**
- **없음** (키가 repo에 commit된 흔적은 로컬 검사상 없음).  
- 단, `git ls-files`로 **주기적 확인** 권장.

---

### 3) 데이터 정합 (outcome / expiry / first-hit)

| 등급 | 판정 |
|------|------|
| 🟡 | 보수적 LOSS 가정은 합리. 경계 케이스 몇 개 |

**🟢 그대로 OK**
- `_evaluate_single_outcome`: 동일 봉 high≥target & low≤stop → **LOSS 우선** (`db.py:371-376`) — 사용자 “리스크 최소”와 일치.
- `check_price_expiry`: KIS 현재가로 TARGET_HIT/STOP_HIT — **살아 있는 시그널** 정리에 유용.

**🟡 권장 변경**
- Outcome 평가: `bars["ts_local"] > created` (`db.py:359`) — **시그널이 당일 장중·종가 근처**에 나오면 **당일 봉 전체가 제외**될 수 있음. `>=` 또는 “당일 봉은 partial bar로 처리” 검토.
- Outcome은 **일봉 high/low**만 사용 — 장중 30분 유효 시그널과 **24h 정의**가 어긋날 수 있음 (문서에 한 줄 명시 권장).
- `check_price_expiry`와 outcome이 **서로 다른 데이터 소스**(KIS 실시간 vs pykrx 일봉) — 만료·성과 통계 불일치 가능.

**🔴 진짜 문제 — 학습 vs 추론 분포 불일치**

`engine/training.py` `build_ticker_dataset` 주석은 “룰 필터 통과 진입점만”이나, **실제 코드는 모든 슬라이딩 윈도우를 label링** (`evaluate_ticker` 미호출).

| 단계 | 필터 |
|------|------|
| **추론** (`evaluate_ticker`) | `min_expected_return` + risk + volume + (optional) ML + (optional) 분봉 |
| **학습** | 피처만 있으면 전부 label (룰 무관) |

→ CLAUDE.md 5/18e “룰 only win 0.416”과 “ML이 룰을 고른다”는 **오프라인 스크립트 결과**로 보이며, **현재 학습 파이프라인과 논리적으로 어긋남**.  
ML이 “룰 통과 후보”가 아니라 “임의의 모든 날”에서 학습되면, **val precision 0.78이 운영 필터와 다를 수 있음**.

**구체 수정안**
```python
# build_ticker_dataset 루프 안, feats 계산 후:
from engine.signals.rule_scanner import evaluate_ticker
sub_full = bars.iloc[: i + 1]  # evaluate_ticker가 len>=25 필요
if evaluate_ticker(ticker, market, sub_full.reset_index(drop=True)) is None:
    continue
# ML 학습 시 use_ml_confidence=False 상태로 룰만 맞추기
```
→ 재학습 후 5/18d/e 수치 **재검증 필수**.

---

### 4) 메시지 200자 제한

| 등급 | 판정 |
|------|------|
| 🟡 | truncate 있으나 다중 라인·이모지로 실읽 가독성 이슈 |

**🟢 그대로 OK**
- `kakao.send_text` → `_truncate(200)` (`kakao.py:202-205, 224`).
- 기본 BUY 메시지(신선도 줄 없음) 로컬 측정 **약 116자** (Cursor 측정).

**🟡 권장 변경**
- `_format_buy_signal` 6~7줄 + freshness(한 줄 최대 ~50자) + 분봉 마커 → **200자 근접·초과 빈번**. 잘림 시 **목표/손절가가 잘리면** 치명적.
- **우선순위 truncate**: 종목명·기준가·목표/손절은 보존, 모멘텀·부가 설명부터 제거하는 **구조적 shorten**이 `_truncate` 한 글자 삭제보다 안전.

**구체 수정안**
```python
# _format_buy_signal: 한 줄 요약 모드 if len > 180
# 또는 freshness를 별도 두 번째 메시지로 분리 (MAX 2통/시그널)
```

---

### 5) 휴리스틱 정직성 (“모멘텀” vs +3% 장담)

| 등급 | 판정 |
|------|------|
| 🟡 | UI/카톡은 정직화됨. 수학적 의미는 여전히 약함 |

**🟢 그대로 OK**
- 카톡: “예상 수익” 대신 **“모멘텀”**, ML/룰 라벨 분기 (`notifier/__init__.py:88-121`).
- `_estimate_expected_return_1d` = `0.35*ret_5d + 0.25*ret_1d + vol` (`rule_scanner.py:55-68`) — **+3% 확률이 아님**.

**🟡 권장 변경**
- `min_expected_return_1d=0.03`과 휴리스틱이 **같은 스케일이 아님** — 과거 5일 수익 3%면 통과 가능하나, **다음 24h +3%와 무관**.
- 사용자 멘탈모델: “장담 못 하면 추천 안 함” → 실제는 **과거 모멘텀 필터 + (옵션) ML P(win)**. CLAUDE 픽업 가이드에 **1문장**으로 고정하는 것이 좋음 (문서 수정은 사용자 승인 후).

**🔴**
- 없음 (의도적 정직 표기로 완화됨). 다만 **필터 이름을 `min_momentum_score`로 바꾸는 것**은 사용자 결정 영역이라 REVIEW에서만 제안.

---

### 6) 분봉 임계값 검증

| 등급 | 판정 |
|------|------|
| 🟡 | 설계는 합리. 검증·한도 미흡 |

**🟢 그대로 OK**
- 일봉+ML 통과 후에만 `fetch_and_evaluate` — KIS 호출 수 제한 (`minute_rule.py`, `rule_scanner.py:142-149`).
- 기본 `MINT_USE_MINUTE_RULE=false` — 안전 디폴트.

**🟡 권장 변경**
- `vol_spike≥3.0`, short/long window — **백테스트/분포 스크립트 없음** (CURSOR 지적 동의).
- `get_minute_bars` **당일 ~30봉, 5분봉 가정** — 장 초반에는 `minute_long_window=20` 미충족으로 **전부 탈락** 가능.
- 10분 스케줄 × ML 통과 6~10종목 × 분봉 = **시간당 수십 KIS 호출** — 한도 문서화 필요.

**🔴**
- 없음 (기본 off).

**권장 다음 작업**: 1주일치 상위 종목 분봉 CSV 수집 → `vol_spike` 분포 p50/p90 플롯 (코드 없이 notebook도 가능).

---

### 7) Outcome 평가 (KRX 일봉 의존)

| 등급 | 판정 |
|------|------|
| 🟡 | 작동하나 “실전 체감 승률”과 괴리 가능 |

**🟢**
- pykrx 개별 일봉은 현재 동작 (로컬 fetch 확인).
- `evaluate_pending_outcomes` + `daily-summary` 연동 — **운영 데이터 축적** 설계 좋음.

**🟡**
- 일일 요약 win rate ≠ 카카오페이 **실체결 승률** (수동 매매·미체결 시그널).
- Outcome **TIME_EXIT** 비율이 높으면 0.78 precision과 별개로 **사용자 만족도** 낮을 수 있음.

**🔴**
- 없음.

---

### 8) 만료 알림 순서 (외출 시나리오)

| 등급 | 판정 |
|------|------|
| 🟢 | 요구사항 충족 |

**🟢**
- `cmd_scan`: heartbeat(선택) → **expiries** → scan → buy notify.
- 만료 건은 `unnotified_expired` + `mark_expiry_notified`로 중복 방지.

**🟡**
- PC가 며칠 꺼져 있으면 — **만료 알림이 한꺼번에** catch-up 시 전송될 수 있음 (스팸). `MAX` 제한은 buy에만 있고 expiry에도 동일 cap 적용 여부 검토.

---

## 2. 추가로 발견한 Risk (8항목 외)

| 심각도 | 항목 | 설명 |
|--------|------|------|
| 🔴 | **학습–추론 분포 불일치** | 위 3) — 5/18 ML 검증 수치의 운영 적용 신뢰도 저하 |
| 🟡 | **`MINT_USE_ML_CONFIDENCE` 기본 false** | 스케줄러가 ML 없이 돌면 CLAUDE의 “0.70 sweet spot”과 **다른 제품** |
| 🟡 | **Isotonic calibration** | val set에 fit — 같은 20% val에서 **p99≈0.70** (재현). threshold 0.70이 “상위 1%”에 가까워 **임계값 의미가 좁음** |
| 🟡 | **Naver 스크래핑** | HTML 구조 변경 시 universe 100종목 **전멸 → static 10 폴백** |
| 🟡 | **모델 파일 git 미포함** | `mint_lgbm.joblib`는 로컬에만 있을 수 있음 — 새 머신/CI에서 ML 스캔 silent degrade |
| 🟡 | **학습 label = `profit_pct > 0`** | TARGET(+3.5%)만 win이 아니라 **TIME_EXIT 소폭 플러스도 win** — 사용자 “+3% 만족”과 label 정의 차이 |
| 🟢 | **테스트 커버리지** | rule/features/exit 단위 테스트 있음. notifier/db/integration 없음 |

---

## 3. CLAUDE.md 학습 결과 재현 (5/18b/c/d/e)

**데이터**: 로컬 `mint/data/models/training_data_20260518_202917.csv` (47,440 rows, pos rate **0.443**, CLAUDE 5/18b/c와 일치)

**재현 방법**: `engine.training.train_model(df)` — 동일 80/20 time split, 16 features.

| 표 항목 | CLAUDE.md | Cursor 재현 | 일치 |
|---------|-----------|-------------|------|
| 5/18b/c 샘플 수 | 47,440 | 47,440 | ✅ |
| 5/18b/c Val AUC | 0.594 / **0.596** | **0.596** (iter 59) | ✅ |
| 5/18b Best iter | 85 (11 feat) | (11 feat CSV 별도 재학습 안 함) | — |
| 5/18d val n | 9,488 | 9,488 | ✅ |
| 5/18d p99 | 0.702 | **0.702** | ✅ |
| 5/18d thr 0.70 precision | 0.780 | **0.780** | ✅ |
| 5/18d thr 0.70 per day | 6.4 | **6.41** | ✅ |
| 5/18d thr 0.75 precision | 0.988 | **0.988** | ✅ |
| 5/18d thr 0.75 per day | 1.8 | **1.76** | ✅ |
| 5/18e Top-1/day win | 0.980 | **0.980** (49 days) | ✅ |
| 5/18e 룰 only win 0.416 | 0.416 | **미재현** (repo에 스크립트 없음) | ⚠️ |

**해석**
- **5/18b/c/d/e의 ML 관련 수치는 재현 가능** — Claude 기록 신뢰도 높음.
- **5/18e “룰 only 0.416”**은 별도 오프라인 분석으로 보이며, 현재 `training.py`는 룰 필터 없이 학습하므로 **“ML이 룰 위에 얹힌다”는 스토리와 코드가 불일치**.
- **5/17 AUC 0.528** — `training_data_20260517_*.csv`로 동일 절차 시 재현 가능 (이번 세션에서는 미실행).

**권장**: `scripts/validate_filters.py`를 repo에 고정해 CI/수동 재현 가능하게 (승인 후).

---

## 4. 다음 카드 ROI (C / D / E / F / G)

사용자 결정(+3% 필터, 카카오페이 수동, 카카오톡 알림) 유지 전제.

| 순위 | 카드 | ROI | 이유 |
|------|------|-----|------|
| **1** | **D — 페이퍼 트레이딩** | ★★★★★ | 이미 스케줄러·알림·outcome DB 있음. **실전 전환 전 유일하게 “돈 안 쓰고” 검증** 가능. ML 0.70 켠 채 4주 win rate vs 0.78 비교가 핵심. |
| **2** | **(신규) 학습–추론 정합** | ★★★★☆ | 코드 소규모, 효과 큼. 5/18e 해석·ML 필터 신뢰도에 직결. |
| **3** | **C — 독립 신호** | ★★★☆☆ | AUC +0.002 포화 이후 **유일한 구조적 상승** 가능. 다만 수급/섹터 API·작업량 큼. |
| **4** | **E — 데이터 확대** | ★★☆☆☆ | 20→100에서 이미 +0.066. 200/730일은 **한계체감·비용↑** 가능. D 이후 데이터가 쌓이면 우선순위 재평가. |
| **5** | **F — 피처 4개 정리** | ★☆☆☆☆ | 유지보수·해석력. AUC 거의 안 변할 것 (문서와 일치). |
| **6** | **G — target/stop 대칭** | ★☆☆☆☆ | **사용자 결정 변경** 필요. 백테스트상 손절 79 vs 익절 37이면 논의 가치는 있으나 정책 카드. |

**D 구현 시 최소 스펙 제안** (승인 후)
- 시그널 발생 시 `paper_positions` 가상 매수 (체결가 = signal ref 또는 다음 KIS가)
- 24h 후 outcome과 동일 규칙으로 가상 청산
- `daily-summary`에 **실제 outcome win rate vs paper win rate** 병기

---

## 5. 지금 Mint를 쓸 때 체크리스트 (운영자용)

1. `.env`에 `MINT_USE_ML_CONFIDENCE=true` + `mint/data/models/mint_lgbm.joblib` 존재 확인  
2. Windows 작업: **「새 인스턴스 시작 안 함」** + scan 10분 **> 예상 실행 시간**  
3. `daily-summary` 15:35 **단일 트리거** (daemon과 중복 X)  
4. 카카오 메시지 잘림 시 — 대시보드에서 시그널 상세 확인 (URL/대시보드 링크 추가는 개선안)  
5. 며칠 PC off 후 첫 scan — **만료 알림 폭주** 가능 → `MINT_NOTIFY_MAX` expiry에도 적용 검토  

---

## 6. 승인 요청 목록 (코드 반영 후보)

| # | 항목 | 예상 diff |
|---|------|-----------|
| P1 | `build_ticker_dataset`에 `evaluate_ticker` 룰 필터 적용 + 재학습 | `engine/training.py` |
| P2 | `cmd_scan_us`에 `_process_expiries()` | `main.py` |
| P3 | `max_daily_buys` enforce | `rule_scanner.py` |
| P4 | 카톡 메시지 shorten (목표/손절 보존) | `notifier/__init__.py` |
| P5 | outcome `ts_local > created` → `>=` 또는 당일 봉 포함 | `portfolio/db.py` |
| P6 | `scripts/validate_filters.py` (5/18e 재현) | 신규 |
| P7 | 페이퍼 트레이딩 (카드 D) | `portfolio/` + `main.py` |

**사용자에게 확인이 필요한 정보**
1. 운영 중 **`MINT_USE_ML_CONFIDENCE=true`인지?** (false면 ML 검증 수치와 무관하게 동작)  
2. **`MINT_USE_MINUTE_RULE` 켜져 있는지?**  
3. 작업 스케줄러 — scan / daily-summary **각각 몇 개 등록**되어 있는지 (중복 여부)  

---

## 7. 결론

Claude Code는 Cursor Step 2 이후 **6~8주치 분량의 기능을 3일에 압축**한 수준이다. 아키텍처·운영·정직한 알림 문구·ML 데이터 확대는 **실사용 가능**하다.

다만 **“ML precision 0.78을 믿고 실전”** 하기 전에:
1. **학습 데이터에 룰 필터를 넣는 정합성 수정** (P1)  
2. **페이퍼 4주** (D)  
3. **아웃오브타임 validation** (val 49일 이후 구간)  

이 세 가지 없으면, 통계는 예쁘지만 **카카오페이에서의 실제 수익**과 어긋날 위험이 크다.

---

*본 문서는 Cursor가 작성. `CLAUDE.md` / `CURSOR.md` 미수정.*

---

# 📨 Cursor에게 — 3차 검토 요청 (2026-05-20 사용자 발신)

## 배경 (Claude가 정리)

2차 검토(5/19) 이후 다음 작업 완료:
- **P1+P2+P3 반영** (commit `2a5e9f3`) — 학습-추론 정합 + 운영 안정 + 메시지 안전
- **카드 E** (commit `412bbbd`) — 200종목 × 730일 재학습. AUC 0.551 → 0.582, 임계값 0.60 일평균 1.3개 · precision 0.79
- **카드 a/b/c** (commit `863d6f8`) — 시장 지수 / 스캔 funnel / 미드데이 ping (운영 가시성)
- **카드 d/e/f/g** (commit `2771542`) — 대시보드 통합 리프레시 (시장지수+funnel+outcome trend, P&L 게이지, 모델 분석 페이지+슬라이더, 모바일 UI)
- **운영 첫날 (5/20)**: 약세장 (KOSPI -0.86%, KOSDAQ -2.61%) → 시그널 0건. 시스템 보수 회피 성공.

운영 환경 답변 (Claude가 PowerShell로 확인):
1. `MINT_USE_ML_CONFIDENCE=true` ✓
2. `MINT_USE_MINUTE_RULE=true` ✓
3. 작업 스케줄러: `Mint Signal Scan` 1개만 등록. `Mint 일일 요약`은 미등록 (사용자 잔여 작업).

## 사용자 핵심 질문

> "내일이 오늘처럼 엄청난 하락장이 아니라는 가정 하에, 좋은 시그널을 내가 받을 수 있는 상황인지에 대해서 검증해줘."

## 부탁드릴 검토

### A. 평상시 시그널 건전성 (핵심)
1. **5/19c 모델 (AUC 0.582)** 의 임계값 0.60 + 분봉 ON 조합이 **평상시 (지수 -0.5% ~ +0.5%) 에 적절한 시그널 양** 을 만들 수 있는지?
   - val 시뮬레이션 일평균 1.3개. 분봉 통과율 미검증 → 실제는 더 적을 가능성.
   - 분봉 임계값 (`vol_spike >= 3.0`) 이 너무 빡빡해서 시그널이 거의 0인 운영이 될 수도?
2. 분봉을 끄거나 (`MINT_USE_MINUTE_RULE=false`) 분봉 임계값을 낮추는 것 (`MINT_MIN_MINUTE_VOL_SPIKE=2.0`) 중 어느 쪽 권장?
3. ML 임계값 0.60이 평상시 적정인지, 아니면 0.55까지 낮춰서 시그널 양 확보 vs precision 감수가 나은지?

### B. 5/20 카드 a/b/c 코드 정합성
1. `data/market_index.py` Naver 모바일 API — 휴일/장 후 동작?
2. `notifier.maybe_send_midday_ping` 의 자동 사유 진단 로직(약세장/ML 미달/분봉 미달) 이 funnel stats 해석으로 합리적인지?
3. `notifier.accumulate_scan_stats` race condition (여러 scan 동시) 위험?

### C. 5/20 카드 d/e/f/g 대시보드
1. `dashboard/app.py` 의 새 함수 (outcome_trend_df, signal_count_trend, model_confidence_distribution) SQL/pandas 정합성
2. `🧠 모델 분석` 페이지 임계값 슬라이더가 사용자에게 의미 있는 작용을 하는지 (val set 기준이라 실 운영과 격차 있음)
3. P&L 게이지의 stop/buy/target axis 범위 — 음수 가격 등 edge case

### D. 다음 카드 우선순위 (사용자 결정 보조용)
다음 후보:
- **카드 m** — outcome 1~2주 누적 후 실 분포 재학습
- **카드 C** — 시장 regime/섹터 피처 (현재 가장 큰 도약 카드)
- **카드 D** — 페이퍼 트레이딩 인프라
- **Cloud Migration** — `CLOUD_MIGRATION.md` 가이드 (PC OFF + NASDAQ 야간 운영)

사용자 의향: 미래에 Cloud Migration 하고 싶음 (PC OFF + NASDAQ). 다만 지금은 1~2주 운영 후 결정.

## 검토 결과 출력

`mint/REVIEW_CURSOR.md` 끝에 `# 📨 Cursor 3차 검토 (2026-05-XX)` 섹션으로 append.
승인된 사항만 Claude가 다음 라운드에 코드 반영.

---

# 📨 Cursor 3차 검토 (2026-05-21)

> **검토 범위**: 5/20 세션 5 commits (`8d4554e`~`5efe692`) + 운영 funnel 실측 + `CLOUD_MIGRATION.md`  
> **2차 대비**: P1(학습-추론 정합)·P2(`scan_us` 만료)·P3(`max_daily_buys`) **반영 확인됨**

---

## 0. 사용자 핵심 질문에 대한 답

> **「내일이 평상시(지수 ±0.5%)라면 좋은 시그널을 받을 수 있는가?」**

**예 — 받을 수 있는 구조입니다.** 다만 기대치를 **「하루 0~2건의 카카오 매수 알림」**으로 잡는 것이 맞고, **「매일 여러 건」**은 아닙니다.

| 근거 | 내용 |
|------|------|
| 백테스트(val) | 5/19c 모델, 룰+ML **0.60** → **일평균 1.3건**, precision **0.79** (분봉 **미포함**) |
| 5/20 실측 (약세) | KOSPI -0.86%, KOSDAQ -2.61% → funnel `passed_momentum=0` → 시그널 0 — **의도대로 회피** |
| 5/21 실측 (상대적 평상) | 6회 scan, `passed_momentum=30` → `passed_ml=5` → `passed_minute=2` → **시그널 2건** (`.notifier_state.json`) |
| 해석 | 평상시에도 **분봉 AND**가 최종 관문이라 val 1.3건의 **절반 이하**가 카톡까지 갈 수 있음 |

**「좋은 시그널」의 정의를 나누면:**

- **시스템 관점**: precision ~0.79(ML만) → 분봉 추가 시 더 보수적 → **나쁜 날 0건, 좋은 날 1~2건**은 건전함.
- **체감 관점**: 주 2~5건이면 “자주 온다”고 느끼기 어려울 수 있음 → **미드데이 ping + funnel**이 그 공백을 메우는 설계(5/20 카드 c)로 타당.

---

## A. 평상시 시그널 건전성 (상세)

### A-1. ML 0.60 + 분봉 ON — 일평균 ~1개 가능한가?

| 등급 | 판정 |
|------|------|
| 🟢 | **가능** (0~2건/일). 5/21 funnel이 실증적 전처리 |
| 🟡 | val **1.3건/일**은 분봉 없는 시뮬 — 실운영은 **더 적음** |

**파이프라인 대략적 통과율 (5/21 하루, 200종×6 scan 누적):**

```
평가 1200 → 모멘텀 30 (2.5%) → … → ML 5 (0.42% of evaluated) → 분봉 2 (0.17%) → 시그널 2
```

- 스캔마다 **같은 종목 재평가**이므로 %는 낮게 보임. 중요한 것은 **하루 끝 `signals_created=2`**.
- 평상시(지수 ±0.5%)면 `passed_momentum` 비율이 5/20(0%)보다 **5/21(2.5%/scan 누적) 이상**으로 오를 가능성 큼.
- **보수적 운영 추정**: 평상시 **주 3~8건**, 약세일 **0~1건**.

### A-2. `vol_spike >= 3.0` 너무 빡빡한가?

| 등급 | 판정 |
|------|------|
| 🟡 | **빡빡함**. 5/21에서 ML 5건 중 분봉 **2건만** 통과 (통과율 ~40%) |

**권장 (코드 변경 없이 env만):**

| 옵션 | 장점 | 단점 |
|------|------|------|
| **① `MINT_MIN_MINUTE_VOL_SPIKE=2.0` (권장 1순위)** | 시그널 수 ↑, 5/21 데이터로 점진 조정 가능 | precision 소폭 하락 가능 |
| ② 분봉 OFF | val 기준 ~1.3건/일에 근접 | 장중 “이미 오른 뒤” 진입 ↑, 5/20 약세에도 모멘텀 통과 종목은 알림 가능 |
| ③ 분봉 ON 유지 + 3.0 | precision 최대 | **평상시에도 0~1건/일**에 그칠 위험 |

**Cursor 의견:** **분봉을 끄지 말 것.** 대신 **`vol_spike=2.0`으로 1~2주 운영** 후 funnel의 `passed_ml` vs `passed_minute` 비율을 보고 2.5/3.0 재조정.  
장 초반(09:00~10:00)은 `minute_long_window=20` 미충족으로 **구조적으로 0건** — 스케줄러가 08:30 시작이면 첫 1~2회 scan은 분봉 통과 거의 없음(정상).

### A-3. ML 0.60 vs 0.55

| 등급 | 판정 |
|------|------|
| 🟢 | **0.60 유지** |

`CLAUDE.md` 5/19c 표: **0.55~0.74 구간 precision·일평균 동일(plateau)**. 0.55로 내려도 **시그널 수 이득 없음**, precision만 0.686으로 하락.

**0.55는 비추천.** 시그널 수를 늘리려면 ML보다 **분봉 완화(2.0)** 또는 **Top-N/일 1건** 정책이 낫다.

---

## B. 카드 a/b/c 정합성 (5/20 `863d6f8`)

### B-1. `data/market_index.py`

| 등급 | 판정 |
|------|------|
| 🟢 | 구현 적절 |
| 🟡 | 휴일·장후·API 변경 |

**🟢**
- Naver 모바일 JSON, 60초 캐시, `marketStatus` 보존 — heartbeat/미드데이/일일요약에 적합.
- 5/20 약세 수치(-0.86%, -2.61%)와 funnel `passed_momentum=0` **정합**.

**🟡**
- **휴일/장전**: API 실패 시 `None` → 메시지에서 지수 줄 생략 (크래시 없음). “시스템 죽음”과 혼동 가능 → 캡션 “지수 조회 실패” 한 줄 권장(승인 시).
- **장 마감 후**: `CLOSE`여도 종가·등락률은 유효 — 문제 없음.
- **Naver 스키마 변경** 시 silent fail — universe와 동일 리스크.

### B-2. `maybe_send_midday_ping` 자동 진단

| 등급 | 판정 |
|------|------|
| 🟢 | funnel 기반 진단 **합리** |

분기 순서 (`notifier/__init__.py:248-255`):

1. `passed_momentum==0` → 약세/모멘텀 부족  
2. else `passed_ml==0` & `passed_volume>0` → ML 미달  
3. else `passed_minute==0` & `passed_ml>0` → 분봉 미달  

5/20 데이터와 **일치** (모멘텀 0이면 2·3번 미실행). 5/21에서는 분봉 병목 메시지가 나올 조건 충족 가능.

**🟡 한계:** `passed_volume`은 모멘텀 통과 후 카운트 — 메시지 “룰은 통과”는 엄밀히 **모멘텀+리스크+거래량**까지 통과한 뒤 ML 실패를 의미. 사용자 혼동 가능하나 **방향은 맞음**.

### B-3. `accumulate_scan_stats` race

| 등급 | 판정 |
|------|------|
| 🟡 | 이론상 race, 실운영에서는 낮음 |

read-modify-write without file lock. Windows 스케줄러 **「새 인스턴스 시작 안 함」**이면 대부분 직렬.  
겹침 시 funnel 숫자 **소폭 누락** 가능 — 치명적 아님.

**승인 시 수정안:** `fcntl`/`portalocker` 또는 scan 종료 시 **단일 writer** 보장.

---

## C. 카드 d/e/f/g 대시보드 (`2771542`)

### C-1. SQL / pandas 정합성

| 등급 | 판정 |
|------|------|
| 🟢 | SQLite에서 동작 |
| 🟡 | Cloud(Postgres) 이전 시 수정 필요 |

**🟢**
- `_outcome_trend_df`, `_signal_count_trend`: `DATE(created_at)` — **SQLite OK**.
- `_scan_funnel_today`: notifier state 읽기 — DB와 분리, 정합.

**🟡**
- `CLOUD_MIGRATION.md` Phase 1 시 `DATE()` → `DATE_TRUNC('day', ...)` 등 **dialect 분기** 필요 (가이드에 이미 언급됨).
- outcome이 아직 적으면 차트 **빈 화면** — 1~2주 후 의미 생김.

### C-2. 모델 분석 슬라이더

| 등급 | 판정 |
|------|------|
| 🟢 | 교육·튜닝용으로 **의미 있음** |
| 🟡 | 실운영과 격차 명시 필요 |

- validation set + **최신 training CSV** 기준 — 5/19c 수치와 **일치** (0.60 plateau 재현 가능).
- **분봉·dedup·장중 stale** 미반영 → “슬라이더에서 10건 나온다” ≠ “오늘 카톡 10건”.
- UI에 이미 caption 있음 — **“validation 기준, 분봉 미포함”** 한 줄 추가 권장(승인 시).

### C-3. P&L 게이지 edge case

| 등급 | 판정 |
|------|------|
| 🟡 | 일반 케이스 OK, edge 있음 |

```python
"axis": {"range": [stop * 0.99, target * 1.01] if target and stop else None},
```

- `target <= stop` (데이터 오류) → gauge 깨짐.
- `buy_price <= 0` → metric/format 오류.
- `stop`/`target` None → `range: None` — Plotly가 자동 스케일 (허용).

**승인 시 수정안:** `if target and stop and target > stop > 0` 일 때만 steps/range 설정.

---

## D. 다음 카드 우선순위 (ROI)

사용자 의향: Cloud는 **1~2주 운영 데이터 후**. 당장 **일일 요약 스케줄러 등록** 잔여.

| 순위 | 카드 | ROI | 이유 |
|------|------|-----|------|
| **0 (즉시)** | **일일 요약 스케줄러** | ★★★★★ | outcome 평가·누적 win rate·funnel 마감이 **안 돌고 있음**. 코드 완성, 트리거만缺失 |
| **1** | **카드 m** (outcome 1~2주 후 재학습) | ★★★★☆ | 일일 요약 없으면 outcome DB가 안 쌓임 → **m은 요약 이후** |
| **2** | **분봉 vol_spike 2.0 실험** (env) | ★★★★☆ | 코드 0줄, 평상시 시그널 수 튜닝 — 사용자 질문 직결 |
| **3** | **카드 D** (페이퍼) | ★★★★☆ | 실체결 없이 **가상 승률 vs ML 0.79** 검증 |
| **4** | **카드 C** (regime/섹터) | ★★★☆☆ | AUC 구조적 상승 — 작업량 큼, 2~4주 후 |
| **5** | **Cloud Migration** | ★★★☆☆ | PC OFF + NASDAQ — **아래 Cloud 절** |
| **6** | **카드 F** (피처 정리) | ★☆☆☆☆ | 유지보수 |

**2차 검토 P4(카톡 shorten)·P5(outcome 당일봉)·P6(validate_filters)** — 여전히 유효하나 **일일 요약·분봉 튜닝보다 후순위**.

---

## E. Cloud Migration (`CLOUD_MIGRATION.md`) 의견

| 등급 | 판정 |
|------|------|
| 🟢 | 가이드 방향 **타당** |
| 🟡 | 트리거·순서 조정 권장 |

### 트리거 시점 (Cursor 의견)

**지금 당장 Full Migration 하지 말 것.** 아래 **모두** 충족 후:

1. ✅ ML 0.60 + 분봉 운영 **1~2주** (funnel·outcome 축적)  
2. ⏳ **`Mint 일일 요약` 스케줄러 등록** (사용자 잔여 5분)  
3. ⏳ outcome **WIN/LOSS 30건 이상** 또는 2주 경과  
4. ⏳ (선택) 페이퍼 또는 수동 체결 **10건 이상** — 실전 체감 검증  

**PC OFF + NASDAQ**이 목표면: **Phase 4(GHA cron) + US workflow**만 먼저 해도 됨. DB는 당분간 **SQLite를 Actions artifact로 넘기는 해킹**보다, 가이드대로 **Postgres 전환 후**가 깔끔.

### 스택·단계 의견

| 항목 | 의견 |
|------|------|
| GitHub Actions cron | KR 일봉 스캔에 **적합** (5~15분 지연 허용). `workflow_dispatch` 병행 권장 |
| Supabase vs Neon | **Neon** — 무료 3GB·branching. Supabase도 OK |
| SQLAlchemy 추상화 | **필수** — `dashboard`의 `DATE()` 포함 dialect 분기 |
| 토큰 DB화 | GHA에서 **필수** — 가이드 Phase 2 정확 |
| `mint_lgbm.joblib` git commit | **권장** — Actions에서 모델 누락 방지 (가이드와 동일) |
| Streamlit Cloud | 대시보드만 cloud, **scan은 GHA** — 분리 타당 |
| KIS IP 제한 | **OFF 필수** — 가이드 경고 적절 |
| UTC vs KST | 🔴 마이그레이션 시 **가장 흔한 버그** — `ZoneInfo("Asia/Seoul")` 일원화 선행 권장 |

### NASDAQ 야간

- `scan-us` + `MINT_US_SCAN` — 코드 준비됨 (`cmd_scan_us`에 `_process_expiries` 포함 확인).
- Cloud 후 **별도 workflow** `scan-us.yml` (UTC 13:30~20:00) — KR과 **cron 분리**가 디버깅에 유리.
- yfinance 지연 — “실시간” 기대 낮추기 (문서화됨).

---

## F. 2차 검토 대비 개선·잔여

| 2차 항목 | 5/20 상태 |
|----------|-----------|
| P1 학습-추론 정합 | ✅ `training.py` 룰 필터 적용 확인 |
| P2 `scan_us` 만료 | ✅ `main.py:110` |
| P3 `max_daily_buys` | ✅ `rule_scanner.py:207-219` |
| P4 카톡 200자 | 🟡 freshness+분봉 시 여전히 위험 |
| P5 outcome 당일봉 | 🟡 미수정 |
| train/inference 분봉 gap | 🟡 문서화됨, 코드상 분봉은 추론만 |

---

## G. 승인 요청 목록 (3차 — Claude 다음 라운드)

| # | 항목 | 기대 효과 |
|---|------|-----------|
| R0 | 사용자: **일일 요약 스케줄러 등록** (코드 아님) | outcome·win rate 파이프라인 가동 |
| R1 | env 실험: `MINT_MIN_MINUTE_VOL_SPIKE=2.0` (1~2주) | 평상시 시그널 0~1 → 1~3 |
| R2 | 대시보드 모델 페이지 caption: “val 기준, 분봉 미포함” | 기대치 관리 |
| R3 | P&L gauge `target > stop` 가드 | edge crash 방지 |
| R4 | `accumulate_scan_stats` file lock | funnel 정확도 |
| R5 | `scripts/validate_filters.py` (5/19c 재현 + 분봉 시뮬 placeholder) | 수치 감사 가능 |
| R6 | Cloud: **TZ 유틸 + DATE() dialect** 선행 (Migration Phase 0) | 이전 시 버그 예방 |

**비추천 (이번 라운드):** ML 0.55, 분봉 OFF, target/stop 대칭(G), Full Cloud 즉시 실행.

---

## H. 결론 (사용자에게)

1. **평상시에는 시그널을 받을 수 있다** — 다만 **하루 0~2건**이 정상이며, 5/20 같은 약세일 0건도 **설계대로**다.  
2. **0.60 + 분봉 ON** 조합은 유지하되, **`vol_spike` 2.0**으로 완화 실험을 권장한다. 분봉 OFF는 precision 대신 “늦은 진입” 리스크가 커진다.  
3. **지금 가장 급한 것은 코드가 아니라 `daily-summary` 스케줄러** — 없으면 outcome·win rate·카드 m이 모두 지연된다.  
4. **Cloud**는 가이드 품질 좋음 — **1~2주 로컬 운영 + 일일 요약 가동 후** Postgres+GHA로 옮기는 순서가 맞다.

---

*본 섹션은 Cursor 3차 검토. `CLAUDE.md` / `CURSOR.md` 미수정.*

---

# 📨 Cursor 4차 검토 요청 (2026-05-23)

## 배경 (Claude가 정리)

3차 검토(5/21) 이후 사용자가 다음을 일괄 결정·진행:

1. **5/21 진단 픽스** (`aaae6e7`)
   - TZ 비교 버그 (`_evaluate_single_outcome`에서 KST tz-aware vs naive 비교 실패)
   - Universe 정적 폴백 (MINT_WATCHLIST_SIZE 미설정 → static 20종목으로 운영 중. 200종목 모델과 mismatch)
   - Risk 게이트 30→45 (실 데이터 모멘텀 통과 종목 risk 평균 41.4. 사용자 결정 사안 변경)

2. **Cloud Migration 코드 + 배포** (`b7afcc1`, `4fb61ec`, `465731d`, `5fab66d`, `649c4cd`)
   - Phase 1: SQLAlchemy 추상화 (sqlite/postgres 양쪽 호환). DATABASE_URL env, RETURNING id, dialect 분기
   - Phase 2: auth_tokens + app_state 테이블. kakao/kis 토큰 + notifier state 파일→DB 자동 마이그레이션 (1회)
   - Phase 4: GHA workflow 4개 (scan-kr/scan-us/daily-summary/outcomes). mint_lgbm.joblib repo commit. main.py에 scan-us 명령 추가
   - GHA용 requirements-runtime.txt + Streamlit용 dashboard/requirements.txt 분리 (qlib/torch 제외 — 그게 cold-start 빌드 실패 원인이었음)
   - Neon Postgres + GHA cron + Streamlit Cloud (https://chaemink2-mint.streamlit.app) 운영 시작

3. **지수 추종 + Dynamic Exit** (`c55e8e8`) — 사용자 비전 paradigm shift
   - 사용자 5/22 발언: "mint의 진짜 목표는 최단시간 내 최대 수익. +3%/-2%/24h는 baseline 예시. 종목별·시장별 동적 적용 필요."
   - **ML 모델은 그대로** (binary classifier, AUC 0.582). post-processing layer만 동적.
   - `engine/market_regime.py` 신규 — KOSPI/KOSDAQ 시장별 5단계 regime (yfinance ^KS11/^KQ11)
   - `engine/dynamic_exit.py` 신규 — 종목 ATR × regime multiplier → target/stop/hold
   - signals/positions 테이블 max_hold_hours/regime_label 컬럼 추가
   - 카톡 시그널/heartbeat/midday/daily_summary + 대시보드 4곳에 regime 표시

## 사용자 핵심 질문

> **"5/22~23 양일 변경 다발(8 commit, +1300 lines)이 안전한가? 1주 운영 시작 전 마지막 점검."**

## 부탁드릴 검토

### A. SQLAlchemy 리팩터 회귀 안정성 (commit b7afcc1)
- `portfolio/db.py` 654→830 lines. 모든 SQL을 `text()` + named param + `RETURNING id`로 변환
- `_evaluate_single_outcome`은 `to_kst()` 통일 + 시그널별 max_hold_hours 사용
- 검토 포인트:
  1. `_existing_columns()` PRAGMA(sqlite) vs information_schema(postgres) 분기 정확한가
  2. SQLite FK 활성화 이벤트(`PRAGMA foreign_keys=ON`)의 안정성
  3. `_id_pk()` AUTOINCREMENT vs BIGSERIAL — 마이그레이션 후 기존 sqlite 데이터 호환 문제 없나
  4. `mark_expiry_notified`의 `bindparam(expanding=True)` — postgres에서 정상 동작 확인됐는지 (현재 로컬은 sqlite만 검증)
  5. `ON CONFLICT(service) DO UPDATE` UPSERT — sqlite 3.35+ / postgres 9.5+ 호환만 가정. Python 3.13 sqlite는 더 최신이라 OK이지만 GHA ubuntu Python sqlite 버전 확인 필요

### B. Phase 2 토큰/상태 영속화 (kakao/kis/notifier)
- 파일 → DB 1회 자동 마이그레이션 패턴
- sqlite 운영 시 파일도 동시 보존 (`if DATABASE_URL.startswith("sqlite")`)
- 검토 포인트:
  1. **순환 import 위험**: notifier/kakao.py가 portfolio.db import — kakao 모듈은 다른 곳에서도 import되는데 init 시점 충돌 가능성
  2. **GHA 휘발 환경에서 첫 호출**: Neon에 토큰 없으면 `_load_tokens` → file fallback → file 없음 → None. 그때 발송 attempt가 어떻게 처리되는지
  3. **race condition**: 동시 2개 GHA가 토큰 refresh 시도하면 (예: scan-kr + daily-summary가 같은 5분 안에) — UPSERT는 atomic이지만 refresh API 호출 자체는 중복 호출. KIS는 토큰 발급 한도 있음

### C. GHA workflow 안전성 (commit 4fb61ec, 465731d)
- 4개 workflow + 인라인 env (`MINT_USE_ML_CONFIDENCE=true` 등 6개)
- `concurrency: { group: mint-kr-scan, cancel-in-progress: false }`
- 검토 포인트:
  1. **secrets 노출 위험**: workflow 로그가 자동 마스킹되나 — 특히 KIS_APP_SECRET이 stderr 출력에 섞일 가능성
  2. **timeout-minutes 10**: KR scan은 200종목 pykrx fetch — pip cache miss 시 30s + scan 5~9분 = OK. 다만 첫 콜드런 4~6분 추가 가능성 — timeout=15 권장?
  3. **cron 시각 KST 9:00~15:50**: UTC `*/10 0-6 * * 1-5` — 정확한가? (06:00 UTC = 15:00 KST, `0-6` 범위가 UTC 06:50까지 = KST 15:50)
  4. **daily-summary 시각**: `35 6 * * 1-5` UTC = 15:35 KST. KR 장 마감 직후 적절
  5. **outcomes 시각**: `30 14 * * 1-5` UTC = 23:30 KST. 24h 지난 5/19 LOSS 같은 외래 데이터는 이미 평가됐고, 신규 시그널 24h 이후 평가만 의미

### D. Dynamic Exit 휴리스틱 합리성 (commit c55e8e8) — 🔥 가장 중요
**`engine/dynamic_exit.py`의 multiplier 값들은 사용자 결정 사안. 임의 휴리스틱이라 백테스트 없음.**

| Regime | target × | stop × | hold × |
|---|---|---|---|
| STRONG_BULL | 1.5 | 0.7 | 1.5 |
| BULL | 1.2 | 0.85 | 1.25 |
| SIDEWAYS | 1.0 | 1.0 | 1.0 |
| BEAR | 0.75 | 0.9 | 0.75 |
| STRONG_BEAR | 0.5 | 0.85 | 0.5 |

- baseline: target = ATR×1.5, stop = -ATR×1.0, hold = 24h
- cap: target [1.5%, 15%], stop abs [0.5%, 5%], hold [6h, 72h]
- 검토 포인트:
  1. **ATR 기반 target/stop의 정합성** — 변동 큰 종목엔 큰 target. 그러나 ATR 큰 종목은 본질적으로 노이즈 큰 종목이라 false positive ↑ 가능. ATR×1.5 multiplier가 적정한가? (백테스트 없음)
  2. **regime multiplier 비대칭** — STRONG_BULL의 stop ×0.7 (좁힘)은 강세장의 의도된 lower drawdown 허용. 다만 강세장에선 작은 stop으로 false stop이 잦을 수 있음. 데이터로 검증 필요
  3. **hold 6~72h 범위** — 6h hold는 일봉 outcome 평가에 정확도 한계 (분봉 fetch 인프라 미구축). `_evaluate_single_outcome`은 일봉 first-hit이라 6h hold도 24h 일봉 1개로 평가됨 — 사실상 hold=24h와 동일 평가. 이게 문제인가?
  4. **종목 ATR 사용처와 risk 게이트 mismatch** — risk_score = ATR_pct × 500 (cap 100). dynamic_exit는 `atr_pct = risk / 500.0` 역산. 이게 정확한가? risk가 100에 캡되면 atr_pct도 0.2 캡 — 그런 큰 변동 종목은 사실상 dynamic_exit cap에 다 묶임
  5. **NASDAQ 미적용**: us_client 종목엔 regime 없고 dynamic_exit 안 됨. 일관성 깨짐 (현재 NASDAQ scan은 비활성이라 영향 작음)

### E. Market Regime 분류 임계값 (engine/market_regime.py)
- composite_score = ret_5d × 0.5 + ret_20d × 0.3 + ma20_dist × 0.2
- 카테고리 cut: ±0.04 (STRONG), ±0.01 (BULL/BEAR), 그 사이 SIDEWAYS
- 검토 포인트:
  1. **ret_5d 가중치 0.5**: 사용자 직관 "최근 분위기" 반영. 그러나 ret_5d는 단기 noise도 큼 — 한 큰 갭이 regime 잘못 판단할 가능성
  2. **STRONG_BULL 임계값 +0.04**: 5/22 KOSPI가 5d +4.7%로 STRONG_BULL 분류. 한국 시장에서 +4.7%가 STRONG_BULL이 맞는 강도인가
  3. **yfinance fetch 실패 시**: SIDEWAYS 폴백 — 안전 default이나, 만약 장기간 yfinance 장애 시 dynamic_exit가 항상 SIDEWAYS multiplier(1.0/1.0/1.0)로 동작. 즉 baseline ATR×1.5 target만 적용. 보수적이라 무해
  4. **KOSPI vs KOSDAQ regime 독립** — 사용자 결정. 다만 KOSPI/KOSDAQ 상관 0.7+ 라 별도 분류의 실익은 작을 수 있음
  5. **VKOSPI 등 변동성 지표 미반영**: regime이 오로지 가격 기반. 향후 카드

### F. 카톡 메시지 200자 안전성 (P3 재발 위험)
시그널 메시지에 dynamic + regime 줄 추가 → 길이 ↑
```
🟢 [Mint 매수] 🇰🇷 삼성전자 (005930)
기준가 72,500원
🎯 76,578 (+5.6%) / 손절 71,231 (-1.7%)
⏱ 36h내 권고 · 유효 30분
시장 🟢🟢 KOSPI 강한 상승
⚠️ 현재 72,820원 (+0.44% · 이미 상승, 엔트리 늦음)
🔥 5분봉 패턴 동시 통과
모멘텀 +4.5% · ML 확률 73%
```
- 총 8줄 — 한글 + 이모지 비율 높아 200자 위험
- 검토 포인트:
  1. truncate 로직 (라인 단위 아래쪽부터)이 핵심 정보 보존하는가
  2. 200자 안전한지 실측 — 위 예시 길이 측정 부탁
  3. 어떤 줄을 합치거나 줄일 수 있나

### G. Streamlit Cloud 보안/안정성
- `chaemink2/mint` repo public 전환 (Streamlit 무료 plan 호환)
- DATABASE_URL은 Streamlit secrets에만 (코드 X)
- mint_lgbm.joblib (138KB) repo commit
- 검토 포인트:
  1. **public repo에 commit된 것 중 secret 노출 흔적**: git log 전체 grep 권장 — REST_API_KEY/APP_SECRET/access_token/refresh_token/postgresql://
  2. **mint_lgbm.joblib commit**: 모델 자체는 학습된 weights — 무해. 다만 학습 데이터 정보는 누설 안 됨
  3. **Streamlit Cloud secrets TOML**: 로그에 마스킹되나 — 에러 발생 시 traceback에 노출 가능성

### H. 다음 카드 우선순위 (사용자 결정 보조용)
1주 운영 데이터(outcome 0~10건 추정) 후 다음 작업으로 어느 것이 ROI 최고일지 의견:
- **카드 m** (재학습): regime feature 추가 + dynamic exit outcome으로 회귀 모델 시도. 가장 큰 도약 가능성 + 가장 큰 리스크
- **카드 C**: 추가 regime feature (외국인/기관 수급, 섹터 강도, VKOSPI). market_regime 보강
- **카드 D**: 페이퍼 트레이딩 (가상 매수 → 가상 outcome). 실 카카오페이 수동 매매와 별개로 알고리즘 평가용
- **P1~P4** (OPERATION_WEEK1.md): 지수 표시 오류 (사실 시뮬레이션 환경이라 false alarm 가능), UTC vs KST dedup, mint/requirements.txt qlib 청소, funnel passed_risk 패턴
- **카드 N**: dynamic_exit 휴리스틱의 데이터 기반 calibration (현재 임의 multiplier 값을 outcome 데이터로 fit)

## 검토 결과 출력
`mint/REVIEW_CURSOR.md` 끝에 `# 📨 Cursor 4차 검토 (2026-05-XX)` 섹션으로 append.
승인된 사항만 다음 라운드에 코드 반영. CLAUDE.md / CURSOR.md / OPERATION_WEEK1.md는 직접 수정 자제.

---

*5/23 4차 검토 요청. 코드 변경 없음.*
