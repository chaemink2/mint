# Mint Cloud Migration 가이드

> **상태**: 미래 작업 — 아직 미실행. 5/20 작성 (reference 문서).
> **트리거 조건**: PC 24/7 운영이 불편해지거나, NASDAQ 야간 스캔까지 안정 운영이 필요해질 때.
> **현재 운영**: Windows 데스크탑 + 작업 스케줄러 (월 전기료 ~1만원).

---

## 🎯 목표

PC 꺼져 있어도 다음이 자동 동작:
1. **평일 한국장 (09:00~15:30 KST)** — 10분 간격 룰+ML+분봉 scan
2. **평일 미국장 (22:30~05:00 KST)** — 10분 간격 NASDAQ scan (현재 OFF, 활성화 시)
3. **카카오톡 알림** — 시그널/만료/매도/하트비트/미드데이/일일 요약
4. **대시보드** — 휴대폰/외부에서 언제든 접근
5. **Outcome 자동 평가** — 24h 지난 시그널 매일

---

## 🏗️ 목표 아키텍처

```
┌─────────────────────────────────────────────────────────────┐
│  GitHub Actions cron (UTC 기준 변환)                         │
│  - KR scan: 평일 00:00~06:30 UTC (= 09:00~15:30 KST) /10min  │
│  - US scan: 평일 13:30~20:00 UTC (= 22:30~05:00 KST) /10min  │
│  - daily-summary: 평일 06:35 UTC (= 15:35 KST)               │
│  - outcomes:      평일 매일 1회                              │
└────────────────────┬────────────────────────────────────────┘
                     │ python mint/main.py {scan|daily-summary|outcomes}
                     ↓
┌─────────────────────────────────────────────────────────────┐
│  Supabase Postgres (mint.db 대체)                            │
│  - signals / positions / trades                              │
│  - kakao_tokens / kis_tokens (파일 → DB row)                  │
│  - scan_state (last_heartbeat/midday/summary date 등)        │
│  - 무료 500MB (1년치 시그널 충분)                            │
└────────────────────┬────────────────────────────────────────┘
                     │
       ┌─────────────┴──────────────┐
       │                            │
       ↓                            ↓
┌──────────────┐         ┌─────────────────────┐
│ Kakao API    │         │ Streamlit Cloud      │
│ (메시지 전송) │         │ (dashboard/app.py)   │
└──────────────┘         │ 폰/PC 브라우저        │
                         └─────────────────────┘
```

---

## 📦 컴포넌트별 상세

### 1. Cron — GitHub Actions

**장점**: 무료 (public repo 무제한, private 월 2000분), 코드 push로 자동 trigger.
**한계**: cron 실행 지연 (수 분 ~ 수십 분, 무료 한도). 분당 실시간성은 X.

`.github/workflows/scan-kr.yml`:
```yaml
name: Mint KR Scan
on:
  schedule:
    - cron: '*/10 0-6 * * 1-5'  # UTC. 평일 KST 09:00~15:30 = UTC 00:00~06:30
  workflow_dispatch:  # 수동 실행
jobs:
  scan:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: '3.13'
      - run: pip install -r mint/requirements.txt
      - run: python -X utf8 mint/main.py scan
        env:
          DATABASE_URL: ${{ secrets.DATABASE_URL }}
          KAKAO_REST_API_KEY: ${{ secrets.KAKAO_REST_API_KEY }}
          KIS_APP_KEY: ${{ secrets.KIS_APP_KEY }}
          KIS_APP_SECRET: ${{ secrets.KIS_APP_SECRET }}
          MINT_USE_ML_CONFIDENCE: 'true'
          MINT_USE_MINUTE_RULE: 'true'
          MINT_MIN_ML_CONFIDENCE: '0.60'
```

별도 workflow: `scan-us.yml`, `daily-summary.yml`, `outcomes.yml`.

**대안**: Railway/Render의 cron 기능 — 더 안정적이지만 월 $5~10.

### 2. DB — Supabase Postgres

**왜 Postgres?**
- SQLite는 파일 기반 — GitHub Actions 매 호출마다 새 컨테이너이므로 영구 X
- Cloud SQLite는 동시성 문제

**선택지**:
- **Supabase** — 무료 500MB, 7일 백업, REST API 보너스
- **Neon** — 무료 3GB, branching 가능, 가장 안정적
- **Railway Postgres** — 월 $5 (cron과 통합 시 편함)
- **Turso (libSQL)** — sqlite API 호환, 무료 + 분산

