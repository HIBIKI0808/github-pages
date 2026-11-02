"""FastAPI アプリ本体: LINE Webhook / 定期配信用 cron エンドポイント / ダッシュボード API。"""
from __future__ import annotations

import hmac
import json
import logging
from contextlib import asynccontextmanager
from datetime import date, datetime, timedelta
from pathlib import Path
from urllib.parse import parse_qs, unquote

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from . import line_api, messages, service
from .config import settings
from .database import DeliveryLog, Member, Recipient, SessionLocal, Task, get_db, init_db
from .schedule import describe
from .seed_tasks import CATEGORIES

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("chore-bot")
STATIC_DIR = Path(__file__).parent / "static"


@asynccontextmanager
async def lifespan(_: FastAPI):
    init_db()
    yield


app = FastAPI(title="家事タスク LINE ボット", lifespan=lifespan)


@app.get("/")
def root():
    return RedirectResponse("/dashboard")


@app.get("/healthz")
def healthz():
    return {"ok": True, "today": service.today().isoformat()}


# =====================================================================
# LINE Webhook
# =====================================================================
@app.post("/callback")
async def callback(request: Request, x_line_signature: str = Header(default="")):
    body = await request.body()
    if not line_api.verify_signature(body, x_line_signature):
        raise HTTPException(status_code=400, detail="invalid signature")
    payload = json.loads(body or b"{}")
    for event in payload.get("events", []):
        try:
            with SessionLocal() as db:
                await handle_event(db, event)
        except Exception:  # 1件の失敗で他イベントを落とさない
            log.exception("イベント処理に失敗: %s", event.get("type"))
    return "OK"


def _chat_target(source: dict) -> tuple[str, str]:
    kind = source.get("type", "user")
    target = source.get("groupId") or source.get("roomId") or source.get("userId", "")
    return kind, target


def _set_recipient(db: Session, kind: str, target: str, active: bool) -> None:
    rec = db.scalar(select(Recipient).where(Recipient.target_id == target))
    if rec is None:
        rec = Recipient(target_id=target, kind=kind, active=active)
        db.add(rec)
    rec.active = active
    db.commit()


async def _member_name(db: Session, source: dict) -> str | None:
    user_id = source.get("userId")
    if not user_id:
        return None
    member = db.get(Member, user_id)
    if member:
        return member.display_name
    name = await line_api.get_display_name(user_id, source.get("groupId"), source.get("roomId"))
    if name:
        db.add(Member(user_id=user_id, display_name=name))
        db.commit()
    return name


async def handle_event(db: Session, event: dict) -> None:
    etype = event.get("type")
    source = event.get("source", {})
    kind, target = _chat_target(source)
    token = event.get("replyToken")

    if etype in ("follow", "join"):
        _set_recipient(db, kind, target, True)
        welcome = messages.text_message(
            "はじめまして！家事ボットです 🧹\n毎朝このトークに今日の家事リストを届けます。\n\n"
            + messages.HELP_TEXT
        )
        await line_api.reply(token, [welcome, messages.board_message(service.get_board(db))])
        return

    if etype in ("unfollow", "leave"):
        _set_recipient(db, kind, target, False)
        return

    if etype == "postback":
        await handle_postback(db, event, source, token)
        return

    if etype == "message" and event.get("message", {}).get("type") == "text":
        await handle_text(db, event["message"]["text"].strip(), kind, target, source, token)


async def handle_postback(db: Session, event: dict, source: dict, token: str) -> None:
    data = {k: v[0] for k, v in parse_qs(event.get("postback", {}).get("data", "")).items()}
    action, inst_id = data.get("a"), data.get("i", "")
    if action not in ("done", "undo") or not inst_id.isdigit():
        return
    by = await _member_name(db, source)
    inst = service.set_done(db, int(inst_id), action == "done", by)
    if inst is None:
        await line_api.reply(token, [messages.text_message("そのタスクは見つかりませんでした 🙏")])
        return
    board = service.get_board(db)
    if action == "done":
        msg = messages.done_message(inst, board, by)
    else:
        msg = messages.text_message(
            f"↩️「{inst.task.title}」を未完了に戻しました。\n今日の残り {len(board.remaining)}件",
            [messages.qr_message("残りを見る", "残り")],
        )
    await line_api.reply(token, [msg])


async def handle_text(db: Session, text: str, kind: str, target: str, source: dict, token: str) -> None:
    if text in ("今日", "きょう", "タスク", "一覧", "家事"):
        reply = [messages.board_message(service.get_board(db))]
    elif text in ("残り", "のこり", "未完了"):
        board = service.get_board(db)
        if board.remaining:
            reply = [messages.board_message(board, heading="⏳ 残りの家事", remaining_only=True)]
        else:
            reply = [messages.text_message("🎉 今日のタスクはすべて完了しています！")]
    elif text in ("明日", "あした"):
        reply = [messages.board_message(service.get_board(db, service.today() + timedelta(days=1)),
                                        heading="🔭 明日の家事")]
    elif text in ("リンク", "ダッシュボード", "チェックリスト"):
        reply = [messages.text_message(f"📋 チェックリスト画面はこちら\n{settings.dashboard_url}")]
    elif text == "通知オン":
        _set_recipient(db, kind, target, True)
        reply = [messages.text_message("🔔 このトークへの定期配信をオンにしました")]
    elif text == "通知オフ":
        _set_recipient(db, kind, target, False)
        reply = [messages.text_message("🔕 このトークへの定期配信をオフにしました")]
    elif text in ("ヘルプ", "help", "使い方", "?", "？"):
        reply = [messages.text_message(messages.HELP_TEXT)]
    elif kind == "user":
        reply = [messages.text_message("「今日」「残り」「ヘルプ」などと送ってね",
                                       [messages.qr_message("今日", "今日"), messages.qr_message("残り", "残り"),
                                        messages.qr_message("ヘルプ", "ヘルプ")])]
    else:
        return  # グループでは関係ない会話に反応しない
    await _member_name(db, source)  # 表示名をキャッシュしておく
    await line_api.reply(token, reply)


