"""
号码隐私映射服务
- POST /mask       : 真实号 → Token（供客户CRM内部调用）
- GET  /unmask     : Token → 真实号（仅SIP网关内网可达）
- DELETE /mask/:token : 主动注销Token
- GET  /health     : 健康检查
"""

import os
import secrets
import logging
from datetime import datetime, timedelta
from typing import Optional

from fastapi import FastAPI, HTTPException, Request, Depends
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, field_validator
import re

from .database import get_db, Database
from .config import settings
from .auth import verify_internal_key, verify_gateway_key

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

app = FastAPI(
    title="号码隐私映射服务",
    version="1.0.0",
    docs_url="/docs" if settings.DEBUG else None,  # 生产环境关闭swagger
    redoc_url=None,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.ALLOWED_ORIGINS,
    allow_methods=["GET", "POST", "DELETE"],
    allow_headers=["X-Internal-Key", "X-Gateway-Key", "Content-Type"],
)


# ── 数据模型 ──────────────────────────────────────────────

PHONE_RE = re.compile(r"^1[3-9]\d{9}$")

class MaskRequest(BaseModel):
    phone: str
    ttl_days: Optional[int] = None  # None = 永不过期，或继承全局配置

    @field_validator("phone")
    @classmethod
    def validate_phone(cls, v):
        v = v.strip().lstrip("+86")
        if not PHONE_RE.match(v):
            raise ValueError("非法手机号格式")
        return v

class MaskResponse(BaseModel):
    token: str
    expires_at: Optional[str]  # ISO8601 或 null

class UnmaskResponse(BaseModel):
    phone: str


# ── 工具函数 ──────────────────────────────────────────────

def generate_token() -> str:
    """生成格式：tok_<16位hex>，URL-safe，可直接用作SIP URI user部分"""
    return f"tok_{secrets.token_hex(16)}"

def calc_expire(ttl_days: Optional[int]) -> Optional[datetime]:
    effective = ttl_days if ttl_days is not None else settings.DEFAULT_TTL_DAYS
    if effective is None or effective <= 0:
        return None
    return datetime.utcnow() + timedelta(days=effective)


# ── 路由：CRM侧（内部密钥鉴权） ──────────────────────────

@app.post("/mask", response_model=MaskResponse, summary="真实号码 → Token")
async def mask_phone(
    req: MaskRequest,
    request: Request,
    db: Database = Depends(get_db),
    _: None = Depends(verify_internal_key),
):
    """
    客户CRM调用。传入真实手机号，返回Token。
    同一手机号多次调用返回同一Token（幂等）。
    """
    # 幂等：同号码已存在则直接返回
    existing = await db.get_token_by_phone(req.phone)
    if existing:
        logger.info(f"[mask] 复用已有Token phone=***{req.phone[-4:]}")
        return MaskResponse(
            token=existing["token"],
            expires_at=existing["expires_at"],
        )

    token = generate_token()
    expires_at = calc_expire(req.ttl_days)

    await db.insert_mapping(
        token=token,
        phone=req.phone,
        expires_at=expires_at,
        client_ip=request.client.host,
    )

    logger.info(f"[mask] 新建Token phone=***{req.phone[-4:]} token={token[:12]}...")
    return MaskResponse(
        token=token,
        expires_at=expires_at.isoformat() if expires_at else None,
    )


# ── 路由：SIP网关侧（网关密钥鉴权 + IP白名单） ──────────

@app.get("/unmask", response_model=UnmaskResponse, summary="Token → 真实号码")
async def unmask_token(
    token: str,
    request: Request,
    db: Database = Depends(get_db),
    _: None = Depends(verify_gateway_key),
):
    """
    仅SIP网关调用。传入Token，返回真实手机号。
    此接口必须通过防火墙限制，不得对外暴露。
    """
    # IP白名单二次校验
    client_ip = request.client.host
    if settings.GATEWAY_ALLOWED_IPS and client_ip not in settings.GATEWAY_ALLOWED_IPS:
        logger.warning(f"[unmask] IP不在白名单 ip={client_ip} token={token[:12]}...")
        raise HTTPException(status_code=403, detail="IP not allowed")

    row = await db.get_phone_by_token(token)
    if not row:
        logger.warning(f"[unmask] Token不存在 token={token[:12]}...")
        raise HTTPException(status_code=404, detail="Token not found")

    # 检查过期
    if row["expires_at"]:
        exp = datetime.fromisoformat(row["expires_at"])
        if datetime.utcnow() > exp:
            logger.warning(f"[unmask] Token已过期 token={token[:12]}...")
            raise HTTPException(status_code=410, detail="Token expired")

    await db.record_call(token, client_ip)
    logger.info(f"[unmask] 查询成功 token={token[:12]}... ip={client_ip}")
    return UnmaskResponse(phone=row["phone"])


# ── 路由：主动注销 ────────────────────────────────────────

@app.delete("/mask/{token}", summary="注销Token")
async def revoke_token(
    token: str,
    db: Database = Depends(get_db),
    _: None = Depends(verify_internal_key),
):
    """客户主动注销某条线索的Token（如线索作废）"""
    deleted = await db.delete_mapping(token)
    if not deleted:
        raise HTTPException(status_code=404, detail="Token not found")
    logger.info(f"[revoke] Token注销 token={token[:12]}...")
    return {"status": "revoked", "token": token}


# ── 健康检查 ─────────────────────────────────────────────

@app.get("/health")
async def health(db: Database = Depends(get_db)):
    await db.ping()
    return {"status": "ok", "time": datetime.utcnow().isoformat()}
