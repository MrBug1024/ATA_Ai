"""身份契约（Tier 3 认证层）。

不良资产 v2 支持两类身份来源：
  - platform：用户经**用户中心**登录拿到 JWT，本服务只**验签 + 取身份**。
  - private：私有化部署下使用本项目本地身份；本阶段先复用同一验签入口承载本地 token。

取身份优先级：
  ① Authorization: Bearer <JWT/token> —— 配了密钥/公钥就验签解码（claims: sub/name/company/apps/roles）
  ② 开发态信任头 X-User-Id / X-User-Roles / X-Company-Id（AUTH_DEV_TRUST_HEADERS）
  ③ AUTH_ENABLED=false → 返回全权限默认 admin 身份（现有接口/测试不受影响）
     AUTH_ENABLED=true 且无有效凭证 → 401

JWT 验签：HS256 无第三方依赖（hmac 手验）；RS256 需安装 PyJWT。
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import time
from dataclasses import dataclass, field

from fastapi import HTTPException, Request

from ..settings import get_settings
from .roles import ADMIN_ROLE, COMPANY_ADMIN_ROLE, normalize_roles

LOGGER = logging.getLogger(__name__)


@dataclass
class Identity:
    user_id: str = ""
    username: str = ""
    roles: list[str] = field(default_factory=list)
    company_id: str = ""
    apps: list[str] = field(default_factory=list)
    is_company_admin: bool = False
    is_super_admin: bool = False
    authenticated: bool = False  # True=经 JWT 验签；False=开发头/默认

    @classmethod
    def admin(cls) -> "Identity":
        return cls(
            user_id="__system__",
            username="system",
            roles=[ADMIN_ROLE],
            is_company_admin=True,
            is_super_admin=True,
            authenticated=False,
        )

    @property
    def is_admin(self) -> bool:
        return self.is_super_admin or ADMIN_ROLE in self.roles


def _b64url_decode(seg: str) -> bytes:
    pad = "=" * (-len(seg) % 4)
    return base64.urlsafe_b64decode(seg + pad)


def _verify_hs256(token: str, secret: str) -> dict:
    header_b64, payload_b64, sig_b64 = token.split(".")
    signing_input = f"{header_b64}.{payload_b64}".encode()
    expected = hmac.new(secret.encode(), signing_input, hashlib.sha256).digest()
    if not hmac.compare_digest(expected, _b64url_decode(sig_b64)):
        raise ValueError("签名校验失败")
    return json.loads(_b64url_decode(payload_b64))


def _decode_jwt(token: str, settings) -> dict:
    """验签解码 JWT。HS256 手验；RS256 走 PyJWT（需安装）。返回 claims。"""
    alg = (settings.user_center_jwt_alg or "HS256").upper()
    if alg == "HS256":
        secret = settings.user_center_jwt_secret
        if str(settings.auth_identity_mode).strip().lower() == "private" and settings.auth_local_jwt_secret:
            secret = settings.auth_local_jwt_secret
        if not secret:
            raise ValueError("HS256 未配置 AUTH_LOCAL_JWT_SECRET 或 USER_CENTER_JWT_SECRET")
        claims = _verify_hs256(token, secret)
        exp = claims.get("exp")
        if exp is not None and int(exp) < int(time.time()):
            raise ValueError("JWT 已过期")
        return claims
    # RS256 等非对称算法 → PyJWT
    try:
        import jwt  # type: ignore
    except ImportError as exc:  # pragma: no cover
        raise ValueError(f"算法 {alg} 需要安装 PyJWT") from exc
    key = settings.user_center_jwt_public_key
    if not key:
        raise ValueError(f"{alg} 未配置 USER_CENTER_JWT_PUBLIC_KEY")
    return jwt.decode(token, key, algorithms=[alg])


def _bearer_token(request: Request) -> str:
    auth = request.headers.get("authorization", "") or request.headers.get("Authorization", "")
    if auth.lower().startswith("bearer "):
        return auth[7:].strip()
    return ""


def _list_claim(value) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [item.strip() for item in value.split(",") if item.strip()]
    if isinstance(value, (list, tuple, set)):
        return [str(item) for item in value if str(item)]
    return [str(value)]


def _bool_claim(value) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    return str(value).strip().lower() in {"1", "true", "yes", "y", "on"}


def _identity_from_claims(claims: dict, settings) -> Identity:
    roles = normalize_roles(_list_claim(claims.get(settings.auth_jwt_roles_claim, [])))
    apps = _list_claim(claims.get(settings.auth_jwt_apps_claim, []))
    if (
        str(settings.auth_identity_mode).strip().lower() == "platform"
        and settings.auth_require_project_access
        and settings.auth_project_code
        and settings.auth_project_code not in apps
    ):
        raise HTTPException(status_code=403, detail="无权限访问本项目")
    return Identity(
        user_id=str(claims.get(settings.auth_jwt_user_claim, "") or ""),
        username=str(claims.get(settings.auth_jwt_name_claim, "") or ""),
        roles=roles,
        company_id=str(claims.get(settings.auth_jwt_company_claim, "") or ""),
        apps=apps,
        is_super_admin=_bool_claim(claims.get("is_super_admin")),
        authenticated=True,
    )


def _identity_from_headers(request: Request) -> Identity | None:
    uid = request.headers.get("x-user-id") or request.headers.get("X-User-Id")
    if not uid:
        return None
    raw_roles = request.headers.get("x-user-roles") or request.headers.get("X-User-Roles") or ""
    roles = normalize_roles([r.strip() for r in raw_roles.split(",") if r.strip()])
    name = request.headers.get("x-user-name") or request.headers.get("X-User-Name") or ""
    company_id = request.headers.get("x-company-id") or request.headers.get("X-Company-Id") or ""
    apps = _list_claim(request.headers.get("x-user-apps") or request.headers.get("X-User-Apps"))
    return Identity(
        user_id=uid,
        username=name,
        roles=roles,
        company_id=company_id,
        apps=apps,
        is_super_admin=_bool_claim(
            request.headers.get("x-is-super-admin") or request.headers.get("X-Is-Super-Admin")
        ),
        authenticated=False,
    )


def _load_local_roles(identity: Identity, fallback_roles: list[str], settings) -> Identity:
    """Load project roles from app_user_role, with v1 fallback during migration."""
    if not identity.user_id or identity.is_admin:
        return identity

    roles: list[str] = []
    try:
        from ..services.user_service import get_user_service

        roles = get_user_service().list_user_roles(identity.user_id, company_id=identity.company_id)
    except Exception as exc:  # noqa: BLE001 - app_user_role may not exist before v2 DDL is applied
        LOGGER.warning("load_user_roles_from_db_failed: %s", str(exc)[:160])

    if roles:
        identity.roles = normalize_roles(roles)
    elif settings.auth_legacy_roles_enabled:
        identity.roles = normalize_roles(fallback_roles)
    else:
        identity.roles = []

    identity.is_super_admin = identity.is_super_admin or ADMIN_ROLE in identity.roles
    identity.is_company_admin = (
        identity.is_super_admin
        or ADMIN_ROLE in identity.roles
        or COMPANY_ADMIN_ROLE in identity.roles
    )
    return identity


def get_current_identity(request: Request) -> Identity:
    """FastAPI 依赖：解析当前请求身份（见模块 docstring 的三优先级）。"""
    settings = get_settings()
    token = _bearer_token(request)

    local_secret = settings.auth_local_jwt_secret if str(settings.auth_identity_mode).strip().lower() == "private" else ""
    if token and (local_secret or settings.user_center_jwt_secret or settings.user_center_jwt_public_key):
        try:
            ident = _identity_from_claims(_decode_jwt(token, settings), settings)
            return _load_local_roles(ident, list(ident.roles), settings)
        except Exception as exc:  # noqa: BLE001 — 验签失败
            if isinstance(exc, HTTPException):
                raise
            LOGGER.warning("jwt_verify_failed: %s", str(exc)[:160])
            if settings.auth_enabled:
                raise HTTPException(status_code=401, detail="JWT 验签失败")

    if settings.auth_dev_trust_headers:
        hdr = _identity_from_headers(request)
        if hdr is not None:
            return _load_local_roles(hdr, list(hdr.roles), settings)

    if not settings.auth_enabled:
        return Identity.admin()

    raise HTTPException(status_code=401, detail="缺少有效身份凭证（Authorization: Bearer）")
