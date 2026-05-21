# Mint Cloud Migration — 사용자 액션 가이드

> **2026-05-21 기준** · Phase 1+2+4 코드 완료(`b7afcc1`, `4fb61ec`).
> 이 가이드의 단계 따라가면 약 30~60분 안에 PC OFF + 클라우드 운영 시작.
> 참고: 큰 그림은 [CLOUD_MIGRATION.md](CLOUD_MIGRATION.md).

---

## ⚡ 한 줄 요약

1. **Neon DB 가입** (10분) → `DATABASE_URL` 복사
2. **GitHub Secrets 등록** (10분) → DB URL + 카톡/KIS 키
3. **GHA workflow 활성화** (5분) → manual trigger로 1회 검증
4. **Streamlit Cloud 배포** (15분) → 폰 북마크
5. **로컬 Windows 작업 스케줄러 비활성** (5분, 1주일 검증 후)

총 **30~60분** 셋업 + **1주일 검증 운영**.

---

## ✅ 사전 체크리스트

- [ ] commit `4fb61ec` push 완료 (사용자 push 권한)
- [ ] KIS 콘솔에 IP 제한 OFF (GitHub Actions 동적 IP에서 호출)
- [ ] 카카오 디벨로퍼스 redirect URI에 `https://localhost` 또는 운영 도메인 등록 확인

---

## Phase 3 — Neon DB 가입 + DATABASE_URL (10분)

1. **회원가입**: https://console.neon.tech → GitHub OAuth 권장
2. **Project 생성**:
   - Name: `mint`
   - Region: AWS `ap-northeast-2` (서울) 또는 `us-east-1` (속도 차이 미미)
   - Postgres 버전: 최신 (16+)
3. **Connection string 복사**:
   - Dashboard → Project → **Connection Details** → "Pooled connection" 선택
   - 형식: `postgresql://user:pass@ep-xxx-pooler.ap-northeast-2.aws.neon.tech/neondb?sslmode=require`
   - ⚠️ `pooler` 들어간 URL 사용 (Serverless 호환). 일반 URL은 connection limit 낮음.
4. **DATABASE_URL 보관**: 다음 단계에서 GitHub Secrets에 등록

### (선택) 로컬 → Neon 데이터 마이그레이션

기존 운영 5/19 시그널 2건 등을 옮기려면:

```powershell
# 1. 로컬 sqlite 덤프 (signals/positions/trades/auth_tokens/app_state)
cd "C:\Users\USER\OneDrive\바탕 화면\workspace"
python -X utf8 -c "
import sys; sys.path.insert(0,'mint')
from portfolio.db import get_conn, init_db
import json
init_db()
with get_conn() as c:
    from sqlalchemy import text as t
    out = {}
    for tbl in ['signals','positions','trades','auth_tokens','app_state']:
        rows = c.execute(t(f'SELECT * FROM {tbl}')).fetchall()
        out[tbl] = [dict(r._mapping) for r in rows]
import json; json.dump(out, open('mint_dump.json','w',encoding='utf-8'), ensure_ascii=False, indent=2, default=str)
print('dumped:', {k:len(v) for k,v in out.items()})
"

# 2. Neon에 import — DATABASE_URL을 임시로 Neon URL로 잡고 실행
$env:DATABASE_URL = "postgresql://..."  # 1단계에서 받은 URL
python -X utf8 -c "
import sys, json; sys.path.insert(0,'mint')
from portfolio.db import init_db, migrate_db, get_conn
from sqlalchemy import text
init_db(); migrate_db()
data = json.load(open('mint_dump.json',encoding='utf-8'))
with get_conn() as c:
    for tbl, rows in data.items():
        if not rows: continue
        cols = list(rows[0].keys())
        placeholders = ','.join(f':{k}' for k in cols)
        sql = f'INSERT INTO {tbl} ({\",\".join(cols)}) VALUES ({placeholders})'
        for r in rows:
            try: c.execute(text(sql), r)
            except Exception as e: print(f'skip {tbl}#{r.get(\"id\")}: {e}')
        print(f'{tbl}: {len(rows)} imported')
"
Remove-Item Env:\DATABASE_URL  # 원래 sqlite로 복귀
```

마이그레이션 안 해도 GHA가 새 시그널부터 정상 누적. outcome 5/19 LOSS 기록은 안 옮겨감.

---

## Phase 4b — GitHub Secrets 등록 (10분)

GitHub repo `chaemink2/mint` → **Settings** → **Secrets and variables** → **Actions** → **New repository secret**:

| Secret 이름 | 값 |
|---|---|
| `DATABASE_URL` | Phase 3에서 받은 Neon `postgresql://...?sslmode=require` |
| `KAKAO_REST_API_KEY` | 카카오 디벨로퍼스 → 앱 → REST API 키 (이미 로컬 env에 있는 값) |
| `KAKAO_REDIRECT_URI` | `https://localhost` (또는 설정한 값) |
| `KIS_APP_KEY` | KIS 콘솔 → APP_KEY |
| `KIS_APP_SECRET` | KIS 콘솔 → APP_SECRET |

⚠️ 비밀 키이므로 한 번 등록하면 GitHub UI에서 다시 볼 수 없음. 분실 시 재발급.

---

## Phase 4c — 카카오 토큰 DB로 이전 (5분)

GHA 환경은 휘발 컨테이너 → `.kakao_token.json` 파일이 없음. 로컬 sqlite의 `auth_tokens` 테이블에 이미 token이 있는데 (Phase 2에서 자동 마이그레이션 완료), 이걸 Neon Postgres에도 한 번 복사해야 함.

