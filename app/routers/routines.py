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


@router.put("/{routine_id}", response_model=RoutineCreateResponse)
async def update_routine(
    routine_id: int,
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
        current = await conn.fetchrow(
            """
            SELECT id, adapt_id, adjust_id
            FROM plan.routine
            WHERE id = $1 AND NOT is_deleted
            FOR UPDATE
            """,
            routine_id,
        )
        if current is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="ルーティンが見つからないか、削除済みです",
            )

        adapt_id: int = int(current["adapt_id"])
        adjust_id: int | None = current["adjust_id"]

        try:
            # 適用日マスタは既存行を更新（adapt_id は変えない）
            await conn.execute(
                """
                UPDATE plan.routine_adapt_day
                SET explain = $1, what_number = $2, order_week = $3
                WHERE id = $4
                """,
                _explain_adapt(body.title, body.adapt),
                body.adapt.number,
                body.adapt.week,
                adapt_id,
            )

            # 調整日マスタは、既存があれば更新、なければ追加、無ければ紐付け解除
            if body.adjust is None:
                await conn.execute(
                    """
                    UPDATE plan.routine
                    SET title = $1, activity_category_id = $2, adjust_id = NULL
                    WHERE id = $3
                    """,
                    body.title,
                    body.activity_category_id,
                    routine_id,
                )
            else:
                if adjust_id is not None:
                    await conn.execute(
                        """
                        UPDATE plan.routine_adjust_day
                        SET explain = $1,
                            avoid_holiday = $2,
                            avoid_sun = $3,
                            avoid_mon = $4,
                            avoid_tue = $5,
                            avoid_wed = $6,
                            avoid_thu = $7,
                            avoid_fri = $8,
                            avoid_sat = $9,
                            alt_day = $10
                        WHERE id = $11
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
                        adjust_id,
                    )
                    await conn.execute(
                        """
                        UPDATE plan.routine
                        SET title = $1, activity_category_id = $2
                        WHERE id = $3
                        """,
                        body.title,
                        body.activity_category_id,
                        routine_id,
                    )
                else:
                    new_adjust_id = await conn.fetchval(
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
                    await conn.execute(
                        """
                        UPDATE plan.routine
                        SET title = $1, activity_category_id = $2, adjust_id = $3
                        WHERE id = $4
                        """,
                        body.title,
                        body.activity_category_id,
                        int(new_adjust_id),
                        routine_id,
                    )
        except asyncpg.UniqueViolationError:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="同じ title のルーティンが既に存在します",
            ) from None

    return RoutineCreateResponse(id=routine_id)


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
