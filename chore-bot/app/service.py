"""タスクの発生・チェック・集計のロジック。"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import settings
from .database import Task, TaskInstance
from .schedule import is_due
from .seed_tasks import CATEGORIES

FREQ_ORDER = {"daily": 0, "weekly": 1, "monthly": 2}
FREQ_LABEL = {"daily": "毎日", "weekly": "週次", "monthly": "月次"}
# 持ち越し表示をさかのぼる日数
CARRY_OVER_DAYS = {"daily": 1, "weekly": 6, "monthly": 30}


def today() -> date:
    return datetime.now(settings.tz).date()


def ensure_instances(db: Session, d: date) -> list[TaskInstance]:
    """その日に発生するタスクのインスタンスを作成（既にあればそのまま）して返す。"""
    tasks = db.scalars(select(Task).where(Task.active.is_(True))).all()
    due = [t for t in tasks if is_due(t, d)]
    existing = {
        i.task_id: i
        for i in db.scalars(select(TaskInstance).where(TaskInstance.due_date == d)).unique()
    }
    created = False
    for t in due:
        if t.id not in existing:
            inst = TaskInstance(task_id=t.id, due_date=d)
            db.add(inst)
            existing[t.id] = inst
            created = True
    if created:
        db.commit()
    return _sorted([existing[t.id] for t in due])


def _sorted(instances: list[TaskInstance]) -> list[TaskInstance]:
    cat_order = list(CATEGORIES)
    return sorted(
        instances,
        key=lambda i: (
            FREQ_ORDER.get(i.task.frequency, 9),
            cat_order.index(i.task.category) if i.task.category in cat_order else 99,
            i.task.sort_order,
        ),
    )


def carry_over_instances(db: Session, d: date) -> list[TaskInstance]:
    """過去に発生して未完了のまま残っている週次・月次タスク（同じタスクは最新の1件だけ）。"""
    since = d - timedelta(days=max(CARRY_OVER_DAYS.values()))
    rows = db.scalars(
        select(TaskInstance)
        .join(Task)
        .where(
            TaskInstance.due_date < d,
            TaskInstance.due_date >= since,
            TaskInstance.done.is_(False),
            Task.carry_over.is_(True),
            Task.active.is_(True),
        )
        .order_by(TaskInstance.due_date.desc())
    ).unique().all()
    latest: dict[int, TaskInstance] = {}
    for inst in rows:
        window = CARRY_OVER_DAYS.get(inst.task.frequency, 0)
        if (d - inst.due_date).days <= window and inst.task_id not in latest:
            latest[inst.task_id] = inst
    # 今日も同じタスクが発生しているなら持ち越しは不要
    todays = set(db.scalars(select(TaskInstance.task_id).where(TaskInstance.due_date == d)))
    return _sorted([i for tid, i in latest.items() if tid not in todays])


@dataclass
class Board:
    date: date
    today: list[TaskInstance]
    carry_over: list[TaskInstance] = field(default_factory=list)

    @property
    def all(self) -> list[TaskInstance]:
        return self.today + self.carry_over

    @property
    def remaining(self) -> list[TaskInstance]:
        return [i for i in self.all if not i.done]

    @property
    def done_count(self) -> int:
        return sum(1 for i in self.all if i.done)

    @property
    def total(self) -> int:
        return len(self.all)

    @property
    def remaining_minutes(self) -> int:
        return sum(i.task.minutes for i in self.remaining)


def get_board(db: Session, d: date | None = None) -> Board:
    d = d or today()
    return Board(date=d, today=ensure_instances(db, d), carry_over=carry_over_instances(db, d))


def set_done(db: Session, instance_id: int, done: bool, by: str | None) -> TaskInstance | None:
    inst = db.get(TaskInstance, instance_id)
    if inst is None:
        return None
    inst.done = done
    inst.done_by = by if done else None
    inst.done_at = datetime.now(settings.tz) if done else None
    db.commit()
    db.refresh(inst)
    return inst


def toggle(db: Session, instance_id: int, by: str | None) -> TaskInstance | None:
    inst = db.get(TaskInstance, instance_id)
    if inst is None:
        return None
    return set_done(db, instance_id, not inst.done, by)


def serialize_instance(inst: TaskInstance) -> dict:
    t = inst.task
    cat = CATEGORIES.get(t.category, {"label": t.category, "emoji": "📌"})
    return {
        "id": inst.id,
        "task_id": t.id,
        "title": t.title,
        "note": t.note,
        "category": t.category,
        "category_label": cat["label"],
        "category_emoji": cat["emoji"],
        "frequency": t.frequency,
        "frequency_label": FREQ_LABEL.get(t.frequency, t.frequency),
        "minutes": t.minutes,
        "due_date": inst.due_date.isoformat(),
        "done": inst.done,
        "done_by": inst.done_by,
        "done_at": inst.done_at.isoformat() if inst.done_at else None,
    }


def serialize_board(board: Board) -> dict:
    return {
        "date": board.date.isoformat(),
        "total": board.total,
        "done": board.done_count,
        "remaining": len(board.remaining),
        "remaining_minutes": board.remaining_minutes,
        "today": [serialize_instance(i) for i in board.today],
        "carry_over": [serialize_instance(i) for i in board.carry_over],
        "categories": CATEGORIES,
    }
