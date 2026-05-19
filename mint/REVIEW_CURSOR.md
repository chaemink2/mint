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
