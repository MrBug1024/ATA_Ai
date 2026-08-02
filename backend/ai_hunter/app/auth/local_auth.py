"""Private-mode local authentication helpers."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError, VerificationError

from ..settings import get_settings


_HASHER = PasswordHasher()


def validate_password_policy(password: str, *, username: str = "") -> None:
    settings = get_settings()
    if len(password or "") < settings.auth_password_min_length:
        raise ValueError(f"密码长度不能少于 {settings.auth_password_min_length} 位")
    if username and password.strip().lower() == username.strip().lower():
        raise ValueError("密码不能与用户名相同")
    has_alpha = any(ch.isalpha() for ch in password)
    has_digit = any(ch.isdigit() for ch in password)
    if not (has_alpha and has_digit):
        raise ValueError("密码必须同时包含字母和数字")


def hash_password(password: str, *, username: str = "") -> str:
    validate_password_policy(password, username=username)
    return _HASHER.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    if not password_hash:
        return False
    try:
        return _HASHER.verify(password_hash, password)
    except (VerifyMismatchError, VerificationError):
        return False


def issue_local_access_token(*, user_id: str, username: str, company_id: str, auth_source: str = "local") -> tuple[str, datetime]:
    settings = get_settings()
    secret = settings.auth_local_jwt_secret or settings.user_center_jwt_secret
    if not secret:
        raise ValueError("未配置 AUTH_LOCAL_JWT_SECRET")
    now = datetime.now(timezone.utc)
    expires_at = now + timedelta(minutes=settings.auth_local_access_token_minutes)
    token = jwt.encode(
        {
            "sub": user_id,
            "name": username,
            settings.auth_jwt_company_claim: company_id,
            "auth_source": auth_source,
            "iat": int(now.timestamp()),
            "exp": int(expires_at.timestamp()),
        },
        secret,
        algorithm="HS256",
    )
    return token, expires_at
