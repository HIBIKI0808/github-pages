"""LINE に送るメッセージ（Flex Message / テキスト）の組み立て。"""
from __future__ import annotations

import json
from collections import OrderedDict
from datetime import date

from .config import settings
from .database import TaskInstance
from .seed_tasks import CATEGORIES
from .service import Board

WEEKDAY_JA = "月火水木金土日"
ROWS_PER_BUBBLE = 10
MAX_BUBBLES = 12  # LINE のカルーセル上限
MAX_JSON_BYTES = 45_000  # Flex Message 全体の上限 (50KB) に余裕を持たせる

COLOR_MAIN = "#06C755"
COLOR_SUB = "#8C8C8C"
FREQ_BADGE = {"daily": ("毎日", "#9E9E9E"), "weekly": ("週", "#1E88E5"), "monthly": ("月", "#E53935")}


def fmt_date(d: date) -> str:
    return f"{d.month}/{d.day}({WEEKDAY_JA[d.weekday()]})"


def _task_row(inst: TaskInstance) -> dict:
    t = inst.task
    badge, badge_color = FREQ_BADGE.get(t.frequency, ("", COLOR_SUB))
    title = {
        "type": "text",
        "text": ("✅ " if inst.done else "⬜ ") + t.title,
        "size": "sm",
        "wrap": True,
        "flex": 5,
        "color": COLOR_SUB if inst.done else "#111111",
    }
    if inst.done:
        title["decoration"] = "line-through"
    row = {
        "type": "box",
        "layout": "horizontal",
        "spacing": "sm",
        "paddingTop": "6px",
        "paddingBottom": "6px",
        "contents": [
            title,
            {"type": "text", "text": f"{badge}·{t.minutes}分", "size": "xxs",
             "color": badge_color, "flex": 0, "gravity": "center"},
        ],
    }
    if not inst.done:
        # 行をタップすると完了（postback はトークに何も表示されない）
        row["action"] = {"type": "postback", "label": "完了", "data": f"a=done&i={inst.id}"}
    return row


def _category_bubbles(instances: list[TaskInstance], title_prefix: str = "") -> list[dict]:
    groups: OrderedDict[str, list[TaskInstance]] = OrderedDict((k, []) for k in CATEGORIES)
    for inst in instances:
        groups.setdefault(inst.task.category, []).append(inst)
    bubbles = []
    for cat, items in groups.items():
        if not items:
            continue
        meta = CATEGORIES.get(cat, {"label": cat, "emoji": "📌"})
        chunks = [items[i:i + ROWS_PER_BUBBLE] for i in range(0, len(items), ROWS_PER_BUBBLE)]
        for n, chunk in enumerate(chunks, 1):
            remaining = sum(1 for i in items if not i.done)
            suffix = f" ({n}/{len(chunks)})" if len(chunks) > 1 else ""
            bubbles.append({
                "type": "bubble",
                "size": "mega",
                "header": {
                    "type": "box", "layout": "vertical", "backgroundColor": "#F4F8F5",
                    "contents": [
                        {"type": "text", "text": f"{title_prefix}{meta['emoji']} {meta['label']}{suffix}",
                         "weight": "bold", "size": "md"},
                        {"type": "text", "text": f"残り {remaining} / {len(items)} 件　タップで完了",
                         "size": "xxs", "color": COLOR_SUB},
                    ],
                },
                "body": {"type": "box", "layout": "vertical", "spacing": "none",
                         "contents": [_task_row(i) for i in chunk]},
            })
    return bubbles


