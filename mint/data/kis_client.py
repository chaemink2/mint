"""
KIS (한국투자증권) REST 현재가 클라이언트 — 데이터 전용.

목적:
  - 장중 ref_price 보강 (룰 스캐너의 일봉 close는 stale일 수 있음)
  - 시그널 stale 판정 (config.ops.ref_price_stale_pct)

비고:
  - APP_KEY/SECRET이 비어있으면 모든 호출은 None을 반환 (no-op).
  - 토큰은 파일 캐시(mint/data/.kis_token.json)로 재사용 — KIS는 발급 한도 있음.
  - 매매(주문) API는 의도적으로 미구현. 카카오페이증권 수동 매매가 기본 [[user-trading-setup]].
"""
from __future__ import annotations

import json
import logging
import os
import threading
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Optional

import requests

from config.settings import config

log = logging.getLogger("mint.kis")

_TOKEN_CACHE_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), ".kis_token.json"
)
_TOKEN_LOCK = threading.Lock()
_REQUEST_TIMEOUT = 5.0


@dataclass
class KISPrice:
    ticker: str
    price: float
    prev_close: float
    change_pct: float
    fetched_at: datetime
    source: str = "kis"


def _has_credentials() -> bool:
    return bool(config.kis.app_key and config.kis.app_secret)


def _load_cached_token() -> Optional[dict]:
    if not os.path.exists(_TOKEN_CACHE_PATH):
        return None
    try:
        with open(_TOKEN_CACHE_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not data.get("expires_at"):
            return None
        if datetime.fromisoformat(data["expires_at"]) <= datetime.now():
            return None
        return data
    except Exception:
        return None


def _save_cached_token(token: str, expires_in_sec: int) -> None:
    try:
        with open(_TOKEN_CACHE_PATH, "w", encoding="utf-8") as f:
            json.dump(
                {
                    "access_token": token,
                    "expires_at": (
                        datetime.now() + timedelta(seconds=max(0, expires_in_sec - 300))
                    ).isoformat(),
                },
                f,
            )
    except Exception as e:
        log.debug("KIS token cache save failed: %s", e)


def _issue_token() -> Optional[str]:
    if not _has_credentials():
        return None

    with _TOKEN_LOCK:
        cached = _load_cached_token()
        if cached:
            return cached["access_token"]

        url = f"{config.kis.base_url}/oauth2/tokenP"
        body = {
            "grant_type": "client_credentials",
            "appkey": config.kis.app_key,
            "appsecret": config.kis.app_secret,
        }
        try:
            resp = requests.post(url, json=body, timeout=_REQUEST_TIMEOUT)
            resp.raise_for_status()
            data = resp.json()
        except Exception as e:
            log.warning("KIS token issue failed: %s", e)
            return None

        token = data.get("access_token")
        expires_in = int(data.get("expires_in", 3600))
        if not token:
            return None
        _save_cached_token(token, expires_in)
        return token


def get_current_price(ticker: str) -> Optional[KISPrice]:
    """국내 현재가 조회. 자격증명 없거나 실패 시 None."""
    if not _has_credentials():
        return None
    token = _issue_token()
    if not token:
        return None

    ticker = str(ticker).strip().zfill(6)
    url = f"{config.kis.base_url}/uapi/domestic-stock/v1/quotations/inquire-price"
    headers = {
        "content-type": "application/json; charset=utf-8",
        "authorization": f"Bearer {token}",
        "appkey": config.kis.app_key,
        "appsecret": config.kis.app_secret,
        "tr_id": "FHKST01010100",
    }
    params = {"FID_COND_MRKT_DIV_CODE": "J", "FID_INPUT_ISCD": ticker}

    try:
        resp = requests.get(url, headers=headers, params=params, timeout=_REQUEST_TIMEOUT)
        resp.raise_for_status()
        body = resp.json()
    except Exception as e:
        log.debug("KIS price fetch failed for %s: %s", ticker, e)
        return None

    out = body.get("output") or {}
    try:
        price = float(out.get("stck_prpr") or 0)
        prev_close = float(out.get("stck_sdpr") or 0)
        change_pct = float(out.get("prdy_ctrt") or 0)
    except (TypeError, ValueError):
        return None

    if price <= 0:
        return None

    return KISPrice(
        ticker=ticker,
        price=price,
        prev_close=prev_close,
        change_pct=change_pct,
        fetched_at=datetime.now(),
    )


def is_ref_price_stale(ref_price: float, current_price: Optional[float]) -> bool:
    """현재가가 ref_price와 stale threshold 이상 벗어났는지."""
    if not current_price or not ref_price or ref_price <= 0:
        return False
    drift = abs(current_price - ref_price) / ref_price
    return drift > config.ops.ref_price_stale_pct
