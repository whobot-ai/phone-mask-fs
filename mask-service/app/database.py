"""
数据库层：支持 SQLite（开发/轻量部署）和 PostgreSQL（生产）
通过 DATABASE_URL 环境变量切换：
  sqlite:///./mask.db
  postgresql+asyncpg://user:pass@host/dbname
"""

import logging
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Optional, AsyncGenerator

import aiosqlite
import asyncpg

from .config import settings

logger = logging.getLogger(__name__)


# ── 建表SQL（方言兼容） ───────────────────────────────────

SQLITE_SCHEMA = """
CREATE TABLE IF NOT EXISTS phone_tokens (
    token       TEXT PRIMARY KEY,
    phone       TEXT NOT NULL,
    created_at  TEXT NOT NULL,
    expires_at  TEXT,
    client_ip   TEXT,
    call_count  INTEGER DEFAULT 0,
    last_called TEXT
);
CREATE INDEX IF NOT EXISTS idx_phone ON phone_tokens(phone);
"""

PG_SCHEMA = """
CREATE TABLE IF NOT EXISTS phone_tokens (
    token       TEXT PRIMARY KEY,
    phone       TEXT NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    expires_at  TIMESTAMPTZ,
    client_ip   TEXT,
    call_count  INTEGER DEFAULT 0,
    last_called TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS idx_phone ON phone_tokens(phone);
"""


class Database:
    """统一接口，内部区分SQLite/PG"""

    def __init__(self):
        self._sqlite: Optional[aiosqlite.Connection] = None
        self._pg_pool: Optional[asyncpg.Pool] = None
        self._is_pg = settings.DATABASE_URL.startswith("postgresql")

    async def connect(self):
        if self._is_pg:
            self._pg_pool = await asyncpg.create_pool(
                settings.DATABASE_URL,
                min_size=2,
                max_size=10,
            )
            async with self._pg_pool.acquire() as conn:
                await conn.execute(PG_SCHEMA)
            logger.info("PostgreSQL 连接池已建立")
        else:
            db_path = settings.DATABASE_URL.replace("sqlite:///", "")
            self._sqlite = await aiosqlite.connect(db_path)
            self._sqlite.row_factory = aiosqlite.Row
            await self._sqlite.executescript(SQLITE_SCHEMA)
            await self._sqlite.commit()
            logger.info(f"SQLite 已连接：{db_path}")

    async def disconnect(self):
        if self._pg_pool:
            await self._pg_pool.close()
        if self._sqlite:
            await self._sqlite.close()

    async def ping(self):
        if self._is_pg:
            async with self._pg_pool.acquire() as conn:
                await conn.fetchval("SELECT 1")
        else:
            await self._sqlite.execute("SELECT 1")

    # ── 写入映射 ──────────────────────────────────────────

    async def insert_mapping(
        self,
        token: str,
        phone: str,
        expires_at: Optional[datetime],
        client_ip: str,
    ):
        now = datetime.utcnow().isoformat()
        exp = expires_at.isoformat() if expires_at else None

        if self._is_pg:
            async with self._pg_pool.acquire() as conn:
                await conn.execute(
                    """
                    INSERT INTO phone_tokens(token, phone, created_at, expires_at, client_ip)
                    VALUES($1, $2, now(), $3, $4)
                    ON CONFLICT(token) DO NOTHING
                    """,
                    token, phone, expires_at, client_ip,
                )
        else:
            await self._sqlite.execute(
                """
                INSERT OR IGNORE INTO phone_tokens(token, phone, created_at, expires_at, client_ip)
                VALUES(?, ?, ?, ?, ?)
                """,
                (token, phone, now, exp, client_ip),
            )
            await self._sqlite.commit()

    # ── 查询：手机号 → Token（幂等用） ───────────────────

    async def get_token_by_phone(self, phone: str) -> Optional[dict]:
        if self._is_pg:
            async with self._pg_pool.acquire() as conn:
                row = await conn.fetchrow(
                    "SELECT token, expires_at FROM phone_tokens WHERE phone=$1 LIMIT 1",
                    phone,
                )
                return dict(row) if row else None
        else:
            async with self._sqlite.execute(
                "SELECT token, expires_at FROM phone_tokens WHERE phone=? LIMIT 1",
                (phone,),
            ) as cur:
                row = await cur.fetchone()
                return dict(row) if row else None

    # ── 查询：Token → 手机号 ─────────────────────────────

    async def get_phone_by_token(self, token: str) -> Optional[dict]:
        if self._is_pg:
            async with self._pg_pool.acquire() as conn:
                row = await conn.fetchrow(
                    "SELECT phone, expires_at FROM phone_tokens WHERE token=$1",
                    token,
                )
                return dict(row) if row else None
        else:
            async with self._sqlite.execute(
                "SELECT phone, expires_at FROM phone_tokens WHERE token=?",
                (token,),
            ) as cur:
                row = await cur.fetchone()
                return dict(row) if row else None

    # ── 记录每次呼叫 ──────────────────────────────────────

    async def record_call(self, token: str, client_ip: str):
        now = datetime.utcnow().isoformat()
        if self._is_pg:
            async with self._pg_pool.acquire() as conn:
                await conn.execute(
                    """
                    UPDATE phone_tokens
                    SET call_count = call_count + 1, last_called = now()
                    WHERE token = $1
                    """,
                    token,
                )
        else:
            await self._sqlite.execute(
                """
                UPDATE phone_tokens
                SET call_count = call_count + 1, last_called = ?
                WHERE token = ?
                """,
                (now, token),
            )
            await self._sqlite.commit()

    # ── 删除映射 ──────────────────────────────────────────

    async def delete_mapping(self, token: str) -> bool:
        if self._is_pg:
            async with self._pg_pool.acquire() as conn:
                result = await conn.execute(
                    "DELETE FROM phone_tokens WHERE token=$1", token
                )
                return result != "DELETE 0"
        else:
            cur = await self._sqlite.execute(
                "DELETE FROM phone_tokens WHERE token=?", (token,)
            )
            await self._sqlite.commit()
            return cur.rowcount > 0


# ── 单例 + FastAPI 依赖注入 ───────────────────────────────

_db = Database()

async def get_db() -> AsyncGenerator[Database, None]:
    yield _db

async def startup():
    await _db.connect()

async def shutdown():
    await _db.disconnect()
