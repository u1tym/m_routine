from typing import Annotated

import asyncpg
from fastapi import APIRouter, Depends, HTTPException, status

from app.database import get_db
from app.schemas import (
    ApplyResponse,
    MessageResponse,
    RoutineCreateRequest,
    RoutineCreateResponse,
    RoutineListItem,
    YearMonthBody,
    AdaptInOut,
    AdjustInOut,
    AvoidInOut,
)
from app.services.routine_apply import (
    apply_routine_to_month,
    load_holiday_dates,
)

router = APIRouter(prefix="/routines", tags=["routines"])


def _explain_adapt(title: str, adapt: AdaptInOut) -> str:
    return f"{title} の適用日 (number={adapt.number}, week={adapt.week})"


def _explain_adjust(title: str) -> str:
    return f"{title} の調整日"


@router.get("", response_model=list[RoutineListItem])
async def list_routines(
    conn: Annotated[asyncpg.Connection, Depends(get_db)],
) -> list[RoutineListItem]:
    rows = await conn.fetch(
        """
        SELECT
            r.id,
            r.title,
            r.activity_category_id,
            c.name AS activity_category_name,
            ad.what_number,
            ad.order_week,
            aj.avoid_holiday,
            aj.avoid_sun,
            aj.avoid_mon,
            aj.avoid_tue,
            aj.avoid_wed,
            aj.avoid_thu,
            aj.avoid_fri,
            aj.avoid_sat,
            aj.alt_day
        FROM plan.routine r
        INNER JOIN public.activity_categories c ON c.id = r.activity_category_id
        INNER JOIN plan.routine_adapt_day ad ON ad.id = r.adapt_id
        LEFT JOIN plan.routine_adjust_day aj ON aj.id = r.adjust_id
        WHERE NOT r.is_deleted
        ORDER BY r.id
        """
    )
    out: list[RoutineListItem] = []
    for r in rows:
        adapt = AdaptInOut(number=r["what_number"], week=r["order_week"])
        adjust: AdjustInOut | None = None
        if r["alt_day"] is not None:
            adjust = AdjustInOut(
                avoid=AvoidInOut(
                    holiday=r["avoid_holiday"],
                    sun=r["avoid_sun"],
                    mon=r["avoid_mon"],
                    tue=r["avoid_tue"],
                    wed=r["avoid_wed"],
                    thu=r["avoid_thu"],
                    fri=r["avoid_fri"],
                    sat=r["avoid_sat"],
                ),
                alt=int(r["alt_day"]),
            )
        out.append(
            RoutineListItem(
                id=r["id"],
                title=r["title"],
                activity_category_id=r["activity_category_id"],
                activity_category_name=r["activity_category_name"],
                adapt=adapt,
                adjust=adjust,
            )
        )
    return out


@router.post("", response_model=RoutineCreateResponse, status_code=status.HTTP_201_CREATED)
async def create_routine(
    body: RoutineCreateRequest,
    conn: Annotated[asyncpg.Connection, Depends(get_db)],
) -> RoutineCreateResponse:
    cat = await conn.fetchrow(
        """
        SELECT 1 FROM public.activity_categories
        WHERE id = $1 AND NOT is_deleted
        """,
        body.activity_category_id,
    )
    if cat is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="activity_category_id が無効です",
        )

    async with conn.transaction():
        adapt_id = await conn.fetchval(
            """
            INSERT INTO plan.routine_adapt_day (explain, what_number, order_week)
            VALUES ($1, $2, $3)
            RETURNING id
            """,
            _explain_adapt(body.title, body.adapt),
            body.adapt.number,
            body.adapt.week,
        )
        adjust_id: int | None = None
        if body.adjust is not None:
            adjust_id = await conn.fetchval(
                """
                INSERT INTO plan.routine_adjust_day (
                    explain,
                    avoid_holiday,
                    avoid_sun,
                    avoid_mon,
                    avoid_tue,
                    avoid_wed,
                    avoid_thu,
                    avoid_fri,
                    avoid_sat,
                    alt_day
                )
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)
                RETURNING id
                """,
                _explain_adjust(body.title),
                body.adjust.avoid.holiday,
                body.adjust.avoid.sun,
                body.adjust.avoid.mon,
                body.adjust.avoid.tue,
                body.adjust.avoid.wed,
                body.adjust.avoid.thu,
                body.adjust.avoid.fri,
                body.adjust.avoid.sat,
                body.adjust.alt,
            )

        try:
            rid = await conn.fetchval(
                """
                INSERT INTO plan.routine (
                    title,
                    activity_category_id,
                    adapt_id,
                    adjust_id,
                    is_deleted
                )
                VALUES ($1, $2, $3, $4, false)
                RETURNING id
                """,
                body.title,
                body.activity_category_id,
                adapt_id,
                adjust_id,
            )
        except asyncpg.UniqueViolationError:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="同じ title のルーティンが既に存在します",
            ) from None

    return RoutineCreateResponse(id=int(rid))


@router.delete("/{routine_id}", response_model=MessageResponse)
async def delete_routine(
    routine_id: int,
    conn: Annotated[asyncpg.Connection, Depends(get_db)],
) -> MessageResponse:
    result = await conn.execute(
        """
        UPDATE plan.routine
        SET is_deleted = true
        WHERE id = $1 AND NOT is_deleted
        """,
        routine_id,
    )
    if result == "UPDATE 0":
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="ルーティンが見つからないか、既に削除済みです",
        )
    return MessageResponse(message="削除フラグを設定しました")


@router.post("/{routine_id}/apply", response_model=ApplyResponse)
async def apply_single_routine(
    routine_id: int,
    body: YearMonthBody,
    conn: Annotated[asyncpg.Connection, Depends(get_db)],
) -> ApplyResponse:
    holidays = await load_holiday_dates(conn, body.year)
    dates, err = await apply_routine_to_month(
        conn,
        routine_id=routine_id,
        year=body.year,
        month=body.month,
        holiday_dates=holidays,
    )
    if err:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=err)
    return ApplyResponse(inserted_count=len(dates), dates=dates)


@router.post("/apply-all", response_model=ApplyResponse)
async def apply_all_routines(
    body: YearMonthBody,
    conn: Annotated[asyncpg.Connection, Depends(get_db)],
) -> ApplyResponse:
    ids = [
        r["id"]
        for r in await conn.fetch(
            """
            SELECT id FROM plan.routine
            WHERE NOT is_deleted
            ORDER BY id
            """
        )
    ]
    holidays = await load_holiday_dates(conn, body.year)
    all_dates: list[str] = []
    errors: list[str] = []
    for rid in ids:
        dates, err = await apply_routine_to_month(
            conn,
            routine_id=rid,
            year=body.year,
            month=body.month,
            holiday_dates=holidays,
        )
        if err:
            errors.append(f"id={rid}: {err}")
            continue
        all_dates.extend(dates)
    return ApplyResponse(
        inserted_count=len(all_dates), dates=all_dates, errors=errors
    )