def _summary_bubble(board: Board, heading: str) -> dict:
    total, done = board.total, board.done_count
    pct = int(done * 100 / total) if total else 100
    counts = {f: sum(1 for i in board.today if i.task.frequency == f) for f in ("daily", "weekly", "monthly")}
    highlights = []
    if counts["weekly"]:
        highlights.append(f"📅 週次タスク {counts['weekly']}件")
    if counts["monthly"]:
        highlights.append(f"🗓️ 月次・季節タスク {counts['monthly']}件")
    if board.carry_over:
        highlights.append(f"⏳ 持ち越し {len(board.carry_over)}件")
    contents = [
        {"type": "text", "text": heading, "weight": "bold", "size": "lg", "wrap": True},
        {"type": "text", "text": fmt_date(board.date), "size": "sm", "color": COLOR_SUB},
        {"type": "separator", "margin": "md"},
        {"type": "text", "margin": "md", "size": "xl", "weight": "bold", "color": COLOR_MAIN,
         "text": f"残り {len(board.remaining)}件"},
        {"type": "text", "size": "xs", "color": COLOR_SUB,
         "text": f"完了 {done}/{total}件・残り約{board.remaining_minutes}分"},
        {   # プログレスバー
            "type": "box", "layout": "vertical", "margin": "md", "height": "8px",
            "backgroundColor": "#E6E6E6", "cornerRadius": "4px",
            "contents": [{"type": "box", "layout": "vertical", "contents": [],
                          "width": f"{max(pct, 1)}%", "height": "8px",
                          "backgroundColor": COLOR_MAIN, "cornerRadius": "4px"}],
        },
    ]
    for h in highlights:
        contents.append({"type": "text", "text": h, "size": "sm", "margin": "sm"})
    return {
        "type": "bubble",
        "size": "mega",
        "body": {"type": "box", "layout": "vertical", "contents": contents},
        "footer": {
            "type": "box", "layout": "vertical", "spacing": "sm",
            "contents": [
                {"type": "button", "style": "primary", "color": COLOR_MAIN, "height": "sm",
                 "action": {"type": "uri", "label": "チェックリストを開く", "uri": settings.dashboard_url}},
                {"type": "button", "style": "secondary", "height": "sm",
                 "action": {"type": "message", "label": "残りだけ表示", "text": "残り"}},
            ],
        },
    }


def board_message(board: Board, heading: str = "🏠 今日の家事", remaining_only: bool = False) -> dict:
    """今日のボードを Flex カルーセルで返す（右スワイプでカテゴリ別リスト）。"""
    alt = f"{heading} {fmt_date(board.date)} 残り{len(board.remaining)}件"
    if board.total == 0:
        return text_message(f"{heading} {fmt_date(board.date)}\n今日のタスクはありません 🎉")

    def build(include_done: bool) -> dict:
        today = [i for i in board.today if include_done or not i.done]
        carry = [i for i in board.carry_over if include_done or not i.done]
        bubbles = [_summary_bubble(board, heading)]
        bubbles += _category_bubbles(today)
        if carry:
            bubbles += _category_bubbles(carry, title_prefix="⏳持ち越し ")
        if len(bubbles) > MAX_BUBBLES:
            bubbles = bubbles[:MAX_BUBBLES]
        return {"type": "flex", "altText": alt, "contents": {"type": "carousel", "contents": bubbles}}

    msg = build(include_done=not remaining_only)
    if _size(msg) > MAX_JSON_BYTES and not remaining_only:
        msg = build(include_done=False)
    while _size(msg) > MAX_JSON_BYTES and len(msg["contents"]["contents"]) > 1:
        msg["contents"]["contents"].pop()
    if not board.remaining:
        msg["altText"] = f"{heading} すべて完了！"
    return msg


def _size(msg: dict) -> int:
    return len(json.dumps(msg, ensure_ascii=False).encode())


def text_message(text: str, quick_replies: list[dict] | None = None) -> dict:
    msg: dict = {"type": "text", "text": text[:5000]}
    if quick_replies:
        msg["quickReply"] = {"items": quick_replies[:13]}
    return msg


def qr_message(label: str, text: str) -> dict:
    return {"type": "action", "action": {"type": "message", "label": label[:20], "text": text}}


def qr_postback(label: str, data: str) -> dict:
    return {"type": "action", "action": {"type": "postback", "label": label[:20], "data": data}}


def done_message(inst: TaskInstance, board: Board, by: str | None) -> dict:
    who = f"（{by}）" if by else ""
    if board.remaining:
        text = (f"✅「{inst.task.title}」完了！{who}\n"
                f"今日の残り {len(board.remaining)}件・約{board.remaining_minutes}分")
    else:
        text = f"✅「{inst.task.title}」完了！{who}\n🎉 今日のタスクはすべて完了！おつかれさま！"
    return text_message(text, [
        qr_message("残りを見る", "残り"),
        qr_postback("取り消す", f"a=undo&i={inst.id}"),
    ])


HELP_TEXT = """🧹 家事ボットの使い方

・「今日」… 今日のタスク一覧
・「残り」… 未完了のタスクだけ表示
・「明日」… 明日のタスクを確認
・「リンク」… チェックリスト画面のURL
・「通知オン」/「通知オフ」… このトークへの定期配信の切り替え
・「ヘルプ」… この説明

一覧のタスクをタップすると完了になります ✅
間違えたときは返信の「取り消す」を押してください。"""
