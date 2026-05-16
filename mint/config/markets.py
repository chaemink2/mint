"""
Mint - 시장별 종목 유니버스 및 설정
"""
from dataclasses import dataclass
from typing import List


@dataclass
class Market:
    name: str
    code: str          # 내부 코드
    currency: str
    timezone: str
    open_time: str     # HH:MM
    close_time: str    # HH:MM
    trading_days: str  # 'weekday'


KOSPI = Market(
    name="코스피",
    code="KOSPI",
    currency="KRW",
    timezone="Asia/Seoul",
    open_time="09:00",
    close_time="15:30",
    trading_days="weekday",
)

KOSDAQ = Market(
    name="코스닥",
    code="KOSDAQ",
    currency="KRW",
    timezone="Asia/Seoul",
    open_time="09:00",
    close_time="15:30",
    trading_days="weekday",
)

NASDAQ = Market(
    name="나스닥",
    code="NASDAQ",
    currency="USD",
    timezone="America/New_York",
    open_time="09:30",
    close_time="16:00",
    trading_days="weekday",
)

ALL_MARKETS = [KOSPI, KOSDAQ, NASDAQ]

# 초기 스캔 유니버스 (확장 예정)
KOSPI_WATCHLIST: List[str] = [
    "005930",  # 삼성전자
    "000660",  # SK하이닉스
    "207940",  # 삼성바이오로직스
    "005380",  # 현대차
    "035420",  # NAVER
    "051910",  # LG화학
    "068270",  # 셀트리온
    "105560",  # KB금융
    "055550",  # 신한지주
    "012330",  # 현대모비스
]

KOSDAQ_WATCHLIST: List[str] = [
    "247540",  # 에코프로비엠
    "086520",  # 에코프로
    "373220",  # LG에너지솔루션
    "196170",  # 알테오젠
    "091990",  # 셀트리온헬스케어
    "263750",  # 펄어비스
    "041510",  # SM엔터테인먼트
    "035720",  # 카카오
    "251270",  # 넷마블
    "293490",  # 카카오게임즈
]

NASDAQ_WATCHLIST: List[str] = [
    "NVDA", "AAPL", "MSFT", "GOOGL", "AMZN",
    "META", "TSLA", "AVGO", "AMD", "INTC",
    "NFLX", "ADBE", "QCOM", "TXN", "MU",
]
