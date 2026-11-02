"""環境変数から設定を読み込む。"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from zoneinfo import ZoneInfo


def _normalize_db_url(url: str) -> str:
    # Supabase / Render / Heroku 形式の postgres:// を SQLAlchemy + psycopg3 用に変換
    if url.startswith("postgres://"):
        url = "postgresql://" + url[len("postgres://"):]
    if url.startswith("postgresql://"):
        url = "postgresql+psycopg://" + url[len("postgresql://"):]
    return url


@dataclass(frozen=True)
class Settings:
    line_channel_secret: str = field(default_factory=lambda: os.getenv("LINE_CHANNEL_SECRET", ""))
    line_channel_access_token: str = field(default_factory=lambda: os.getenv("LINE_CHANNEL_ACCESS_TOKEN", ""))
    liff_id: str = field(default_factory=lambda: os.getenv("LIFF_ID", ""))
    line_login_channel_id: str = field(default_factory=lambda: os.getenv("LINE_LOGIN_CHANNEL_ID", ""))
    base_url: str = field(default_factory=lambda: os.getenv("BASE_URL", "http://localhost:8000").rstrip("/"))
    database_url: str = field(
        default_factory=lambda: _normalize_db_url(os.getenv("DATABASE_URL", "sqlite:///./chore_bot.db"))
    )
    cron_secret: str = field(default_factory=lambda: os.getenv("CRON_SECRET", ""))
    dashboard_key: str = field(default_factory=lambda: os.getenv("DASHBOARD_KEY", ""))
    allowed_user_ids: frozenset[str] = field(
        default_factory=lambda: frozenset(
            u.strip() for u in os.getenv("ALLOWED_USER_IDS", "").split(",") if u.strip()
        )
    )
    timezone: str = field(default_factory=lambda: os.getenv("TIMEZONE", "Asia/Tokyo"))

    @property
    def tz(self) -> ZoneInfo:
        return ZoneInfo(self.timezone)

    @property
    def dashboard_url(self) -> str:
        """LINE メッセージから開くダッシュボードの URL。LIFF があればそちらを優先。"""
        if self.liff_id:
            return f"https://liff.line.me/{self.liff_id}"
        # 2人だけのトークで使う前提なので合言葉を URL に含めてワンタップで開けるようにする
        suffix = f"?key={self.dashboard_key}" if self.dashboard_key else ""
        return f"{self.base_url}/dashboard{suffix}"


settings = Settings()
