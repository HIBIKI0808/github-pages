"""DB 接続とテーブル定義（SQLite / PostgreSQL 両対応）。"""
from __future__ import annotations

from collections.abc import Iterator
from datetime import date, datetime

from sqlalchemy import (
    JSON,
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
    create_engine,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, relationship, sessionmaker

from .config import settings


class Base(DeclarativeBase):
    pass


class Task(Base):
    """タスクのテンプレート（「いつ・何をするか」の定義）。"""

    __tablename__ = "tasks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    key: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    title: Mapped[str] = mapped_column(String(200))
    category: Mapped[str] = mapped_column(String(32), index=True)
    # "daily" | "weekly" | "monthly"
    frequency: Mapped[str] = mapped_column(String(16), index=True)
    # weekly: 実施する曜日のリスト（0=月 ... 6=日）
    weekdays: Mapped[list[int] | None] = mapped_column(JSON, nullable=True)
    # monthly: 日付指定（1〜31, 月末を超える場合はその月の最終日）
    day_of_month: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # monthly: 第N◯曜日指定（nth_week=1〜5, -1=最終 / weekday=0〜6）
    nth_week: Mapped[int | None] = mapped_column(Integer, nullable=True)
    weekday: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # 実施する月（季節タスク用）。None なら毎月
    months: Mapped[list[int] | None] = mapped_column(JSON, nullable=True)
    minutes: Mapped[int] = mapped_column(Integer, default=5)
    note: Mapped[str] = mapped_column(String(500), default="")
    # 未完了のとき翌日以降も「持ち越し」として表示するか
    carry_over: Mapped[bool] = mapped_column(Boolean, default=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)


class TaskInstance(Base):
    """ある日に発生したタスク 1 件（チェック状態を持つ）。"""

    __tablename__ = "task_instances"
    __table_args__ = (UniqueConstraint("task_id", "due_date", name="uq_task_due"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    task_id: Mapped[int] = mapped_column(ForeignKey("tasks.id", ondelete="CASCADE"), index=True)
    due_date: Mapped[date] = mapped_column(Date, index=True)
    done: Mapped[bool] = mapped_column(Boolean, default=False)
    done_by: Mapped[str | None] = mapped_column(String(100), nullable=True)
    done_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    task: Mapped[Task] = relationship(lazy="joined")


class Recipient(Base):
    """定期配信の送り先（1:1 トークのユーザー or グループ）。"""

    __tablename__ = "recipients"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    target_id: Mapped[str] = mapped_column(String(64), unique=True)
    # "user" | "group" | "room"
    kind: Mapped[str] = mapped_column(String(16))
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class Member(Base):
    """LINE ユーザー ID と表示名のキャッシュ（「誰が完了したか」の表示用）。"""

    __tablename__ = "members"

    user_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    display_name: Mapped[str] = mapped_column(String(100))


class DeliveryLog(Base):
    """定期配信の送信記録（cron の再試行で同じ日に二重送信しないため）。"""

    __tablename__ = "delivery_logs"
    __table_args__ = (UniqueConstraint("kind", "target_date", name="uq_delivery"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    kind: Mapped[str] = mapped_column(String(16))
    target_date: Mapped[date] = mapped_column(Date)
    sent_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


def _make_engine(url: str):
    kwargs: dict = {"pool_pre_ping": True}
    if url.startswith("sqlite"):
        kwargs["connect_args"] = {"check_same_thread": False}
    return create_engine(url, **kwargs)


engine = _make_engine(settings.database_url)
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)


def init_db() -> None:
    from .seed_tasks import seed_tasks

    Base.metadata.create_all(engine)
    with SessionLocal() as db:
        seed_tasks(db)


def get_db() -> Iterator[Session]:
    with SessionLocal() as db:
        yield db
