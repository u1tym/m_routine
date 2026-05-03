from datetime import date, datetime

import asyncpg

from app.schemas import AvoidInOut
from app.services.adjust_date import resolve_adjusted_date
from app.services.routine_dates import compute_adapt_date


async def load_holiday_dates(conn: asyncpg.Connection, center_year: int) -> frozenset[date]:
    rows = await conn.fetch(
        """
        SELECT date FROM public.holidays
        WHERE date >= $1::date AND date <= $2::date
        """,
        date(center_year - 1, 1, 1),
        date(center_year + 1, 12, 31),
    )
    return frozenset(r["date"] for r in rows)


_ADAPT_MONTH_KEYS = (
    "adapt_jan",
    "adapt_feb",
    "adapt_mar",
    "adapt_apr",
    "adapt_may",
    "adapt_jun",
    "adapt_jul",
    "adapt_aug",
    "adapt_sep",
    "adapt_oct",
    "adapt_nov",
    "adapt_dec",
)


def _month_enabled_for_apply(row: asyncpg.Record, month: int) -> bool:
    key = _ADAPT_MONTH_KEYS[month - 1]
    v = row[key]
    return True if v is None else bool(v)


async def fetch_routine_for_apply(
    conn: asyncpg.Connection, routine_id: int, aid: int
) -> asyncpg.Record | None:
    return await conn.fetchrow(
        """
        SELECT
            r.id,
            r.title,
            r.activity_category_id,
            ad.adapt_jan,
            ad.adapt_feb,
            ad.adapt_mar,
            ad.adapt_apr,
            ad.adapt_may,
            ad.adapt_jun,
            ad.adapt_jul,
            ad.adapt_aug,
            ad.adapt_sep,
            ad.adapt_oct,
            ad.adapt_nov,
            ad.adapt_dec,
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
        INNER JOIN plan.routine_adapt_day ad ON ad.id = r.adapt_id
        LEFT JOIN plan.routine_adjust_day aj ON aj.id = r.adjust_id
        WHERE r.id = $1 AND r.aid = $2 AND NOT r.is_deleted
        """,
        routine_id,
        aid,
    )


def _avoid_from_row(row: asyncpg.Record) -> AvoidInOut:
    return AvoidInOut(
        holiday=row["avoid_holiday"],
        sun=row["avoid_sun"],
        mon=row["avoid_mon"],
        tue=row["avoid_tue"],
        wed=row["avoid_wed"],
        thu=row["avoid_thu"],
        fri=row["avoid_fri"],
        sat=row["avoid_sat"],
    )


async def insert_schedule_if_absent(
    conn: asyncpg.Connection,
    *,
    aid: int,
    title: str,
    on_date: date,
    activity_category_id: int,
    routine_id: int,
) -> bool:
    start = datetime(on_date.year, on_date.month, on_date.day)
    row = await conn.fetchrow(
        """
        INSERT INTO public.schedules (
            title,
            start_datetime,
            duration,
            is_all_day,
            activity_category_id,
            schedule_type,
            location,
            details,
            is_todo_completed,
            is_deleted,
            routine_id,
            aid
        )
        SELECT
            $1,
            $2,
            1,
            true,
            $3,
            'TODO',
            '',
            '',
            false,
            false,
            $4,
            $5
        WHERE NOT EXISTS (
            SELECT 1
            FROM public.schedules s
            WHERE s.routine_id = $4
              AND NOT s.is_deleted
              AND s.start_datetime::date = $6::date
        )
        RETURNING id
        """,
        title,
        start,
        activity_category_id,
        routine_id,
        aid,
        on_date,
    )
    return row is not None


async def apply_routine_to_month(
    conn: asyncpg.Connection,
    *,
    routine_id: int,
    aid: int,
    year: int,
    month: int,
    holiday_dates: frozenset[date],
) -> tuple[list[str], str | None]:
    """
    戻り値: (挿入した日付文字列のリスト, エラーメッセージ)。
    エラー時はメッセージを返し挿入は行わない（該当ルーティンだけスキップ可能）。
    """
    row = await fetch_routine_for_apply(conn, routine_id, aid)
    if row is None:
        return [], "ルーティンが見つからないか削除済みです"

    if not _month_enabled_for_apply(row, month):
        return [], None

    base = compute_adapt_date(year, month, row["what_number"], row["order_week"])
    if base is None:
        return [], None

    final_date: date | None
    if row["alt_day"] is None:
        final_date = base
    else:
        avoid = _avoid_from_row(row)
        final_date = resolve_adjusted_date(
            base, avoid, holiday_dates, int(row["alt_day"])
        )
        if final_date is None:
            return [], "代替日を決定できませんでした（除外範囲が広すぎる可能性があります）"

    inserted: list[str] = []
    if await insert_schedule_if_absent(
        conn,
        aid=aid,
        title=row["title"],
        on_date=final_date,
        activity_category_id=row["activity_category_id"],
        routine_id=row["id"],
    ):
        inserted.append(final_date.isoformat())
    return inserted, None
