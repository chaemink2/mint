"""
Mint - 전역 설정
모든 API 키, 임계값, 파라미터를 중앙 관리
"""
from dataclasses import dataclass, field
from typing import Optional
import os


@dataclass
class KISConfig:
    """한국투자증권 KIS API 설정 — 실전 키지만 매매는 paper 모드 기본"""
    app_key: str = os.getenv("KIS_APP_KEY", "")
    app_secret: str = os.getenv("KIS_APP_SECRET", "")
    account_no: str = os.getenv("KIS_ACCOUNT_NO", "")      # 계좌번호 앞 8자리
    account_code: str = os.getenv("KIS_ACCOUNT_CODE", "01") # 상품코드
    is_mock: bool = os.getenv("KIS_MOCK", "false").lower() == "true"  # 시세는 실전이 기본
    trade_mode: str = os.getenv("KIS_TRADE_MODE", "paper")  # paper: 시뮬레이션 / live: 실주문

    @property
    def base_url(self) -> str:
        if self.is_mock:
            return "https://openapivts.koreainvestment.com:29443"
        return "https://openapi.koreainvestment.com:9443"

    @property
    def is_paper(self) -> bool:
        return self.trade_mode.lower() != "live"


@dataclass
class KakaoConfig:
    """카카오 설정.
    - 1차 채널: "나에게 보내기" (talk_message scope, 개인 가능)
      필요 필드: rest_api_key, redirect_uri, token_path
    - 2차 채널: 비즈니스 알림톡 (채널·템플릿 승인 필요, 보류)
      필요 필드: template_id, receiver_phone
    """
    rest_api_key: str = os.getenv("KAKAO_REST_API_KEY", "")
    redirect_uri: str = os.getenv("KAKAO_REDIRECT_URI", "https://localhost")
    token_path: str = os.getenv(
        "KAKAO_TOKEN_PATH", "mint/data/.kakao_token.json"
    )
    # 비즈니스 알림톡 (보류)
    template_id: str = os.getenv("KAKAO_TEMPLATE_ID", "")
    receiver_phone: str = os.getenv("KAKAO_RECEIVER_PHONE", "")


@dataclass
class USDataConfig:
    """미국 시장 실시간 데이터 (Alpaca 또는 Polygon)"""
    alpaca_api_key: str = os.getenv("ALPACA_API_KEY", "")
    alpaca_secret_key: str = os.getenv("ALPACA_SECRET_KEY", "")
    alpaca_base_url: str = os.getenv("ALPACA_BASE_URL", "https://data.alpaca.markets")
    polygon_api_key: str = os.getenv("POLYGON_API_KEY", "")

    @property
    def provider(self) -> str:
        """우선순위: Polygon > Alpaca > yfinance(폴백)"""
        if self.polygon_api_key:
            return "polygon"
        if self.alpaca_api_key:
            return "alpaca"
        return "yfinance"


@dataclass
class SignalConfig:
    """
    매수/매도 임계값.
    - min_expected_return_1d: 시그널 필터 (24h 내 +3% 장담 못 하면 추천 안 함) — 사용자 확정
    - target_return: 익절 목표 (실제 매도 권고가, 높을수록 좋음)
    - min_model_confidence: Step 3b ML 캘리브레이션 후에만 적용 (use_ml_confidence=True)
    """
    min_expected_return_1d: float = float(os.getenv("MINT_MIN_EXPECTED_RETURN", "0.03"))
    min_model_confidence: float = float(os.getenv("MINT_MIN_ML_CONFIDENCE", "0.70"))
    use_ml_confidence: bool = os.getenv("MINT_USE_ML_CONFIDENCE", "false").lower() == "true"
    max_risk_score: float = float(os.getenv("MINT_MAX_RISK_SCORE", "30"))
    min_volume_ratio: float = float(os.getenv("MINT_MIN_VOLUME_RATIO", "1.2"))

    target_return: float = float(os.getenv("MINT_TARGET_RETURN", "0.035"))
    stop_loss: float = float(os.getenv("MINT_STOP_LOSS", "-0.02"))
    max_hold_hours: int = int(os.getenv("MINT_MAX_HOLD_HOURS", "24"))

    # 분봉 룰 (장중 시그널 검증) — KIS 분봉 fetch 필요. 일봉 룰+ML 통과 종목만 평가.
    use_minute_rule: bool = os.getenv("MINT_USE_MINUTE_RULE", "false").lower() == "true"
    min_minute_vol_spike: float = float(os.getenv("MINT_MIN_MINUTE_VOL_SPIKE", "3.0"))
    minute_short_window: int = int(os.getenv("MINT_MINUTE_SHORT_WINDOW", "5"))
    minute_long_window: int = int(os.getenv("MINT_MINUTE_LONG_WINDOW", "20"))

    max_position_pct: float = 0.20
    max_daily_buys: int = 5


def _optional_int(env_name: str) -> Optional[int]:
    v = os.getenv(env_name)
    if not v:
        return None
    try:
        return int(v)
    except ValueError:
        return None


@dataclass
class OperationConfig:
    """운영 모드 — PC 간헐 실행 / 수동 매매 전제"""
    default_mode: str = os.getenv("MINT_MODE", "scan-once")  # scan-once | daemon
    enable_us_market_scan: bool = os.getenv("MINT_US_SCAN", "false").lower() == "true"
    signal_valid_minutes: int = int(os.getenv("MINT_SIGNAL_VALID_MIN", "30"))
    signal_dedup_hours: int = int(os.getenv("MINT_SIGNAL_DEDUP_H", "4"))
    ref_price_stale_pct: float = float(os.getenv("MINT_REF_STALE_PCT", "0.008"))
    stop_loss_is_advisory: bool = True
    # None이면 static 워치리스트(10개씩). 정수 지정 시 시총 상위 N개 동적 추출 (KR만).
    watchlist_size: Optional[int] = field(default_factory=lambda: _optional_int("MINT_WATCHLIST_SIZE"))


@dataclass
class MarketConfig:
    """시장별 설정"""
    kospi_universe_size: int = 100           # 코스피 상위 N종목
    kosdaq_universe_size: int = 100          # 코스닥 상위 N종목
    nasdaq_universe_size: int = 50           # 나스닥 상위 N종목
    scan_interval_minutes: int = 10          # 시그널 스캔 주기 (분)


@dataclass
class DBConfig:
    """데이터베이스 설정"""
    path: str = "mint/data/mint.db"
    backup_path: str = "mint/data/backup/"


@dataclass
class MintConfig:
    """Mint 전체 설정 (진입점)"""
    kis: KISConfig = field(default_factory=KISConfig)
    kakao: KakaoConfig = field(default_factory=KakaoConfig)
    us_data: USDataConfig = field(default_factory=USDataConfig)
    signal: SignalConfig = field(default_factory=SignalConfig)
    ops: OperationConfig = field(default_factory=OperationConfig)
    market: MarketConfig = field(default_factory=MarketConfig)
    db: DBConfig = field(default_factory=DBConfig)
    log_level: str = "INFO"
    log_path: str = "mint/logs/"


# 싱글턴 인스턴스
config = MintConfig()
