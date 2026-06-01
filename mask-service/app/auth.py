"""鉴权依赖：两套密钥分别保护不同接口"""

from fastapi import Header, HTTPException
from .config import settings


async def verify_internal_key(x_internal_key: str = Header(...)):
    """CRM侧调用 /mask 和 DELETE /mask/:token 时验证"""
    if x_internal_key != settings.INTERNAL_API_KEY:
        raise HTTPException(status_code=401, detail="Invalid internal key")


async def verify_gateway_key(x_gateway_key: str = Header(...)):
    """SIP网关调用 /unmask 时验证"""
    if x_gateway_key != settings.GATEWAY_API_KEY:
        raise HTTPException(status_code=401, detail="Invalid gateway key")