**추천**: Supabase 또는 Neon (마이그레이션 시 sqlite와 가장 유사한 인터페이스).

### 3. 코드 변경 — DB 추상화

`portfolio/db.py` 변경:
```python
# Before:
import sqlite3
def get_conn(): return sqlite3.connect(DB_PATH)

# After (sqlalchemy 추천):
from sqlalchemy import create_engine
import os
ENGINE = create_engine(os.getenv("DATABASE_URL", f"sqlite:///{DB_PATH}"))
def get_conn(): return ENGINE.begin()
```

장점: `DATABASE_URL=sqlite:///mint.db` 로 로컬 그대로 운영 가능 (개발 환경 호환).

쿼리 문법:
- SQLite: `?` placeholder
- Postgres: `%s` placeholder
- SQLAlchemy 사용 시 둘 다 호환 (`text()` 또는 ORM)

마이그레이션 작업량: **2~3시간**. 모든 SQL을 SQLAlchemy `text()` 로 감싸기 + 로컬 sqlite 호환 검증.

### 4. 토큰 영속화 — 파일 → DB

현재:
- `data/.kakao_token.json` (access_token, refresh_token, expires_at)
- `data/.kis_token.json`
- `data/.notifier_state.json` (last_heartbeat_date 등)

GitHub Actions는 매 호출마다 새 컨테이너 → 파일 시스템 휘발. **DB row로 옮겨야 함**.

새 테이블:
```sql
CREATE TABLE auth_tokens (
    service TEXT PRIMARY KEY,  -- 'kakao' | 'kis'
    access_token TEXT,
    refresh_token TEXT,
    expires_at TIMESTAMP,
    refresh_expires_at TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE app_state (
    key TEXT PRIMARY KEY,  -- 'last_heartbeat_date_2026-05-20' 등
    value TEXT,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

토큰 로딩/저장 함수만 변경. 작업량 **1시간**.

### 5. 모델 파일 — `mint_lgbm.joblib`

크기: 보통 100KB~1MB. 옵션:
- **git에 commit** (gitignore에서 제외) — 가장 단순
- **GitHub Release artifact** — 버전 관리 가능
- **S3/Supabase Storage** — 큰 모델 시
- **Base64로 DB에 저장** — 작은 모델이면 OK

추천: git에 commit (현재 `*.joblib` ignored이지만 `mint_lgbm.joblib`만 unignore).

### 6. Secrets

GitHub Secrets에 등록:
```
DATABASE_URL                # postgresql://...
KAKAO_REST_API_KEY
KAKAO_REDIRECT_URI = https://localhost
KIS_APP_KEY
KIS_APP_SECRET
```

Streamlit Cloud secrets (대시보드 읽기 전용):
```
DATABASE_URL                # 같은 DB
```

### 7. 대시보드 — Streamlit Cloud

배포 단계:
1. https://streamlit.io/cloud → GitHub repo 연결
2. main 파일: `mint/dashboard/app.py`
3. Python 버전 + requirements.txt 자동
4. secrets에 DATABASE_URL 등록
5. URL: `https://[app-name].streamlit.app`

**한계**:
- Streamlit Cloud 무료 플랜은 매월 inactivity sleep — 1주일 사용 안 하면 잠시 cold start
- 풀 production이면 Railway 등 paid 권장

---

## 🛠️ 마이그레이션 단계 (4~8 시간)

### Phase 1: DB 추상화 (2h)
- [ ] `portfolio/db.py` 를 SQLAlchemy로 리팩터
- [ ] `DATABASE_URL` env 처리 (없으면 로컬 sqlite)
- [ ] 모든 SQL을 `text()` 또는 ORM으로
- [ ] 로컬에서 sqlite + postgres 둘 다 동작 확인 (docker-compose)

### Phase 2: 토큰/상태 영속화 (1h)
- [ ] `auth_tokens`, `app_state` 테이블 마이그레이션
- [ ] `notifier/kakao.py` `_load_tokens` / `_save_tokens` 를 DB로
- [ ] `data/kis_client.py` 토큰 캐시 DB로
- [ ] `notifier/__init__.py` `_load_state` / `_save_state` 를 DB로

### Phase 3: Postgres 인스턴스 (30분)
- [ ] Supabase 가입 + project 생성
- [ ] DATABASE_URL 복사
- [ ] 로컬에서 `DATABASE_URL=postgres://...` 로 일회성 마이그레이션 실행
- [ ] 기존 sqlite 데이터 dump → postgres import (`pg_loader` 또는 직접 INSERT)

