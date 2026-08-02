"""Private-mode local authentication routes."""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from ..auth.identity import Identity, get_current_identity
from ..auth.local_auth import hash_password, issue_local_access_token, verify_password
from ..settings import get_settings
from ..services.user_service import get_user_service

router = APIRouter(prefix="/auth", tags=["auth"])


class LoginRequest(BaseModel):
    login_identifier: str = Field(description="登录名")
    password: str = Field(description="密码")


class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_at: datetime
    user_id: str
    username: str
    company_id: str


class PasswordChangeRequest(BaseModel):
    old_password: str = Field(description="旧密码")
    new_password: str = Field(description="新密码")


def _audit(**kwargs) -> None:
    try:
        get_user_service().write_auth_audit_log(**kwargs)
    except Exception:  # noqa: BLE001 - 登录主流程不因审计存储异常中断
        pass


@router.post("/login", response_model=LoginResponse, summary="私有化本地账号密码登录")
async def login(payload: LoginRequest) -> LoginResponse:
    settings = get_settings()
    if settings.auth_identity_mode.strip().lower() != "private":
        raise HTTPException(status_code=404, detail="本地登录仅在 private 模式启用")
    if not (settings.auth_local_jwt_secret or settings.user_center_jwt_secret):
        raise HTTPException(status_code=500, detail="未配置 AUTH_LOCAL_JWT_SECRET")

    svc = get_user_service()
    record = svc.get_local_login_record(payload.login_identifier)
    if not record:
        _audit(
            event_type="login_failed",
            target_type="user",
            target_id=payload.login_identifier,
            action="login",
            decision="failed",
            detail={"reason": "user_not_found"},
        )
        raise HTTPException(status_code=401, detail="登录名或密码错误")

    user_id = str(record.get("user_id") or "")
    company_id = str(record.get("company_id") or "")
    status = str(record.get("status") or "")
    locked_until = record.get("locked_until")
    if status != "active":
        _audit(
            event_type="login_failed",
            actor_id=user_id,
            company_id=company_id,
            target_type="user",
            target_id=user_id,
            action="login",
            decision="failed",
            detail={"reason": f"user_status_{status}"},
        )
        raise HTTPException(status_code=403, detail="用户已禁用或锁定")
    if locked_until and locked_until > datetime.now(timezone.utc):
        raise HTTPException(status_code=423, detail="登录失败次数过多，账号暂时锁定")

    if not verify_password(payload.password, str(record.get("password_hash") or "")):
        svc.record_login_failure(
            payload.login_identifier,
            threshold=settings.auth_password_failed_lock_threshold,
            lock_minutes=settings.auth_password_lock_minutes,
        )
        _audit(
            event_type="login_failed",
            actor_id=user_id,
            company_id=company_id,
            target_type="user",
            target_id=user_id,
            action="login",
            decision="failed",
            detail={"reason": "bad_password"},
        )
        raise HTTPException(status_code=401, detail="登录名或密码错误")

    if not record.get("is_super_admin") and not company_id:
        raise HTTPException(status_code=403, detail="用户缺少 company_id")

    svc.record_login_success(user_id)
    token, expires_at = issue_local_access_token(
        user_id=user_id,
        username=str(record.get("username") or ""),
        company_id=company_id,
        auth_source=str(record.get("auth_source") or "local"),
    )
    _audit(
        event_type="login_success",
        actor_id=user_id,
        company_id=company_id,
        target_type="user",
        target_id=user_id,
        action="login",
        decision="success",
    )
    return LoginResponse(
        access_token=token,
        expires_at=expires_at,
        user_id=user_id,
        username=str(record.get("username") or ""),
        company_id=company_id,
    )


@router.post("/password/change", summary="修改当前用户密码")
async def change_password(payload: PasswordChangeRequest,
                          identity: Identity = Depends(get_current_identity)) -> dict:
    svc = get_user_service()
    record = svc.get_local_credential_by_user_id(identity.user_id)
    if not record or str(record.get("user_id") or "") != identity.user_id:
        raise HTTPException(status_code=404, detail="未找到本地登录凭证")
    if not verify_password(payload.old_password, str(record.get("password_hash") or "")):
        raise HTTPException(status_code=401, detail="旧密码错误")
    password_hash = hash_password(payload.new_password, username=identity.username or identity.user_id)
    svc.set_local_password(
        identity.user_id,
        login_identifier=str(record.get("login_identifier") or identity.user_id),
        password_hash=password_hash,
        password_algo=get_settings().auth_password_hash_algo,
    )
    _audit(
        event_type="password_changed",
        actor_id=identity.user_id,
        company_id=identity.company_id,
        target_type="user",
        target_id=identity.user_id,
        action="change_password",
        decision="success",
    )
    return {"ok": True}


@router.post("/logout", summary="退出登录")
async def logout(_: Identity = Depends(get_current_identity)) -> dict:
    return {"ok": True}
