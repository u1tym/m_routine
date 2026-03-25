"""routine_adjust_day に基づく除外日・代替日の解決。"""

from datetime import date, timedelta

from app.schemas import AvoidInOut


def _db_weekday(d: date) -> int:
    """日=0 … 土=6。"""
    return (d.weekday() + 1) % 7


def is_avoided(
    d: date,
    avoid: AvoidInOut,
    holiday_dates: frozenset[date],
) -> bool:
    if avoid.holiday and d in holiday_dates:
        return True
    wd = _db_weekday(d)
    flags = (
        (avoid.sun, 0),
        (avoid.mon, 1),
        (avoid.tue, 2),
        (avoid.wed, 3),
        (avoid.thu, 4),
        (avoid.fri, 5),
        (avoid.sat, 6),
    )
    for flag, target in flags:
        if flag and wd == target:
            return True
    return False


def resolve_adjusted_date(
    base: date,
    avoid: AvoidInOut,
    holiday_dates: frozenset[date],
    alt_day: int,
    max_steps: int = 400,
) -> date | None:
    """
    base が除外に該当しないなら base。
    該当する場合は alt_day の方向に最大 max_steps 日探索し、最初の非除外日を返す。
    見つからなければ None。
    """
    if not is_avoided(base, avoid, holiday_dates):
        return base
    step = 1 if alt_day == 1 else -1
    cur = base
    for _ in range(max_steps):
        cur += timedelta(days=step)
        if not is_avoided(cur, avoid, holiday_dates):
            return cur
    return None
