"""
시간대 유틸 — Cloud Migration 대비.

Mint는 한국장(KST) 중심이지만, GitHub Actions/클라우드는 UTC.
Phase 0 선행: 모든 영업일/장중 판정·표시는 KST로 일원화.

사용:
  from config.tz import now_kst, today_kst, is_kr_market_open
  ts = now_kst()              # tz-aware KST datetime
  ymd = today_kst()           # 'YYYY-MM-DD' (KST 기준)
  if is_kr_market_open():     # 09:00~15:30 KST + 평일
      ...
"""
from __future__ import annotations

from datetime import datetime, time
from typing import Optional

try:
    from zoneinfo import ZoneInfo
    KST = ZoneInfo("Asia/Seoul")
    UTC = ZoneInfo("UTC")
except ImportError:  # Python <3.9 (불필요. 3.13 권장)
    KST = None
    UTC = None


def now_kst() -> datetime:
    """현재 시각 (KST tz-aware). UTC 환경에서도 KST 반환."""
    if KST is None:
        return datetime.now()
    return datetime.now(tz=KST)


def today_kst() -> str:
    """오늘 KST 날짜 'YYYY-MM-DD'."""
    return now_kst().strftime("%Y-%m-%d")


def is_weekday_kst(dt: Optional[datetime] = None) -> bool:
    """KST 기준 월~금 여부."""
    dt = dt or now_kst()
    return dt.weekday() < 5  # Mon=0, Sun=6


def is_kr_market_open(dt: Optional[datetime] = None) -> bool:
    """KST 09:00~15:30 + 평일. 휴장일은 별도 검증 필요(연동 X)."""
    dt = dt or now_kst()
    if not is_weekday_kst(dt):
        return False
    t = dt.time()
    return time(9, 0) <= t <= time(15, 30)


def is_us_market_open(dt: Optional[datetime] = None) -> bool:
    """미국 정규장 (KST 22:30 ~ 다음날 05:00). DST 무시 (간이 추정).
    정확하려면 pandas_market_calendars 등 사용.
    """
    dt = dt or now_kst()
    # 평일/주말 처리는 KST 기준 — US 야간은 KST 다음날 새벽까지 이어짐
    h = dt.hour
    m = dt.minute
    # 22:30~23:59 또는 0:00~5:00
    if h == 22 and m >= 30:
        return is_weekday_kst(dt)
    if 23 <= h <= 23:
        return is_weekday_kst(dt)
    if 0 <= h <= 4:
        # 전날(KST 목요일) 야간 → KST 금요일 새벽 = NY 목요일 정규장. 평일로 간주.
        return True
    if h == 5 and m == 0:
        return True
    return False


def to_kst(dt: datetime) -> datetime:
    """naive 또는 다른 TZ datetime → KST tz-aware."""
    if KST is None:
        return dt
    if dt.tzinfo is None:
        # UTC 가정 (Actions/Cloud 환경)
        return dt.replace(tzinfo=UTC).astimezone(KST)
    return dt.astimezone(KST)
