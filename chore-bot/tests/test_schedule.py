from datetime import date
from types import SimpleNamespace as NS

from app.schedule import describe, is_due, nth_weekday_of_month


def task(**kw):
    base = dict(frequency="monthly", weekdays=None, day_of_month=None, nth_week=None, weekday=None, months=None)
    base.update(kw)
    return NS(**base)


def test_daily():
    assert is_due(task(frequency="daily"), date(2026, 11, 2))


def test_weekly():
    t = task(frequency="weekly", weekdays=[0, 3])  # 月・木
    assert is_due(t, date(2026, 11, 2))  # 月
    assert not is_due(t, date(2026, 11, 3))
    assert is_due(t, date(2026, 11, 5))  # 木


def test_monthly_day_clamped_to_month_end():
    t = task(day_of_month=31)
    assert is_due(t, date(2026, 11, 30))
    assert not is_due(t, date(2026, 11, 29))
    assert is_due(t, date(2026, 12, 31))


def test_monthly_nth_weekday():
    assert nth_weekday_of_month(2026, 11, 2, 5) == date(2026, 11, 14)  # 第2土曜
    assert nth_weekday_of_month(2026, 11, -1, 6) == date(2026, 11, 29)  # 最終日曜
    assert nth_weekday_of_month(2026, 11, 5, 0) == date(2026, 11, 30)
    assert nth_weekday_of_month(2026, 2, 5, 0) is None
    assert is_due(task(nth_week=2, weekday=5), date(2026, 11, 14))


def test_seasonal_months():
    t = task(day_of_month=1, months=[3, 9])
    assert is_due(t, date(2026, 9, 1))
    assert not is_due(t, date(2026, 11, 1))


def test_describe():
    assert describe(task(frequency="weekly", weekdays=[3, 0])) == "毎週月・木曜"
    assert describe(task(nth_week=2, weekday=5)) == "毎月第2土曜"
    assert describe(task(day_of_month=1, months=[3, 9])) == "3・9月の1日"
