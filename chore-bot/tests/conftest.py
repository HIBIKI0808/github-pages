import os
import sys
from pathlib import Path

# テスト用の設定（app を import する前にセット）
os.environ["DATABASE_URL"] = "sqlite:///:memory:"
os.environ["LINE_CHANNEL_SECRET"] = "test-secret"
os.environ["LINE_CHANNEL_ACCESS_TOKEN"] = ""  # 空なので LINE への送信は行われない
os.environ["CRON_SECRET"] = "cron-secret"
os.environ["DASHBOARD_KEY"] = "dash-key"
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest  # noqa: E402
from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402

from app import database  # noqa: E402

# in-memory SQLite を全接続で共有する
database.engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
database.SessionLocal.configure(bind=database.engine)


@pytest.fixture(autouse=True)
def fresh_db():
    database.Base.metadata.drop_all(database.engine)
    database.init_db()
    yield


@pytest.fixture
def db():
    with database.SessionLocal() as s:
        yield s
