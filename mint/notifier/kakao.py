"""
카카오톡 "나에게 보내기" 알림 클라이언트.

흐름:
  1. 사용자가 1회 인가 (kakao_setup.py 또는 scripts/kakao_setup.py)
     → access_token + refresh_token 을 token_path 에 저장
  2. send_text() 호출 시 access_token 유효성 확인
     → 만료 시 refresh_token 으로 자동 갱신 → 토큰 파일 갱신
  3. POST kapi.kakao.com/v2/api/talk/memo/default/send 로 text 템플릿 전송

엔드포인트:
  - https://kauth.kakao.com/oauth/token            토큰 발급/갱신
  - https://kapi.kakao.com/v2/api/talk/memo/default/send   나에게 메시지

토큰 파일 (JSON):
  {
    "access_token": "...",
    "refresh_token": "...",
    "expires_at": "ISO-8601",
    "refresh_expires_at": "ISO-8601"
  }

제약:
  - 카카오 text 템플릿 본문 200자 (한글 기준).
  - refresh_token 유효 60일 (마지막 사용 기준). 갱신 시 응답에 새 refresh_token 포함될 수 있음.
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

log = logging.getLogger("mint.kakao")

AUTH_BASE = "https://kauth.kakao.com"
API_BASE = "https://kapi.kakao.com"
TEXT_MAX_LEN = 200  # 카카오 text 템플릿 본문 제한
_REQUEST_TIMEOUT = 5.0
_TOKEN_REFRESH_BUFFER = timedelta(minutes=5)
_LOCK = threading.Lock()


@dataclass
class KakaoTokenSet:
    access_token: str
    refresh_token: str
    expires_at: datetime
    refresh_expires_at: Optional[datetime] = None

    def to_dict(self) -> dict:
        return {
            "access_token": self.access_token,
            "refresh_token": self.refresh_token,
            "expires_at": self.expires_at.isoformat(),
            "refresh_expires_at": (
                self.refresh_expires_at.isoformat() if self.refresh_expires_at else None
            ),
        }

    @classmethod
    def from_dict(cls, d: dict) -> "KakaoTokenSet":
        return cls(
            access_token=d["access_token"],
            refresh_token=d["refresh_token"],
            expires_at=datetime.fromisoformat(d["expires_at"]),
            refresh_expires_at=(
                datetime.fromisoformat(d["refresh_expires_at"])
                if d.get("refresh_expires_at") else None
            ),
        )


def _token_path() -> str:
    return config.kakao.token_path


def _load_tokens() -> Optional[KakaoTokenSet]:
    path = _token_path()
    if not os.path.exists(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return KakaoTokenSet.from_dict(data)
    except Exception as e:
        log.warning("Kakao token load failed (%s): %s", path, e)
        return None


def _save_tokens(tokens: KakaoTokenSet) -> None:
    path = _token_path()
    try:
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(tokens.to_dict(), f, ensure_ascii=False, indent=2)
    except Exception as e:
        log.warning("Kakao token save failed: %s", e)


def _now() -> datetime:
    return datetime.now()


def is_configured() -> bool:
    """REST API 키 + 토큰 파일 둘 다 있어야 알림 가능."""
    return bool(config.kakao.rest_api_key) and _load_tokens() is not None


def exchange_code_for_tokens(code: str) -> KakaoTokenSet:
    """인가 코드 → access/refresh 토큰. setup 1회용."""
    if not config.kakao.rest_api_key:
        raise RuntimeError("KAKAO_REST_API_KEY 가 설정되어 있지 않습니다.")
    resp = requests.post(
        f"{AUTH_BASE}/oauth/token",
        data={
            "grant_type": "authorization_code",
            "client_id": config.kakao.rest_api_key,
            "redirect_uri": config.kakao.redirect_uri,
            "code": code,
        },
        timeout=_REQUEST_TIMEOUT,
    )
    if resp.status_code != 200:
        raise RuntimeError(
            f"카카오 토큰 발급 실패 ({resp.status_code}): {resp.text}"
        )
    body = resp.json()
    tokens = KakaoTokenSet(
        access_token=body["access_token"],
        refresh_token=body["refresh_token"],
        expires_at=_now() + timedelta(seconds=int(body.get("expires_in", 21599))),
        refresh_expires_at=_now() + timedelta(
            seconds=int(body.get("refresh_token_expires_in", 5184000))
        ),
    )
    _save_tokens(tokens)
    return tokens


def _refresh_tokens(tokens: KakaoTokenSet) -> Optional[KakaoTokenSet]:
    """refresh_token 으로 access 갱신. 응답에 새 refresh_token 있으면 교체."""
    if not config.kakao.rest_api_key:
        return None
    try:
        resp = requests.post(
            f"{AUTH_BASE}/oauth/token",
            data={
                "grant_type": "refresh_token",
                "client_id": config.kakao.rest_api_key,
                "refresh_token": tokens.refresh_token,
            },
            timeout=_REQUEST_TIMEOUT,
        )
    except Exception as e:
        log.warning("Kakao refresh request failed: %s", e)
        return None

    if resp.status_code != 200:
        log.warning("Kakao refresh failed (%s): %s", resp.status_code, resp.text)
        return None

    body = resp.json()
    new_access = body.get("access_token")
    if not new_access:
        return None

    new_refresh = body.get("refresh_token") or tokens.refresh_token
    new_refresh_expires = body.get("refresh_token_expires_in")
    refreshed = KakaoTokenSet(
        access_token=new_access,
        refresh_token=new_refresh,
        expires_at=_now() + timedelta(seconds=int(body.get("expires_in", 21599))),
        refresh_expires_at=(
            _now() + timedelta(seconds=int(new_refresh_expires))
            if new_refresh_expires else tokens.refresh_expires_at
        ),
    )
    _save_tokens(refreshed)
    log.info("Kakao access token refreshed")
    return refreshed


def _get_valid_access_token() -> Optional[str]:
    with _LOCK:
        tokens = _load_tokens()
        if tokens is None:
            return None
        if tokens.expires_at - _TOKEN_REFRESH_BUFFER > _now():
            return tokens.access_token
        refreshed = _refresh_tokens(tokens)
        return refreshed.access_token if refreshed else None


def _truncate(text: str, limit: int = TEXT_MAX_LEN) -> str:
    if len(text) <= limit:
        return text
    return text[: limit - 1] + "…"


def send_text(text: str, link_url: Optional[str] = None, button_title: Optional[str] = None) -> bool:
    """카카오톡 '나와의 채팅' 으로 text 템플릿 전송. 성공 시 True.

    text: 본문 (200자 초과 시 자동 trim)
    link_url: 메시지 클릭 시 열릴 URL (선택)
    button_title: 버튼 라벨 (link_url 있을 때만 의미)
    """
    if not is_configured():
        log.debug("Kakao notifier 미설정 — 알림 skip")
        return False

    access = _get_valid_access_token()
    if not access:
        log.warning("Kakao access token 확보 실패 — 알림 skip")
        return False

    body_text = _truncate(text)
    template = {
        "object_type": "text",
        "text": body_text,
        "link": {
            "web_url": link_url or "https://developers.kakao.com",
            "mobile_web_url": link_url or "https://developers.kakao.com",
        },
    }
    if button_title and link_url:
        template["button_title"] = button_title

    try:
        resp = requests.post(
            f"{API_BASE}/v2/api/talk/memo/default/send",
            headers={"Authorization": f"Bearer {access}"},
            data={"template_object": json.dumps(template, ensure_ascii=False)},
            timeout=_REQUEST_TIMEOUT,
        )
    except Exception as e:
        log.warning("Kakao send request failed: %s", e)
        return False

    if resp.status_code != 200:
        log.warning("Kakao send failed (%s): %s", resp.status_code, resp.text)
        return False
    return True
