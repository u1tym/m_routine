"""plan.routine_adapt_day のルールに基づく日付算出。"""

import calendar
from datetime import date, timedelta


def _last_calendar_day(y: int, m: int) -> int:
    return calendar.monthrange(y, m)[1]


def _python_weekday_to_db(weekday: int) -> int:
    """Python weekday (月=0…日=6) を DB の order_week (日=0…土=6) に変換。"""
    return (weekday + 1) % 7


def compute_adapt_date(year: int, month: int, what_number: int, order_week: int) -> date | None:
    """
    指定年月における適用日を1日分返す。該当なしは None。

    - order_week == -1: カレンダー日ベース（N日、月末、末尾から）
    - order_week in 0..6: その曜日の第N回（負数は末尾から何番目のその曜日か）
    """
    if order_week == -1:
        last = _last_calendar_day(year, month)
        if what_number > 0:
            if what_number <= last:
                return date(year, month, what_number)
            return None
        if what_number == -1:
            return date(year, month, last)
        k = abs(what_number)
        day = last - (k - 1)
        if day >= 1:
            return date(year, month, day)
        return None

    first = date(year, month, 1)
    last_d = date(year, month, _last_calendar_day(year, month))
    matching: list[date] = []
    d = first
    while d <= last_d:
        if _python_weekday_to_db(d.weekday()) == order_week:
            matching.append(d)
        d += timedelta(days=1)
    if not matching:
        return None
    if what_number > 0:
        idx = what_number - 1
        return matching[idx] if idx < len(matching) else None
    idx = len(matching) + what_number
    return matching[idx] if 0 <= idx < len(matching) else None
