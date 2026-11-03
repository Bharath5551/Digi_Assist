"""Google OAuth (web flow) and encrypted token storage for Gmail + Calendar.

Tokens live in the oauth_tokens table, Fernet-encrypted with TOKEN_ENCRYPTION_KEY.
The Google client libraries are synchronous; every call goes through asyncio.to_thread.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

from cryptography.fernet import Fernet
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import Flow
from googleapiclient.discovery import build
from sqlalchemy import select

from app.config import get_settings
from app.db.base import session
from app.db.models import OAuthToken

SCOPES = [
    "https://www.googleapis.com/auth/gmail.modify",
    "https://www.googleapis.com/auth/calendar",
    "https://www.googleapis.com/auth/tasks",
]
PROVIDER = "google"


class NotConnected(Exception):
    def __init__(self) -> None:
        super().__init__("Google is not connected. Send /connect_google in Telegram to link your account.")


def _fernet() -> Fernet:
    key = get_settings().token_encryption_key
    if not key:
        raise RuntimeError("TOKEN_ENCRYPTION_KEY is not set")
    return Fernet(key.encode())


def _client_config() -> dict[str, Any]:
    s = get_settings()
    if not s.google_client_id or not s.google_client_secret:
        raise RuntimeError("GOOGLE_CLIENT_ID / GOOGLE_CLIENT_SECRET are not set")
    return {
        "web": {
            "client_id": s.google_client_id,
            "client_secret": s.google_client_secret,
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "redirect_uris": [redirect_uri()],
        }
    }


def redirect_uri() -> str:
    return get_settings().public_base_url.rstrip("/") + "/oauth/google/callback"


def auth_url(state: str) -> str:
    flow = Flow.from_client_config(_client_config(), scopes=SCOPES, redirect_uri=redirect_uri())
    url, _ = flow.authorization_url(access_type="offline", prompt="consent", state=state, include_granted_scopes="true")
    return url


async def finish_auth(code: str) -> None:
    flow = Flow.from_client_config(_client_config(), scopes=SCOPES, redirect_uri=redirect_uri())
    await asyncio.to_thread(flow.fetch_token, code=code)
    await _store(flow.credentials)


async def _store(creds: Credentials) -> None:
    blob = _fernet().encrypt(creds.to_json().encode()).decode()
    async with session() as s:
        row = (await s.execute(select(OAuthToken).where(OAuthToken.provider == PROVIDER))).scalar_one_or_none()
        if row:
            row.encrypted = blob
        else:
            s.add(OAuthToken(provider=PROVIDER, encrypted=blob))
        await s.commit()


async def is_connected() -> bool:
    async with session() as s:
        row = (await s.execute(select(OAuthToken).where(OAuthToken.provider == PROVIDER))).scalar_one_or_none()
    return row is not None


async def credentials() -> Credentials:
    async with session() as s:
        row = (await s.execute(select(OAuthToken).where(OAuthToken.provider == PROVIDER))).scalar_one_or_none()
    if row is None:
        raise NotConnected()
    data = json.loads(_fernet().decrypt(row.encrypted.encode()))
    creds = Credentials.from_authorized_user_info(data, SCOPES)
    if creds.expired and creds.refresh_token:
        await asyncio.to_thread(creds.refresh, Request())
        await _store(creds)
    return creds


async def service(name: str, version: str):
    creds = await credentials()
    return await asyncio.to_thread(build, name, version, credentials=creds, cache_discovery=False)


async def call(request) -> dict[str, Any]:
    """Execute a googleapiclient request off the event loop."""
    return await asyncio.to_thread(request.execute)
