# 🌿 Mint — 단기 주식 매매 추천 시스템

## 프로젝트 목표

- **수익 목표**: 매수 후 1일 내 +3% 수익 시 매도 (빠를수록 좋음)
- **리스크 최소화**: 보수적 임계값, -2% 손절 원칙
- **대상 시장**: 코스피 + 코스닥 + 나스닥
- **알림**: 카카오톡 실시간 푸시

---

## 디렉토리 구조

```
mint/
├── config/
│   ├── settings.py          # 전역 설정 (API 키, 임계값 등)
│   └── markets.py           # 시장별 설정 (KOSPI, KOSDAQ, NASDAQ)
│
├── data/
│   ├── collector.py         # 데이터 수집 통합 인터페이스
│   ├── kis_client.py        # 한국투자증권 KIS API 클라이언트
│   ├── krx_client.py        # pykrx 히스토리컬 데이터
│   ├── us_client.py         # yfinance NASDAQ 데이터
│   ├── news_client.py       # 뉴스/공시 감성 데이터
│   ├── raw/                 # 원시 데이터 캐시
│   └── processed/           # 전처리 완료 데이터
│
├── engine/
│   ├── pipeline.py          # 전체 예측 파이프라인 오케스트레이터
│   ├── factors/
│   │   ├── technical.py     # 기술적 지표 팩터 (RSI, MACD, 볼린저밴드 등)
│   │   ├── momentum.py      # 모멘텀 팩터
│   │   ├── volume.py        # 거래량 팩터
│   │   └── sentiment.py     # 감성 팩터 (뉴스/공시)
│   ├── models/
│   │   ├── lgbm_model.py    # LightGBM 단기 예측 모델
│   │   ├── lstm_model.py    # LSTM 시계열 모델
│   │   └── ensemble.py      # 앙상블 (LightGBM + LSTM)
│   └── signals/
│       ├── generator.py     # 매수/매도 시그널 생성
│       ├── risk_filter.py   # 리스크 필터 (보수적 임계값)
│       └── exit_strategy.py # 매도 전략 (목표가/손절가/시간청산)
│
├── portfolio/
│   ├── manager.py           # 포트폴리오 상태 관리
│   ├── tracker.py           # 수익률 추적
│   └── db.py                # SQLite 매매 이력 DB
│
├── notifier/
│   ├── kakao.py             # 카카오 알림톡 발송
│   └── templates.py         # 알림 메시지 템플릿
│
├── dashboard/
│   ├── app.py               # Streamlit 대시보드 앱
│   ├── pages/
│   │   ├── overview.py      # 포트폴리오 개요
│   │   ├── signals.py       # 현재 추천 종목
│   │   ├── history.py       # 매매 이력/수익률
│   │   └── settings.py      # 설정 화면
│   └── components/          # 재사용 UI 컴포넌트
│
├── tests/
│   ├── test_data.py
│   ├── test_engine.py
│   └── test_signals.py
│
├── logs/                    # 실행 로그
├── main.py                  # 메인 실행 진입점 (스케줄러)
├── requirements.txt
└── README.md
```

---

## AI 엔진 선정 근거

| 모델 | 역할 | 단기 매매 적합 이유 |
|------|------|-------------------|
| **Qlib (Microsoft)** | 팩터 생성 + 파이프라인 | Alpha158 팩터셋, 모듈식 ML 파이프라인 |
| **LightGBM** | 핵심 예측 모델 | 빠른 추론, 과적합 저항성, 해석 가능 |
| **LSTM** | 시계열 패턴 | 가격 연속성, 단기 추세 캡처 |
| **앙상블** | 최종 시그널 | 단일 모델 리스크 분산 |

---

## 수익 구조 설계

```
매수 조건:
  - 예상 1일 수익률 ≥ 3.0%
  - 모델 신뢰도 ≥ 70%
  - 리스크 스코어 ≤ 30 (보수적)
  - 거래량 조건 통과

매도 조건 (우선순위):
  1. 목표가 도달 (+3~5%)      → 즉시 매도
  2. 손절가 도달 (-2%)        → 즉시 매도
  3. 보유 1일 초과            → 시간 청산
  4. 역방향 시그널 발생        → 조기 청산
```

---

## 개발 단계

- [x] **Step 1**: 프로젝트 구조 + 아키텍처 설계
- [ ] **Step 2**: 데이터 수집 모듈 (KIS API + pykrx + yfinance)
- [ ] **Step 3**: 팩터 생성 + AI 예측 모델 (Qlib + LightGBM/LSTM)
- [ ] **Step 4**: 시그널 생성 + 리스크 필터
- [ ] **Step 5**: 포트폴리오 DB + 수익률 추적
- [ ] **Step 6**: 카카오톡 알림 연동
- [ ] **Step 7**: Streamlit 대시보드 UI
- [ ] **Step 8**: 스케줄러 + 통합 테스트
