from typing import Annotated

import asyncpg
from fastapi import Depends, HTTPException, Request, status

from app.database import get_db
from app.jwt_auth import decode_verified_username, get_raw_token


async def get_current_aid(
    request: Request,
    conn: Annotated[asyncpg.Connection, Depends(get_db)],
) -> int:
    token = get_raw_token(request)
    if token is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="認証が必要です",
        )
    username = decode_verified_username(token)
    row = await conn.fetchrow(
        """
        SELECT id
        FROM public.accounts
        WHERE username = $1 AND NOT is_deleted
        """,
        username,
    )
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="ユーザーが見つかりません",
        )
    return int(row["id"])
