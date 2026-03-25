from typing import Annotated

import asyncpg
from fastapi import APIRouter, Depends

from app.database import get_db
from app.schemas import CategoryItem

router = APIRouter(prefix="/categories", tags=["categories"])


@router.get("", response_model=list[CategoryItem])
async def list_categories(
    conn: Annotated[asyncpg.Connection, Depends(get_db)],
) -> list[CategoryItem]:
    rows = await conn.fetch(
        """
        SELECT id, name
        FROM public.activity_categories
        WHERE NOT is_deleted
        ORDER BY id
        """
    )
    return [CategoryItem(id=r["id"], name=r["name"]) for r in rows]