### Phase 4: GitHub Actions workflow (1~2h)
- [ ] `.github/workflows/scan-kr.yml` 작성 + secrets 등록
- [ ] `scan-us.yml`, `daily-summary.yml`, `outcomes.yml`
- [ ] 한 번 manually trigger 후 로그 확인 — 카톡 도착 확인
- [ ] Cron 시간대 검증 (UTC ↔ KST)

### Phase 5: Streamlit Cloud 배포 (30분)
- [ ] streamlit.io/cloud → GitHub repo
- [ ] secrets 등록
- [ ] URL 받고 폰 북마크

### Phase 6: PC 운영 전환 (5분)
- [ ] Windows 작업 스케줄러의 `Mint Signal Scan` 작업 비활성화 (삭제는 아직 X)
- [ ] 클라우드 운영 1주일 검증 후 PC OFF 가능

---

## 💰 비용 추정

| 컴포넌트 | 무료 한도 | 초과 시 |
|---|---|---|
| GitHub Actions | public repo 무제한, private 월 2000분 | $0.008/분 |
| Supabase Postgres | 500MB, 2GB 트래픽 | Pro 월 $25 |
| Neon Postgres | 3GB | $19/월부터 |
| Streamlit Cloud | 무제한 (sleep 있음) | 미지원 |
| KIS API | 일/분 호출 한도 | — |
| 카카오 API | 일 무료 한도 (충분) | — |

**예상**: 1년 운영 시 무료 한도 내. 시그널 양 폭증 시 Supabase Pro 또는 Railway $5/월.

---

## ⚠️ 주의/위험

### Cron 실행 지연
GitHub Actions cron은 UTC 기준 정확한 시각이 아닌 **지연 가능** (특히 정각 부근 부하 몰림). 5분 늦어도 시그널 품질엔 큰 영향 X (일봉 기반이라).

### KIS API IP 제한
KIS 콘솔에서 IP 제한을 켰다면 GitHub Actions IP 범위에서 호출 실패. **IP 제한 OFF 필수** (보안은 secret 자체로 충분).

### 토큰 동시성
같은 시점에 여러 GitHub Actions job이 토큰 갱신 시도하면 race condition. 옵션:
- 한 workflow에서 직렬 처리 (`concurrency: { group: 'kakao-token', cancel-in-progress: false }`)
- DB에 advisory lock

### Sqlite ↔ Postgres 동작 차이
- DATE() 함수 (sqlite) vs DATE_TRUNC() (postgres)
- AUTOINCREMENT vs SERIAL
- 적당히 호환 가능한 SQL 작성 + 양쪽 모두 테스트

### 시간대 (TZ)
GitHub Actions = UTC. main.py 내부 `datetime.now()` 도 UTC. Asia/Seoul 변환 필요한 곳:
- 영업일 판정 (월~금)
- 한국장 운영시간 (09:00~15:30 KST)
- `created_at` 등 사용자 표시
- 작업 스케줄러 cron 변환

`config/settings.py` 또는 `utils.py` 에 `KST = ZoneInfo('Asia/Seoul')` 정의 + 일관 사용.

### NASDAQ 통합 (미래)
사용자 명시: NASDAQ 야간 스캔까지 운영. 현재 us_client (yfinance) 있고 NASDAQ 워치리스트 있음. 클라우드 마이그레이션 후 활성화하면 야간 자동 스캔 + 카톡 도착.

야간 시간대 cron:
- US 정규장: UTC 13:30~20:00 (KST 22:30~05:00)
- Pre/After-hours까지 보려면 cron 확대

---

## 📝 권장 마이그레이션 시점

다음 중 하나가 사실이 되면 시작:
1. PC 24/7 운영이 불편해짐 (전기료/소음/이사)
2. 데스크탑 외 다른 장치에서도 운영하고 싶음
3. NASDAQ 야간 스캔까지 안정 운영 필요
4. outcome 데이터 1~2개월 이상 누적 → 모델 재학습도 클라우드에서 자동화

그 전까지는 현재 운영(Windows 작업 스케줄러 + Tailscale 옵션)이 가성비 best.

---

## 🔗 참고

- GitHub Actions cron: https://docs.github.com/en/actions/using-workflows/events-that-trigger-workflows#schedule
- Supabase Python: https://supabase.com/docs/reference/python/initializing
- SQLAlchemy + sqlite/postgres: https://docs.sqlalchemy.org/en/20/dialects/
- Streamlit Cloud 배포: https://docs.streamlit.io/streamlit-community-cloud
- KIS Developers: https://apiportal.koreainvestment.com
