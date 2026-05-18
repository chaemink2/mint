"""
카카오톡 "나에게 보내기" 1회 설정 헬퍼.

실행:
  python mint/notifier/setup_kakao.py

흐름:
  1. config.kakao.rest_api_key 확인 (env: KAKAO_REST_API_KEY)
  2. 인가 URL 안내 → 브라우저에서 로그인+동의 → redirect URL의 ?code= 값 복사
  3. 코드 입력 → access/refresh 토큰 발급 → mint/data/.kakao_token.json 저장
  4. 테스트 메시지 1통 발송으로 검증

카카오 디벨로퍼스 사전 설정 (한 번만):
  - https://developers.kakao.com 가입 → 내 애플리케이션 → 앱 생성
  - REST API 키 복사 → 환경변수 KAKAO_REST_API_KEY 설정
  - 플랫폼 > Web > 사이트 도메인 추가 (KAKAO_REDIRECT_URI, 기본 https://localhost)
  - 제품 > 카카오 로그인 > 활성화 ON, Redirect URI 추가 (위와 동일)
  - 동의항목 > 카카오톡 메시지 전송(talk_message) > 사용 설정
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from urllib.parse import urlencode

from config.settings import config
from notifier import kakao


def _auth_url() -> str:
    params = {
        "response_type": "code",
        "client_id": config.kakao.rest_api_key,
        "redirect_uri": config.kakao.redirect_uri,
        "scope": "talk_message",
    }
    return f"{kakao.AUTH_BASE}/oauth/authorize?{urlencode(params)}"


def main() -> int:
    if not config.kakao.rest_api_key:
        print("KAKAO_REST_API_KEY 환경변수를 먼저 설정하세요.", file=sys.stderr)
        print(
            "Windows PowerShell: $env:KAKAO_REST_API_KEY = \"...\"; "
            "python mint/notifier/setup_kakao.py",
            file=sys.stderr,
        )
        return 1

    print("=" * 60)
    print("카카오톡 '나에게 보내기' 1회 설정")
    print("=" * 60)
    print()
    print("1) 아래 URL을 브라우저에서 여세요 (카카오 로그인 + 동의):")
    print()
    print(f"   {_auth_url()}")
    print()
    print("2) 로그인 후 리다이렉트된 주소(예: https://localhost/?code=XXX...)")
    print(f"   에서 'code=' 뒤의 값을 복사하세요.")
    print(f"   (redirect_uri = {config.kakao.redirect_uri} — 카카오 콘솔과 동일해야 함)")
    print()
    code = input("3) code 값 붙여넣기: ").strip()
    if not code:
        print("코드가 비어 있습니다.", file=sys.stderr)
        return 1

    try:
        tokens = kakao.exchange_code_for_tokens(code)
    except Exception as e:
        print(f"토큰 발급 실패: {e}", file=sys.stderr)
        return 1

    print()
    print(f"✓ 토큰 저장 완료 → {config.kakao.token_path}")
    print(f"   access  만료 ≈ {tokens.expires_at}")
    print(f"   refresh 만료 ≈ {tokens.refresh_expires_at}")
    print()

    print("4) 테스트 메시지 발송 중...")
    ok = kakao.send_text(
        "✅ Mint 알림 설정 완료\n"
        "이 메시지가 보이면 카카오톡 '나에게 보내기' 연동 OK 입니다."
    )
    if ok:
        print("✓ 발송 성공. 카카오톡 '나와의 채팅'을 확인하세요.")
        return 0
    else:
        print("✗ 발송 실패. 동의항목(talk_message)이 활성화돼 있는지 확인하세요.")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
