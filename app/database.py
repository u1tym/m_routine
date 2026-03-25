from collections.abc import AsyncIterator, AsyncGenerator
from contextlib import asynccontextmanager

import asyncpg
from fastapi import FastAPI

from app.config import settings

_pool: asyncpg.Pool | None = None


async def get_pool() -> asyncpg.Pool:
    global _pool
    if _pool is None:
        raise RuntimeError("DB プールが初期化されていません")
    return _pool


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    global _pool
    _pool = await asyncpg.create_pool(
        dsn=settings.database_dsn,
        min_size=1,
        max_size=10,
    )
    try:
        yield
    finally:
        if _pool is not None:
            await _pool.close()
            _pool = None


async def get_db() -> AsyncGenerator[asyncpg.Connection, None]:
    pool = await get_pool()
    async with pool.acquire() as conn:
        yield conn
