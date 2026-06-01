"""配置：从环境变量读取，支持 .env 文件"""

import os
from typing import Optional, List
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # 数据库
    DATABASE_URL: str = "sqlite:///./mask.db"

    # 鉴权密钥（必须在部署时改掉）
    INTERNAL_API_KEY: str = "CHANGE_ME_INTERNAL_KEY"   # CRM侧调用 /mask
    GATEWAY_API_KEY: str  = "CHANGE_ME_GATEWAY_KEY"    # SIP网关调用 /unmask

    # SIP网关IP白名单（逗号分隔，空=不限制，生产必须填）
    GATEWAY_ALLOWED_IPS: List[str] = []

    # Token默认有效期（天），None或0=永不过期
    DEFAULT_TTL_DAYS: Optional[int] = None

    # 其他
    DEBUG: bool = False
    ALLOWED_ORIGINS: List[str] = []

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        raw = os.getenv("GATEWAY_ALLOWED_IPS", "")
        if raw:
            object.__setattr__(
                self,
                "GATEWAY_ALLOWED_IPS",
                [ip.strip() for ip in raw.split(",") if ip.strip()],
            )


settings = Settings()
