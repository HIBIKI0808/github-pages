"""初期タスクデータ（カテゴリ → 頻度 → タスク の階層構造）。

このファイルが「タスクの正」です。編集してアプリを再起動（再デプロイ）すると DB に同期されます。
- key は一意な ID（タイトルを変えても key が同じなら完了履歴は引き継がれる）。
- ここから消したタスクは DB 上で active=False（停止）になる。
- 曜日は 0=月, 1=火, 2=水, 3=木, 4=金, 5=土, 6=日。

スケジュールの指定方法:
- 毎日 (daily)     … 指定不要
- 週1〜2回 (weekly) … weekdays=[...] で曜日指定。省略時は WEEKLY_DEFAULT（日曜）
- 月1〜数ヶ月 (monthly) … day=日付 または nth=(第N週, 曜日)（-1 は最終週）。
                         months=[...] を付けると、その月だけ実施（2〜3ヶ月に1回のタスク用）
"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from .database import Task

MON, TUE, WED, THU, FRI, SAT, SUN = range(7)

# 週次タスクのデフォルト曜日 / 「週2回」タスクの曜日 / 月次タスクのデフォルト日付
WEEKLY_DEFAULT = [SUN]
TWICE_A_WEEK = [WED, SUN]
MONTHLY_DEFAULT_DAY = 1

EVERY_2_MONTHS = [1, 3, 5, 7, 9, 11]
EVERY_3_MONTHS = [3, 6, 9, 12]


def T(key: str, title: str, minutes: int = 5, note: str = "", **schedule) -> dict:
    """タスク 1 件。schedule には weekdays / day / nth / months / carry_over を指定できる。"""
    return dict(key=key, title=title, minutes=minutes, note=note, **schedule)


# =====================================================================
# 【初期タスクリスト】カテゴリ → 頻度（daily / weekly / monthly）→ タスク
# =====================================================================
TASK_TREE: dict[str, dict] = {
    # -----------------------------------------------------------------
    "kitchen": {
        "label": "キッチン",
        "subtitle": "水回り・家電の細部",
        "emoji": "🍳",
        "daily": [
            T("k_drain_trash", "排水口のゴミ受けのゴミ捨て＆簡単なスポンジ洗い", 3),
            T("k_sink_wipe", "シンク全体の水分拭き取り（水垢・ピンク汚れ防止）", 2),
            T("k_stove_wipe", "IH天板（またはガス台）の油跳ねの拭き掃除", 3, "温かいうちに拭くと落ちやすい"),
            T("k_dishwasher_filter", "食洗機のフィルターのゴミ取り", 2),
            T("k_microwave_check", "電子レンジの庫内の飛び散りチェック＆拭き掃除", 2),
        ],
        "weekly": [
            T("k_grill", "魚焼きグリル（受け皿・網）の分解洗浄", 15),
            T("k_gotoku", "五徳やバーナーキャップのつけ置き・焦げ落とし", 20, "重曹＋お湯でつけ置き"),
            T("k_fridge_handle", "冷蔵庫のポケット・ドアの取っ手・パッチンの手垢拭き", 5),
            T("k_toaster_tray", "トースターのパンくずトレーの掃除", 3),
            T("k_board_sponge", "まな板・スポンジの除菌・漂白", 5, "酸素系漂白剤 or 熱湯", weekdays=TWICE_A_WEEK),
            T("k_floor", "キッチンの床（足元）の油跳ね・ホコリの拭き掃除", 10),
        ],
        "monthly": [
            T("k_range_hood", "レンジフード・換気扇のフィルター交換（またはファン・本体掃除）", 30, day=1),
            T("k_fridge_inspect", "冷蔵庫の中身の総点検・賞味期限切れ廃棄＆棚板拭き掃除", 30, day=10),
            T("k_dishwasher_clean", "食洗機自体の庫内洗浄", 10, "食洗機用クリーナーを入れて空運転", day=1),
            T("k_rice_cooker", "炊飯器の蒸気口・内蓋の丸洗い", 10, day=20),
            T("k_knife", "包丁やキッチンバサミの研ぎ・点検", 15, day=20, months=EVERY_3_MONTHS),
        ],
    },
    # -----------------------------------------------------------------
    "bath": {
        "label": "お風呂・洗面所・トイレ",
        "subtitle": "水回りの細かいメンテ",
        "emoji": "🛁",
        "daily": [
            T("b_floor_squeegee", "お風呂の床の水切り（スクイージーや換気）", 3, "カビ予防の最強習慣"),
            T("b_basin_hair", "洗面ボウルの髪の毛取り＆水滴拭き取り", 2),
            T("b_toilet_brush", "トイレの便器内のササッとブラシがけ", 2),
        ],
        "weekly": [
            T("b_bath_drain", "お風呂の排水口の髪の毛ポイ捨て＆パーツ洗浄", 10, weekdays=TWICE_A_WEEK),
            T("b_mirror_scale", "浴室の鏡の水垢・ウロコ取り", 10, "クエン酸パック→スポンジ"),
            T("b_hair_catcher", "洗面所のヘアキャッチャー（ゴミ受け）の掃除", 3),
            T("b_toothbrush_stand", "歯ブラシ立て・コップ置き場の底のぬめり取り・乾燥", 3),
            T("b_toilet_rim", "トイレの便器のフチ裏・便座裏・外側の拭き掃除", 10, weekdays=TWICE_A_WEEK),
            T("b_toilet_floor", "トイレの床・壁（下部）の尿飛び・ホコリ拭き", 5),
        ],
        "monthly": [
            T("b_reheat_pipe", "お風呂の浴槽の循環アダプター（追い焚き配管）内部洗浄", 20, "風呂釜洗浄剤を使用", day=5),
            T("b_dryer_fan", "浴室乾燥機・換気扇のフィルターのホコリ吸い取り", 10, day=5),
            T("b_mold_smoke", "お風呂の防カビ燻煙剤を焚く", 5, "2ヶ月に1回が目安", day=15, months=EVERY_2_MONTHS),
            T("b_door_packing", "お風呂のドアのパッキン・下部のカビ取り", 15, "塩素系カビ取り剤＋ラップパック", day=15),
            T("b_basin_trap", "洗面所の排水トラップの分解洗浄", 15, day=25),
            T("b_toilet_tank", "トイレのタンクの水受け・ノズルそうじ・換気扇掃除", 20, day=25),
        ],
    },
    # -----------------------------------------------------------------
    "living": {
        "label": "リビング・居室",
        "subtitle": "隠れホコリ・細部",
        "emoji": "🛋️",
        "daily": [
            T("l_cushion_reset", "クッション・ソファの形を整える（リセット）", 1),
            T("l_put_back", "テーブルの上・床に落ちているものの定位置戻し", 5),
        ],
        "weekly": [
            T("l_screen", "テレビ画面・パソコン画面のホコリ払い・手垢拭き", 5, "画面は乾拭き→専用クリーナー"),
            T("l_remote", "リモコン・スマホの除菌シート拭き", 3),
            T("l_rug_vacuum", "カーペット・ラグの念入り掃除機がけ", 15, "縦横2方向にゆっくり"),
            T("l_baseboard", "巾木（床と壁の境目）に溜まったホコリの拭き取り", 10),
        ],
        "monthly": [
            T("l_aircon_filter", "エアコンのフィルターのホコリ吸い取り＆水洗い", 20, "冷暖房シーズンは2週に1回が理想", day=15),
            T("l_aircon_louver", "エアコンのルーバー内部のカビ・ホコリ拭き", 15, day=15, months=EVERY_2_MONTHS),
            T("l_light_shade", "照明器具の傘（シェード）のホコリ拭き", 10, day=10),
            T("l_curtain_rail", "カーテンレールの上のホコリ取り", 5, day=10),
            T("l_switch", "ドアノブ・スイッチプレートのアルコール除菌拭き", 10, day=1),
            T("l_sofa_gap", "ソファの隙間のゴミ吸い取り", 5, day=20),
            T("l_window", "窓ガラス・サッシのレール掃除・水拭き", 40, nth=(2, SAT), months=EVERY_3_MONTHS),
            T("l_screen_door", "網戸のホコリ落とし・水拭き", 20, nth=(2, SAT), months=EVERY_3_MONTHS),
        ],
    },
    # -----------------------------------------------------------------
    "entrance": {
        "label": "玄関・廊下・その他",
        "subtitle": "名もなき家事",
        "emoji": "🚪",
        "daily": [],
        "weekly": [
            T("e_tataki", "玄関のたたきの砂埃掃き・水拭き", 5),
            # ゴミの日に合わせて曜日を変更してください
            T("e_trash_collect", "各部屋のゴミ箱のゴミ集め・ゴミ袋セット", 5, "ゴミの日の前日・当日朝に",
              weekdays=TWICE_A_WEEK, carry_over=False),
        ],
        "monthly": [
            T("e_shoebox", "下駄箱の靴を全部出して中の砂埃拭き＆換気", 20, nth=(1, SUN), months=EVERY_3_MONTHS),
            T("e_umbrella_stand", "傘立ての底の汚れ・水たまりの掃除", 5, day=1),
            T("e_router_dust", "分電盤やWi-Fiルーターのホコリ取り", 5, "ホコリはトラッキング火災の原因に",
              day=20, months=EVERY_2_MONTHS),
            T("e_mail_sort", "郵便物の仕分け・不要なDM処分", 10, day=25),
            # 古紙・資源ゴミの収集日に合わせて変更してください
            T("e_cardboard", "段ボール・古紙の紐縛り・まとめ・リサイクル出し", 10, "資源ゴミの収集日に合わせて変更",
              nth=(2, SUN)),
            T("e_bottle_refill", "シャンプー等のボトル底のヌメリ取り＆詰め替え", 10, day=10),
            T("e_stock_check", "トイレットペーパー・洗剤等のストック在庫確認・補充", 10, day=25),
        ],
    },
}

FREQUENCIES = ("daily", "weekly", "monthly")
FREQUENCY_LABELS = {"daily": "毎日", "weekly": "週1〜2回", "monthly": "月1〜数ヶ月"}

# 表示用のカテゴリ情報（順番は TASK_TREE の定義順）
CATEGORIES: dict[str, dict[str, str]] = {
    key: {"label": c["label"], "subtitle": c["subtitle"], "emoji": c["emoji"]}
    for key, c in TASK_TREE.items()
}


def _to_row(category: str, frequency: str, item: dict) -> dict:
    """階層データの 1 件を Task テーブルの列に変換する。"""
    row = dict(
        key=item["key"], title=item["title"], category=category, frequency=frequency,
        minutes=item.get("minutes", 5), note=item.get("note", ""),
        carry_over=item.get("carry_over", frequency != "daily"),
        weekdays=None, day_of_month=None, nth_week=None, weekday=None, months=None,
    )
    if frequency == "weekly":
        row["weekdays"] = sorted(item.get("weekdays") or WEEKLY_DEFAULT)
    elif frequency == "monthly":
        if item.get("nth"):
            row["nth_week"], row["weekday"] = item["nth"]
        else:
            row["day_of_month"] = item.get("day", MONTHLY_DEFAULT_DAY)
        row["months"] = sorted(item["months"]) if item.get("months") else None
    return row


def flatten_tasks(tree: dict[str, dict] = TASK_TREE) -> list[dict]:
    rows = []
    for category, cat in tree.items():
        for frequency in FREQUENCIES:
            for item in cat.get(frequency, []):
                rows.append(_to_row(category, frequency, item))
    return rows


INITIAL_TASKS: list[dict] = flatten_tasks()


def seed_tasks(db: Session) -> dict[str, int]:
    """TASK_TREE の内容を DB に同期する（追加・更新・停止）。"""
    existing = {t.key: t for t in db.scalars(select(Task))}
    stats = {"added": 0, "updated": 0, "deactivated": 0}
    for order, data in enumerate(INITIAL_TASKS):
        task = existing.pop(data["key"], None)
        if task is None:
            db.add(Task(sort_order=order, active=True, **data))
            stats["added"] += 1
            continue
        changed = False
        for field, value in {**data, "sort_order": order, "active": True}.items():
            if getattr(task, field) != value:
                setattr(task, field, value)
                changed = True
        stats["updated"] += changed
    for task in existing.values():  # リストから消えたタスクは停止
        if task.active:
            task.active = False
            stats["deactivated"] += 1
    db.commit()
    return stats
