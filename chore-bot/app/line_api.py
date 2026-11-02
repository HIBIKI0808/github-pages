"""LINE Messaging API / LINE Login の薄いクライアント（公式 SDK に依存せず httpx で直接叩く）。"""
from __future__ import annotations

import base64
import hashlib
import hmac
import logging
import time

import httpx

from .config import settings

log = logging.getLogger(__name__)
API = "https://api.line.me"


def verify_signature(body: bytes, signature: str, secret: str | None = None) -> bool:
    """Webhook の X-Line-Signature を検証する。"""
    secret = secret if secret is not None else settings.line_channel_secret
    if not secret or not signature:
        return False
    digest = hmac.new(secret.encode(), body, hashlib.sha256).digest()
    return hmac.compare_digest(base64.b64encode(digest).decode(), signature)


def _headers() -> dict[str, str]:
    return {"Authorization": f"Bearer {settings.line_channel_access_token}"}


async def _post(path: str, payload: dict) -> None:
    if not settings.line_channel_access_token:
        log.warning("LINE_CHANNEL_ACCESS_TOKEN 未設定のため送信をスキップ: %s", path)
        return
    async with httpx.AsyncClient(timeout=10) as client:
        res = await client.post(f"{API}{path}", json=payload, headers=_headers())
    if res.status_code >= 400:
        log.error("LINE API error %s %s: %s", path, res.status_code, res.text)
        res.raise_for_status()


async def reply(reply_token: str, messages: list[dict]) -> None:
    await _post("/v2/bot/message/reply", {"replyToken": reply_token, "messages": messages[:5]})


async def push(to: str, messages: list[dict]) -> None:
    await _post("/v2/bot/message/push", {"to": to, "messages": messages[:5]})


async def get_display_name(user_id: str, group_id: str | None = None, room_id: str | None = None) -> str | None:
    if not settings.line_channel_access_token:
        return None
    if group_id:
        path = f"/v2/bot/group/{group_id}/member/{user_id}"
    elif room_id:
        path = f"/v2/bot/room/{room_id}/member/{user_id}"
    else:
        path = f"/v2/bot/profile/{user_id}"
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            res = await client.get(f"{API}{path}", headers=_headers())
        if res.status_code == 200:
            return res.json().get("displayName")
    except httpx.HTTPError:
        log.exception("プロフィール取得に失敗")
    return None


# LIFF の ID トークン検証結果を短時間キャッシュ（毎リクエスト LINE に問い合わせないため）
_token_cache: dict[str, tuple[float, dict]] = {}


async def verify_id_token(id_token: str) -> dict | None:
    """LIFF から受け取った ID トークンを検証し、{sub, name, ...} を返す。"""
    if not settings.line_login_channel_id:
        return None
    now = time.time()
    cached = _token_cache.get(id_token)
    if cached and cached[0] > now:
        return cached[1]
    async with httpx.AsyncClient(timeout=10) as client:
        res = await client.post(
            f"{API}/oauth2/v2.1/verify",
            data={"id_token": id_token, "client_id": settings.line_login_channel_id},
        )
    if res.status_code != 200:
        return None
    claims = res.json()
    _token_cache[id_token] = (min(float(claims.get("exp", now + 300)), now + 600), claims)
    return claims