```powershell
# 로컬 DB의 kakao 토큰 → Neon에 복사
$env:DATABASE_URL = "postgresql://..."  # Neon URL
python -X utf8 -c "
import sys, sqlite3; sys.path.insert(0,'mint')
# 로컬 sqlite에서 직접 읽기 (DATABASE_URL은 Neon으로 설정됨)
import json
local = sqlite3.connect('mint/data/mint.db')
local.row_factory = sqlite3.Row
row = local.execute('SELECT * FROM auth_tokens WHERE service=\"kakao\"').fetchone()
local.close()
if row:
    d = dict(row)
    from portfolio.db import save_auth_token
    save_auth_token('kakao',
        access_token=d['access_token'],
        refresh_token=d['refresh_token'],
        expires_at=d['expires_at'],
        refresh_expires_at=d.get('refresh_expires_at'))
    print('카카오 토큰 Neon에 복사 완료')
else:
    print('로컬 DB에 카카오 토큰 없음')
"
Remove-Item Env:\DATABASE_URL
```

KIS 토큰은 매 호출 시 자동 발급되므로 옮길 필요 없음.

---

## Phase 4d — GHA workflow 1회 manual trigger (5분)

1. GitHub repo → **Actions** 탭 → 좌측에서 `Mint Daily Summary` 선택
2. 우측 상단 **Run workflow** → **Run**
3. 진행 상황 클릭 → 로그 확인 — 성공이면 카톡에 일일 요약 도착
4. 같은 방식으로 `Mint KR Scan` 한 번 trigger → 5~10분 소요 (200종목 fetch)

❌ 실패 시 로그 보고 secret 누락/오타 확인.

검증되면 cron으로 자동 실행됨 (KST 평일 09:00~15:50 / 15:35 / 23:30).

---

## Phase 5 — Streamlit Cloud 배포 (15분)

1. https://share.streamlit.io → GitHub OAuth로 로그인
2. **New app**:
   - Repo: `chaemink2/mint`
   - Branch: `main`
   - Main file path: `mint/dashboard/app.py`
   - Python: `3.13`
   - Requirements: 자동 감지 (mint/requirements.txt) — 안 되면 수동 지정
3. **Advanced settings** → **Secrets** (TOML 형식):
   ```toml
   DATABASE_URL = "postgresql://...?sslmode=require"
   ```
4. **Deploy** → 3~5분 대기 → URL 받음 (`https://[app].streamlit.app`)
5. 폰 북마크 → 외출 시 휴대폰에서 funnel/시그널/포지션 확인 가능

⚠️ 무료 플랜은 inactivity sleep — 1주일 미접속 시 cold start 30~60초.

---

## Phase 6 — Windows 작업 스케줄러 비활성 (1주일 검증 후)

GHA 운영이 1주일 정상 동작 확인되면 로컬 작업 스케줄러 정지:

```powershell
Disable-ScheduledTask -TaskName 'Mint Signal Scan'
Disable-ScheduledTask -TaskName 'Mint Daily Note'
```

PC OFF 가능. 다시 켜고 싶으면 `Enable-ScheduledTask` 또는 GHA 비활성.

⚠️ **즉시 삭제 X** — GHA 첫 주 안정성 검증 전까지 보존.

---

## 🚨 흔한 문제와 해결

### Cron이 정시에 안 돌아감
GitHub Actions 무료 한도 cron은 **수 분 ~ 수십 분 지연 가능**. 일봉 기반이라 시그널 품질에 영향 작음. 정확성이 필요하면 Railway/Render cron 검토 ($5/월).

### KIS API "IP 차단" 에러
KIS 콘솔에서 IP 제한 OFF. GitHub Actions IP는 동적이라 화이트리스트 불가능.

### 카카오 토큰 만료 안내가 도착함
refresh_token은 60일 유효 → Neon DB의 `auth_tokens.refresh_token`이 살아있으면 access는 자동 갱신. refresh도 만료되면 로컬에서 `python mint/notifier/setup_kakao.py` 재실행 후 토큰을 다시 Neon에 복사 (Phase 4c).

### Streamlit Cloud DB connection 한도 초과
Neon Pooled URL을 사용했는지 확인. 일반 URL은 limit 매우 낮음.

### GHA 빌드가 5분 이상 걸림
`mint/requirements.txt`의 qlib + torch가 무거움 (사실상 미사용). 필요 시 `requirements-runtime.txt` 분리 후 workflow에서 가벼운 것만 install — **별도 작업, 지금 안 함**.

---

## 📊 운영 시작 후 모니터링

- **첫 주**: GHA Actions 탭에서 실행 로그 + 카톡 도착 확인 매일
- **outcome 누적 30건** 도달 시: 운영 분포로 모델 재학습 (카드 m). GHA에 train workflow 추가 가능
- **NASDAQ 야간 활성화**: `.github/workflows/scan-us.yml`의 cron 주석 해제 후 push

---

## 🔄 롤백 (문제 생겼을 때)

GHA를 못 쓰겠으면:
1. GitHub repo → **Actions** → 각 workflow → **Disable workflow**
2. 로컬 작업 스케줄러 `Enable-ScheduledTask 'Mint Signal Scan'`, `'Mint Daily Note'`
3. 환경변수에서 `DATABASE_URL` 제거 (또는 미설정) → 자동으로 로컬 sqlite로 복귀

코드는 sqlite + postgres 양쪽 호환이므로 언제든 왕복 가능.
