# Mint Cloud 운영 1주 검증 플레이북 (2026-05-22 ~ 2026-05-28)

> **상황**: Cloud Migration Phase 1+2+4 코드 + 배포 완료 (`5fab66d`, `649c4cd`).
> 사용자 액션 8단계 중 1~6 완료. 7(1주 모니터링) 진행 중, 8(스케줄러 비활성)은 5/28~29 예정.
> 이 문서는 사용자/Claude/Cursor 누가 봐도 5/22~28 동안 무엇을 봐야 하고, 무엇을 알려야 하는지의 단일 출처.

---

## 🎯 현재 시스템 상태 (5/22 14:00 KST 기준)

### 어디서 무엇이 도는가
| 컴포넌트 | 어디 | 트리거 | 무엇 |
|---|---|---|---|
| **DB** | Neon Postgres (Singapore) | 24/7 (scale-to-zero) | signals, positions, trades, auth_tokens, app_state |
| **scan-kr** | GHA cron | 평일 09:00~15:50 KST 10분 간격 (`*/10 0-6 * * 1-5` UTC) | KOSPI/KOSDAQ 200종목 룰+ML+분봉 |
| **daily-summary** | GHA cron | 평일 15:35 KST (`35 6 * * 1-5` UTC) | outcome 평가 + 카톡 일일 요약 |
| **outcomes** | GHA cron | 평일 23:30 KST (`30 14 * * 1-5` UTC) | 24h 경과 시그널 outcome 평가 |
| **scan-us** | GHA cron | 평일 NY 정규장 KST 22:30~05:50 (`*/10 13-21 * * 1-5` UTC) | NASDAQ 171종목 룰+ML (분봉 OFF, 2026-05-27 활성화) |
| **대시보드** | Streamlit Cloud | 24/7 (1주 inactive sleep) | `https://chaemink2-mint.streamlit.app` |
| **로컬 작업 스케줄러** | Windows 데스크탑 | 평일 08:30 + 10분 / 15:35 | **5/28까지 backup으로 유지**, 그 후 Disable |

### 운영 환경변수 (GHA workflow에 인라인)
```yaml
MINT_USE_ML_CONFIDENCE: 'true'
MINT_USE_MINUTE_RULE:   'true'
MINT_MIN_ML_CONFIDENCE: '0.60'
MINT_MIN_MINUTE_VOL_SPIKE: '2.0'
MINT_WATCHLIST_SIZE:    '200'
MINT_MAX_RISK_SCORE:    '45'
```

### 🆕 2026-05-22 추가: 지수 추종 + Dynamic Exit
**ML 모델은 그대로** (binary "24h +3% 도달 여부" 분류). 시그널 통과 후 post-processing layer 2개 추가:

- **engine/market_regime.py** — KOSPI/KOSDAQ 시장별 regime 5단계 (STRONG_BULL/BULL/SIDEWAYS/BEAR/STRONG_BEAR). yfinance ^KS11/^KQ11 일봉 + 5d/20d/MA20 종합 score. 60s 캐시.
- **engine/dynamic_exit.py** — 종목 ATR + 시장 regime → target/stop/hold 동적 계산.
  - base target = ATR × 1.5, base stop = -ATR × 1.0, base hold = 24h
  - regime multiplier (target/stop/hold):
    - STRONG_BULL: ×1.5 / ×0.7 / ×1.5 (길게 잡고 작은 stop)
    - BULL: ×1.2 / ×0.85 / ×1.25
    - SIDEWAYS: ×1.0 / ×1.0 / ×1.0
    - BEAR: ×0.75 / ×0.9 / ×0.75
    - STRONG_BEAR: ×0.5 / ×0.85 / ×0.5
  - cap: target 1.5~15% / stop 0.5~5% / hold **6~72h** (사용자 결정)
- DB 마이그레이션: signals/positions 각각 `max_hold_hours REAL` + `regime_label TEXT` 컬럼
- log_signal·open_position_from_signal·_evaluate_single_outcome·exit_strategy 모두 시그널별 max_hold 사용
- 카톡 시그널/미드데이/하트비트/일일요약 + 대시보드에 regime 표시
- NASDAQ은 미적용 (기존 고정값 사용 — yfinance regime은 KOSPI/KOSDAQ만)