# =====================================================================
# 定期配信（GitHub Actions / cron-job.org などの外部スケジューラから叩く）
# =====================================================================
def require_cron_secret(x_cron_secret: str = Header(default="")) -> None:
    if not settings.cron_secret or not hmac.compare_digest(x_cron_secret, settings.cron_secret):
        raise HTTPException(status_code=401, detail="invalid cron secret")


def _claim_delivery(db: Session, kind: str, d: date, force: bool) -> bool:
    """その日のその種類の配信がまだなら記録して True。再試行による二重送信を防ぐ。"""
    log_row = db.scalar(select(DeliveryLog).where(DeliveryLog.kind == kind, DeliveryLog.target_date == d))
    if log_row and not force:
        return False
    if log_row is None:
        db.add(DeliveryLog(kind=kind, target_date=d, sent_at=datetime.now(settings.tz)))
        db.commit()
    return True


async def _broadcast(db: Session, message: dict) -> int:
    sent = 0
    for rec in db.scalars(select(Recipient).where(Recipient.active.is_(True))):
        try:
            await line_api.push(rec.target_id, [message])
            sent += 1
        except Exception:
            log.exception("push に失敗: %s", rec.target_id)
    return sent


@app.post("/cron/morning", dependencies=[Depends(require_cron_secret)])
async def cron_morning(target_date: date | None = None, force: bool = False, db: Session = Depends(get_db)):
    """朝の配信: 毎日 + その日が該当日の週次・月次タスクをまとめて送る。"""
    board = service.get_board(db, target_date)
    if not _claim_delivery(db, "morning", board.date, force):
        return {"sent": 0, "reason": "already sent"}
    heading = "☀️ おはよう！今日の家事"
    if any(i.task.frequency == "monthly" for i in board.today):
        heading = "☀️ 今日は月イチ家事の日！"
    elif any(i.task.frequency == "weekly" and i.task.carry_over for i in board.today):
        heading = "☀️ 今日は週イチ家事の日！"
    sent = await _broadcast(db, messages.board_message(board, heading=heading))
    return {"sent": sent, "date": board.date.isoformat(), "tasks": board.total}


@app.post("/cron/evening", dependencies=[Depends(require_cron_secret)])
async def cron_evening(target_date: date | None = None, force: bool = False, db: Session = Depends(get_db)):
    """夜のリマインド: 残りがあるときだけ送る。"""
    board = service.get_board(db, target_date)
    if not board.remaining:
        return {"sent": 0, "reason": "all done"}
    if not _claim_delivery(db, "evening", board.date, force):
        return {"sent": 0, "reason": "already sent"}
    sent = await _broadcast(db, messages.board_message(board, heading="🌙 今日の残り家事", remaining_only=True))
    return {"sent": sent, "remaining": len(board.remaining)}


# =====================================================================
# ダッシュボード（LIFF / ブラウザ）
# =====================================================================
async def current_actor(
    authorization: str = Header(default=""),
    x_dashboard_key: str = Header(default=""),
    x_actor_name: str = Header(default=""),
) -> str:
    """API 呼び出し元を認証し、表示名を返す。"""
    x_actor_name = unquote(x_actor_name).strip()  # 日本語名はクライアントで URL エンコードして送る
    if authorization.startswith("Bearer ") and settings.line_login_channel_id:
        claims = await line_api.verify_id_token(authorization.removeprefix("Bearer "))
        if not claims:
            raise HTTPException(status_code=401, detail="invalid id token")
        if settings.allowed_user_ids and claims.get("sub") not in settings.allowed_user_ids:
            raise HTTPException(status_code=403, detail="not allowed")
        return claims.get("name") or "LINEユーザー"
    if settings.dashboard_key:
        if not hmac.compare_digest(x_dashboard_key, settings.dashboard_key):
            raise HTTPException(status_code=401, detail="invalid dashboard key")
        return x_actor_name[:50] or "ブラウザ"
    if settings.line_login_channel_id:
        raise HTTPException(status_code=401, detail="login required")
    return x_actor_name[:50] or "ゲスト"  # 認証未設定（ローカル開発用）


@app.get("/dashboard", response_class=HTMLResponse)
def dashboard():
    html = (STATIC_DIR / "index.html").read_text(encoding="utf-8")
    return html.replace("__LIFF_ID__", settings.liff_id)


@app.get("/api/board")
def api_board(target_date: date | None = None, db: Session = Depends(get_db), _: str = Depends(current_actor)):
    return service.serialize_board(service.get_board(db, target_date))


class DoneBody(BaseModel):
    done: bool


@app.post("/api/instances/{instance_id}")
def api_set_done(instance_id: int, body: DoneBody, db: Session = Depends(get_db),
                 actor: str = Depends(current_actor)):
    inst = service.set_done(db, instance_id, body.done, actor)
    if inst is None:
        raise HTTPException(status_code=404, detail="not found")
    return service.serialize_instance(inst)


@app.get("/api/tasks")
def api_tasks(db: Session = Depends(get_db), _: str = Depends(current_actor)):
    tasks = db.scalars(select(Task).order_by(Task.sort_order)).all()
    return {
        "categories": CATEGORIES,
        "tasks": [
            {"id": t.id, "title": t.title, "category": t.category, "frequency": t.frequency,
             "schedule": describe(t), "minutes": t.minutes, "note": t.note, "active": t.active}
            for t in tasks
        ],
    }
