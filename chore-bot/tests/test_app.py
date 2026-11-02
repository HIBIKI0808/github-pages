import base64
import hashlib
import hmac
import json
from datetime import date, timedelta

from fastapi.testclient import TestClient

from app import messages, service
from app.database import Recipient, Task
from app.main import app
from app.seed_tasks import INITIAL_TASKS

client = TestClient(app)
KEY = {"X-Dashboard-Key": "dash-key"}
SUNDAY = date(2026, 11, 1)   # 第1日曜 & 1日
MONDAY = date(2026, 11, 2)


def sign(body: bytes) -> str:
    return base64.b64encode(hmac.new(b"test-secret", body, hashlib.sha256).digest()).decode()


def test_seed_is_comprehensive_and_idempotent(db):
    from app.seed_tasks import seed_tasks
    assert db.query(Task).count() == len(INITIAL_TASKS)
    assert seed_tasks(db) == 0
    assert len({t["key"] for t in INITIAL_TASKS}) == len(INITIAL_TASKS)
    cats = {t["category"] for t in INITIAL_TASKS}
    assert cats == {"kitchen", "bath", "living", "entrance", "nameless"}


def test_board_includes_daily_weekly_monthly(db):
    board = service.get_board(db, SUNDAY)
    freqs = {i.task.frequency for i in board.today}
    assert freqs == {"daily", "weekly", "monthly"}
    monday = service.get_board(db, MONDAY)
    assert "n_trash_burn" in {i.task.key for i in monday.today}


def test_carry_over_and_done(db):
    sunday = service.get_board(db, SUNDAY)
    weekly = next(i for i in sunday.today if i.task.frequency == "weekly" and i.task.carry_over)
    daily = next(i for i in sunday.today if i.task.frequency == "daily")
    monday = service.get_board(db, MONDAY)
    carried = {i.id for i in monday.carry_over}
    assert weekly.id in carried and daily.id not in carried
    service.set_done(db, weekly.id, True, "たろう")
    assert weekly.id not in {i.id for i in service.get_board(db, MONDAY).carry_over}
    # 1週間後はまた新しいインスタンスが発生し、古いものは持ち越されない
    later = service.get_board(db, SUNDAY + timedelta(days=7))
    assert all(i.due_date >= SUNDAY + timedelta(days=1) or i.task.frequency == "monthly" for i in later.carry_over)


def test_flex_message_within_limits(db):
    for offset in range(35):
        board = service.get_board(db, SUNDAY + timedelta(days=offset))
        msg = messages.board_message(board)
        assert len(json.dumps(msg, ensure_ascii=False).encode()) <= messages.MAX_JSON_BYTES
        if msg["type"] == "flex":
            assert len(msg["contents"]["contents"]) <= 12


def test_dashboard_api_requires_key():
    assert client.get("/api/board").status_code == 401
    res = client.get(f"/api/board?target_date={SUNDAY}", headers=KEY)
    assert res.status_code == 200
    data = res.json()
    assert data["total"] == len(data["today"]) + len(data["carry_over"]) > 0
    first = data["today"][0]
    res = client.post(f"/api/instances/{first['id']}", json={"done": True},
                      headers={**KEY, "X-Actor-Name": "%E3%81%9F%E3%82%8D%E3%81%86"})
    assert res.json()["done"] is True and res.json()["done_by"] == "たろう"
    assert client.get(f"/api/board?target_date={SUNDAY}", headers=KEY).json()["done"] == 1


def test_dashboard_html():
    res = client.get("/dashboard")
    assert res.status_code == 200 and "__LIFF_ID__" not in res.text


def test_webhook_signature_and_postback(db):
    body = json.dumps({"events": []}).encode()
    assert client.post("/callback", content=body, headers={"X-Line-Signature": "bad"}).status_code == 400
    assert client.post("/callback", content=body, headers={"X-Line-Signature": sign(body)}).status_code == 200

    inst = service.get_board(db).today[0]
    events = {"events": [
        {"type": "follow", "replyToken": "t", "source": {"type": "user", "userId": "U1"}},
        {"type": "postback", "replyToken": "t", "source": {"type": "user", "userId": "U1"},
         "postback": {"data": f"a=done&i={inst.id}"}},
        {"type": "message", "replyToken": "t", "source": {"type": "user", "userId": "U1"},
         "message": {"type": "text", "text": "残り"}},
    ]}
    body = json.dumps(events).encode()
    assert client.post("/callback", content=body, headers={"X-Line-Signature": sign(body)}).status_code == 200
    db.expire_all()
    assert db.get(type(inst), inst.id).done is True
    assert db.query(Recipient).filter_by(target_id="U1", active=True).count() == 1


def test_cron_requires_secret():
    assert client.post("/cron/morning").status_code == 401
    res = client.post(f"/cron/morning?target_date={SUNDAY}", headers={"X-Cron-Secret": "cron-secret"})
    assert res.status_code == 200 and res.json()["tasks"] > 0
    again = client.post(f"/cron/morning?target_date={SUNDAY}", headers={"X-Cron-Secret": "cron-secret"})
    assert again.json()["reason"] == "already sent"