### 모델
- 5/19c 학습 (`mint/data/models/mint_lgbm.joblib`, 138KB, repo commit)
- 200종목 × 730일 LightGBM, AUC 0.582
- 임계값 0.60: 일평균 1.3건 시뮬, precision 0.79 (분봉 미반영)
- 분봉 추가 시 통과율 ~40% → 실제 일평균 0~1건 예상

---

## 🔍 매일 1분 모니터링 (5/22 ~ 5/28)

### 사용자가 체크할 것

#### 🌅 아침 (한 번)
- [ ] **09:00 시작 후 카톡 하트비트** 도착했는지 — Mint 동작 신호 (없으면 GHA 첫 cron 지연/실패)

#### 🌞 점심
- [ ] **12:00 미드데이 ping 카톡** 도착했는지
  - 정상: "오늘 funnel — 평가/모멘텀/리스크/.../시그널" 요약
  - funnel 0건 단계 안내 — 어디서 막혔는지

#### 📈 장중 (시그널 발생 시만)
- [ ] **매수 시그널 카톡** 도착하면 메시지 캡처
  - STALE 마커 확인: ⚠️ 엔트리 늦음 / 💡 더 좋은 진입 / ✓ 신선
  - 종목/타이밍 노트
  - **실 카카오페이로 매수까지 갔나** 수기 기록 (안 가도 OK)
- [ ] **만료 카톡** 도착 시 (TIME / TARGET_HIT / STOP_HIT)

#### 🌙 장 마감 후
- [ ] **15:35 일일 요약 카톡** 도착 — 그날 시그널 수, 누적 win rate, funnel 마감
- [ ] **23:30 outcomes 워크플로우** 자동 실행 (카톡 없음, GHA Actions 탭에서만 확인)

#### 💻 (선택) 대시보드 1회 열기
- https://chaemink2-mint.streamlit.app
- funnel 누적 / 시그널 / 포지션 / 모델 분석 페이지
- 1주 inactivity sleep 방지 효과

#### 🚦 GHA Actions 탭 — 5초 스캔
- https://github.com/chaemink2/mint/actions
- 빨간 X 없으면 OK
- 있으면 1순위로 보고

### Claude/Cursor가 다음 세션 시작 시 받을 정보 (사용자 인계용)

다음 세션에서 가장 먼저 확인할 정보 — 사용자가 기억나는 만큼 알려주면 됩니다:

```
1주 모니터링 결과 (5/22~5/28):
- 일평균 시그널 수: X건 (예상 0~2건)
- 실 카카오페이로 매수까지 간 종목: X개 (없으면 0)
- 자동 outcome 평가 결과: WIN X / LOSS X / TIME_EXIT X
- STALE 빈도: ⚠️ 자주? / ✓ 위주?
- funnel 패턴 어디서 막힘: 모멘텀? ML? 분봉?
- GHA 빨간 X 빈도: 0회 / 며칠 / 매일
- 카톡 도착 빈도/지연 체감: 정시 / 지연 / 종종 누락
- 대시보드 사용성 의견
- 그 외 사용 중 느낀 점
```

---

## 🐛 알려진 이슈 / 점검 노트 (다음 세션 우선순위)

### ~~P1 — 시장 지수 표시 오류~~ ✅ 2026-06-02 closed (코드 무결성 재검증)
- ~~증상~~: 5/22 시점 KOSPI 7,815 (+8.42%) — 그 당시엔 실 표시 오류였을 가능성 있음
- **6/2 재검증 결과**: [data/market_index.py](data/market_index.py) 파싱 로직 **이상 없음**. 라인별 점검 + 3-source cross-check 통과
  - Naver 모바일 basic API · Naver polling API · Yahoo `^KS11` 모두 KOSPI 8,801.49 동일 반환 (6/2 종가). KOSPI는 5/27 8,228 → 6/2 8,801로 상승한 상태
  - 사용자 카톡 리포트 "KOSPI 8,596.85 (-2.18%)"는 오늘 intraday 범위(8,503~8,933) 안 합법 tick (어제 종가 8,788.38 대비 정확히 -2.18%)
  - "nv/nf 필드" 가설은 검증 없이 적힌 추정이었음 — 실제 Naver API는 `closePrice`/`fluctuationsRatio`/`compareToPreviousClosePrice`/`compareToPreviousPrice.code` full key 사용, 코드와 정확히 일치
