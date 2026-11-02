"""「その日にやるべきタスクか？」を判定する純粋関数。"""
from __future__ import annotations

import calendar
from datetime import date
from typing import Protocol


class Schedulable(Protocol):
    frequency: str
    weekdays: list[int] | None
    day_of_month: int | None
    nth_week: int | None
    weekday: int | None
    months: list[int] | None


def nth_weekday_of_month(year: int, month: int, nth: int, weekday: int) -> date | None:
    """その月の第 nth weekday（nth=-1 は最終）。存在しなければ None（例: 第5月曜がない月）。"""
    days = [d for d in range(1, calendar.monthrange(year, month)[1] + 1)
            if date(year, month, d).weekday() == weekday]
    if nth == -1:
        return date(year, month, days[-1])
    if 1 <= nth <= len(days):
        return date(year, month, days[nth - 1])
    return None


def is_due(task: Schedulable, d: date) -> bool:
    if task.frequency == "daily":
        return True
    if task.frequency == "weekly":
        return d.weekday() in (task.weekdays or [])
    if task.frequency == "monthly":
        if task.months and d.month not in task.months:
            return False
        if task.day_of_month is not None:
            last_day = calendar.monthrange(d.year, d.month)[1]
            # 31日指定でも30日しかない月は30日に実施
            return d.day == min(task.day_of_month, last_day)
        if task.nth_week is not None and task.weekday is not None:
            return nth_weekday_of_month(d.year, d.month, task.nth_week, task.weekday) == d
        return False
    return False


WEEKDAY_JA = "月火水木金土日"


def describe(task: Schedulable) -> str:
    """スケジュールを人間向けの文字列にする（例: 毎月第2土曜）。"""
    if task.frequency == "daily":
        base = "毎日"
    elif task.frequency == "weekly":
        base = "毎週" + "・".join(WEEKDAY_JA[w] for w in sorted(task.weekdays or [])) + "曜"
    elif task.day_of_month is not None:
        base = f"毎月{task.day_of_month}日"
    elif task.nth_week == -1:
        base = f"毎月最終{WEEKDAY_JA[task.weekday]}曜"
    else:
        base = f"毎月第{task.nth_week}{WEEKDAY_JA[task.weekday]}曜"
    if task.frequency == "monthly" and task.months:
        base = base.replace("毎月", "・".join(map(str, task.months)) + "月の")
    return base