- **현재 파싱 robustness**: `_direction_sign` marker 기반 부호 적용 + reported vs computed pct self-consistency 검증(0.05pp tolerance)으로 양쪽 스키마(UP=부호없음, DOWN=부호있음) 모두 정상 처리
- **재현**: `python -X utf8 -c "import sys; sys.path.insert(0,'mint'); from data.market_index import get_market_summary, format_summary_line; print(format_summary_line())"` (이전 노트의 `fetch_summary`는 함수명 오타 — 실제는 `get_market_summary`)

### ~~P2 — UTC vs KST dedup 키 잠재 이슈~~ ✅ 2026-05-23 해결 (R1+R2, `8c43e1c`)
- ~~증상~~: 5/21 KST 23~00시 사이에 daily-summary GHA 실행 시 dedup 키가 UTC date 기준이라 발생
- **해결**: notifier의 4개 dedup 키 (`scan_stats_{today}`, `last_heartbeat_date`, `last_midday_date`, `last_summary_date`) 모두 `config.tz.today_kst()` 일원화. main.py:cmd_daily_summary와 rule_scanner:run_rule_scan의 today_start도 KST. maybe_send_midday_ping의 시각 비교는 `now_kst()`.
- **잔여 (R7 후보)**: portfolio/db.py의 `datetime.now().isoformat()` (created_at 등 timestamp 저장) — KST 보장 안 됨. 비교 양 측이 같은 timezone이라 현재 동작은 OK이나 ad-hoc 쿼리 시 혼동 가능. 운영 데이터 누적 시 검토.

### P3 — Streamlit Cloud Build에 qlib 시도 흔적
- **증상**: 처음 배포에서 plotly ModuleNotFoundError → mint/requirements.txt의 qlib 빌드 실패가 원인
- **상태**: `mint/dashboard/requirements.txt` 별도 생성으로 해결 (`649c4cd`)
- **후속 작업**: `mint/requirements.txt`에서도 qlib/torch 제거 검토 (학습 안 하는 한 dead weight)
- **작업량**: 5분

### P4 — KOSPI/KOSDAQ funnel `passed_risk=0` 패턴 검증
- **5/21 진단 후 변경**: max_risk_score 30 → 45
- **5/22 결과 (대시보드 캡처)**: 평가 392 → 모멘텀 53 → 리스크 27 → 거래량 16 → 시그널 0
- **해석**: risk 게이트 풀림(53→27, 49% 통과), volume 게이트 OK(27→16, 59%), 분봉/ML에서 0건
- **다음 세션 점검**: 1주 누적 후 ML/분봉 통과 패턴이 0이 지속되면 분봉 vol_spike 2.0 더 완화 검토

---

## 🌎 NASDAQ 확장 (별도 작업)

별도 Claude Code Chat 세션에서 진행. 단일 출처: **`mint/HANDOFF_NASDAQ.md`**.
- Stage 1 인프라 (워치리스트 동적화, regime/dynamic exit/outcome NASDAQ 분기) 4~6h
- Stage 2 ML 학습 (NASDAQ 전용 모델) 6~10h
- Stage 3 백테스트 + 1주 시범 운영
- 진행 전 사용자 합의 4가지 (ML 전략 / 분봉 / 진입 시점 / 운영 의향) — 별도 세션이 받음

KR 운영은 무영향. NASDAQ 변경 시 KR 모델/스키마/workflow 보호 (HANDOFF_NASDAQ.md "변경 시 주의사항" 참조).

---

## 🎯 1주 후 (5/29 ~ ) 의사결정 포인트

### 우선순위 (Cursor 4차 검토 권고 반영, 2026-05-23)
**Cursor 권고 순서: P2(해결됨) → 카드 N(dynamic exit calibration) → 카드 D(페이퍼) → 카드 m(재학습)**

1. ✅ **P2 (UTC vs KST dedup)** 해결 (5/23 R1+R2)
2. **카드 N — Dynamic Exit calibration (Cursor 권고 1순위)**. 현재 multiplier(1.5/0.7/1.5 등)는 임의 휴리스틱 — outcome 데이터로 fit. 데이터 누적 후 진입.
3. **카드 D — 페이퍼 트레이딩 인프라**. 가상 매수 → 가상 outcome. 실 카카오페이와 별개로 알고리즘 평가용. 카드 N과 결합 시너지.
4. **카드 m — 재학습** (regime feature + dynamic exit outcome 라벨로). 가장 큰 도약 카드. outcome 30건+ 누적 후.
5. **Step 8 — Windows 작업 스케줄러 Disable** (GHA 안정 확인 후).
6. **카드 C 보강** — 외국인/기관 수급, 섹터, VKOSPI. market_regime 정밀도 ↑.
7. **NASDAQ 야간 활성화** — scan-us.yml cron 주석 해제. 사용자 결정 시.

### Cursor 4차 정직성 메모 (다음 세션 인지 필수)
- **AUC 0.582 / precision 0.79는 분봉·dedup·dynamic exit 적용 전 val 수치**. live 승률로 그대로 인용하면 과장.
- **ML은 "고정 +3.5%/-2%/24h exit에 이길 확률"을 학습**, 실전은 dynamic exit. 라벨 불일치 = 카드 m 재학습 동기.
- **hold 6~72h 적용해도 일봉 outcome 평가는 사실상 24h** (horizon_h // 24). 카톡·DB는 dynamic, 평가는 일봉 first-hit. 분봉 outcome 인프라 미구축.

---

## 🔧 디버깅 명령 모음 (사용자/Claude/Cursor 공용)

### 환경변수
```powershell
$env:DATABASE_URL = "postgresql://neondb_owner:실제비밀번호@ep-purple-sky-a00j28fz-pooler.c-2.ap-southeast-1.aws.neon.tech/neondb?sslmode=require"
# 작업 끝나면: Remove-Item Env:\DATABASE_URL
```

### Neon DB 상태 점검
```powershell
# 시그널 + outcome
python -X utf8 -c "import sys; sys.path.insert(0,'mint'); from portfolio.db import get_conn; from sqlalchemy import text; from datetime import datetime, timedelta; since = (datetime.now() - timedelta(days=7)).isoformat(); c = get_conn().__enter__(); rows = c.execute(text('SELECT id, ticker, name, status, outcome, created_at FROM signals WHERE created_at >= :since ORDER BY id DESC'), {'since': since}).fetchall(); [print(dict(r._mapping)) for r in rows]"

# Outcome 통계
python -X utf8 -c "import sys; sys.path.insert(0,'mint'); from portfolio.db import get_outcome_stats; print('7d:', get_outcome_stats(7)); print('30d:', get_outcome_stats(30))"

# Funnel 통계 (최근 며칠)
python -X utf8 -c "import sys, json; sys.path.insert(0,'mint'); from portfolio.db import get_app_state; raw = get_app_state('notifier_state'); s = json.loads(raw) if raw else {}; [print(k, s[k]) for k in sorted(s) if 'scan_stats' in k]"

# 카카오 토큰 상태
python -X utf8 -c "import sys; sys.path.insert(0,'mint'); from portfolio.db import get_auth_token; r = get_auth_token('kakao'); print('access head:', r['access_token'][:15] if r else None, 'expires:', r['expires_at'] if r else None)"
```

### GHA 수동 trigger
- Daily Summary: https://github.com/chaemink2/mint/actions/workflows/daily-summary.yml → Run workflow
- KR Scan: https://github.com/chaemink2/mint/actions/workflows/scan-kr.yml → Run workflow
- Outcomes: https://github.com/chaemink2/mint/actions/workflows/outcomes.yml → Run workflow

### dedup 키 리셋 (특정 일자 카톡 재발송 원할 때)
```powershell
python -X utf8 -c "import sys, json; sys.path.insert(0,'mint'); from portfolio.db import get_app_state, set_app_state; raw = get_app_state('notifier_state'); s = json.loads(raw) if raw else {}; s.pop('last_summary_date', None); s.pop('last_heartbeat_date', None); s.pop('last_midday_date', None); set_app_state('notifier_state', json.dumps(s, ensure_ascii=False)); print('dedup 키 제거')"
```

### Streamlit Cloud reboot
- https://share.streamlit.io → My apps → 앱 ⋮ → Reboot

### 로컬 작업 스케줄러 (5/28 이후)
```powershell
# 비활성
Disable-ScheduledTask -TaskName 'Mint Signal Scan'
Disable-ScheduledTask -TaskName 'Mint Daily Note'

# 재활성 (롤백 시)
Enable-ScheduledTask -TaskName 'Mint Signal Scan'
Enable-ScheduledTask -TaskName 'Mint Daily Note'

# 상태 확인
Get-ScheduledTask | Where-Object {$_.TaskName -like '*Mint*'} | Select-Object TaskName, State, LastRunTime, LastTaskResult, NextRunTime
```

---

## 🆘 1주 운영 중 흔한 이슈 → 대응

| 증상 | 1순위 의심 | 대응 |
|---|---|---|
| 평일 09시 후 카톡 무음 | GHA 첫 cron 지연 (수~십수 분 정상) | 10:00까지 기다림. 그래도 무음이면 Actions 탭 빨간 X 확인 |
| 카톡 일부 누락 (예: 미드데이만) | dedup 키 잘못 |  `last_midday_date` 등 dedup 키 확인 |
| 모든 GHA 빨강 | KIS IP 제한 부활 / Neon 한도 초과 / Secret 만료 | 첫 빨간 X 로그 확인 |
| Streamlit 빈 화면 | Neon scale-to-zero cold start | 30초 후 새로고침 |
| 카카오 토큰 만료 안내 카톡 | refresh_token 60일 만료 (5/18 발급 → 7월 중순 만료) | 로컬에서 `python mint/notifier/setup_kakao.py` 재실행 → DB 자동 마이그레이션 |
| 시그널이 매일 0건 | 1주는 정상. 2주+면 임계값 검토 | funnel 어디서 막히는지 패턴 분석 |

---

## 📌 다음 세션 픽업 (Claude/Cursor)

### 첫 행동
```powershell
# 1) 1주 운영 데이터 확인
$env:DATABASE_URL = "postgresql://..."  # Neon URL (사용자에게 받기)

python -X utf8 -c "import sys; sys.path.insert(0,'mint'); from portfolio.db import get_outcome_stats, get_conn; from sqlalchemy import text; print('30d outcome:', get_outcome_stats(30)); c = get_conn().__enter__(); rows = c.execute(text('SELECT COUNT(*), status FROM signals GROUP BY status')).fetchall(); [print(dict(r._mapping)) for r in rows]"

python -X utf8 -c "import sys, json; sys.path.insert(0,'mint'); from portfolio.db import get_app_state; raw = get_app_state('notifier_state'); s = json.loads(raw) if raw else {}; [print(k, s[k]) for k in sorted(s) if 'scan_stats' in k]"

Remove-Item Env:\DATABASE_URL

# 2) GHA 1주 실행 이력
gh run list --workflow=scan-kr.yml --limit 50
gh run list --workflow=daily-summary.yml --limit 7
gh run list --workflow=outcomes.yml --limit 7

# 3) 사용자 피드백 수렴 — 위 "사용자 인계용" 섹션의 질문
```

### 우선순위 결정 분기
- **outcome 30건 이상** → 카드 m (재학습) 진행
- **outcome 10~30건** → P1/P3 이슈 처리 + 다음 주 운영 계속
- **outcome 0~10건** → P1/P2/P3 이슈 처리 + 시그널 빈도 디버깅 (분봉 vol_spike, ML 임계값)
- **GHA 안정** → Step 8 (사용자가 작업 스케줄러 Disable) 합의
- **GHA 자주 빨강** → 원인 분석 우선

### 변경 금지 사항 (사용자 결정)
- 매매 채널은 카카오페이증권 수동 — KIS 실주문 모드 X
- 알림은 카카오톡 "나에게 보내기"
- 1일 +3% 전략 임계값은 사용자 확정 (변경 시 사용자 승인)
- `MINT_WATCHLIST_SIZE=200`, `MINT_MAX_RISK_SCORE=45` (5/21 결정)

---

*이 문서는 Cloud Migration 배포 직후(2026-05-22) 작성. 1주 운영 결과는 다음 세션에서 추가/대체.*
