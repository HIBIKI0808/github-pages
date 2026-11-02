"""初期タスクデータ（キッチン / お風呂・水回り / リビング / 玄関 / 名もなき家事）。

ここを編集すれば自分たちの暮らしに合わせたリストにできる。
- key は一意な ID。DB に既にある key は上書きしない（アプリ側の変更を保持するため）。
- 曜日は 0=月, 1=火, 2=水, 3=木, 4=金, 5=土, 6=日。
- monthly は day=日付 か nth=(第N週, 曜日) のどちらかを指定。months で実施月を絞れる（季節タスク）。
"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from .database import Task

MON, TUE, WED, THU, FRI, SAT, SUN = range(7)

CATEGORIES: dict[str, dict[str, str]] = {
    "kitchen": {"label": "キッチン", "emoji": "🍳"},
    "bath": {"label": "お風呂・水回り", "emoji": "🛁"},
    "living": {"label": "リビング・寝室", "emoji": "🛋️"},
    "entrance": {"label": "玄関・ベランダ", "emoji": "🚪"},
    "nameless": {"label": "名もなき家事", "emoji": "🧺"},
}

# 週次タスクのデフォルト曜日 / 月次タスクのデフォルト日付
WEEKLY_DEFAULT = [SUN]
MONTHLY_DEFAULT_DAY = 1


def D(key, category, title, minutes=5, note="", carry_over=False):
    """毎日のタスク（デフォルトでは翌日へ持ち越さない）。"""
    return dict(key=key, category=category, title=title, frequency="daily",
                minutes=minutes, note=note, carry_over=carry_over)


def W(key, category, title, minutes=10, note="", weekdays=None, carry_over=True):
    """週次タスク。weekdays 未指定なら WEEKLY_DEFAULT（日曜）。"""
    return dict(key=key, category=category, title=title, frequency="weekly",
                weekdays=list(weekdays or WEEKLY_DEFAULT), minutes=minutes, note=note,
                carry_over=carry_over)


def M(key, category, title, minutes=20, note="", day=None, nth=None, months=None, carry_over=True):
    """月次・季節タスク。day も nth も未指定なら毎月 MONTHLY_DEFAULT_DAY 日。"""
    nth_week, weekday = nth if nth else (None, None)
    if day is None and nth is None:
        day = MONTHLY_DEFAULT_DAY
    return dict(key=key, category=category, title=title, frequency="monthly",
                day_of_month=day, nth_week=nth_week, weekday=weekday,
                months=list(months) if months else None, minutes=minutes, note=note,
                carry_over=carry_over)


INITIAL_TASKS: list[dict] = [
    # ================= 毎日 =================
    # --- キッチン ---
    D("k_dishes", "kitchen", "食器を洗う（or 食洗機をセット＆片付け）", 15),
    D("k_sink_dry", "kitchen", "シンクと蛇口の水気を拭き上げる", 2, "水垢予防。マイクロファイバーで一拭き"),
    D("k_drain_trash", "kitchen", "排水口のゴミ受けのゴミを捨てる", 2),
    D("k_stove_wipe", "kitchen", "コンロ周り・壁の油はねを拭く", 3, "温かいうちならアルコールで一発"),
    D("k_counter", "kitchen", "調理台・ダイニングテーブルを拭く", 3),
    D("k_sponge", "kitchen", "スポンジ・布巾を除菌して干す", 2, "熱湯 or 酸素系漂白剤"),
    D("k_garbage_bag", "kitchen", "生ゴミをまとめて口を縛る", 2),
    D("k_rice", "kitchen", "お米を研いで炊飯予約", 5),
    # --- お風呂・水回り ---
    D("b_tub", "bath", "浴槽を洗う", 5),
    D("b_squeegee", "bath", "入浴後に壁・床・鏡の水気をスクイージーで切る", 3, "カビ・水垢予防の最強習慣"),
    D("b_hair", "bath", "浴室の排水口の髪の毛を取る", 1),
    D("b_vent", "bath", "浴室の換気扇を回しっぱなしにする", 1),
    D("b_basin", "bath", "洗面ボウルと蛇口を拭く", 2),
    D("b_mirror", "bath", "洗面所の鏡の水はね・歯磨き粉を拭く", 1),
    D("b_toilet_bowl", "bath", "トイレの便器内をブラシでさっと掃除", 2),
    D("b_toilet_seat", "bath", "便座・便座裏・床をシートで拭く", 2),
    D("b_towel", "bath", "バスマット・フェイスタオルを交換／干す", 2),
    # --- リビング・寝室 ---
    D("l_reset", "living", "出しっぱなしの物を定位置に戻す（リセット）", 5),
    D("l_table", "living", "ローテーブル・カウンターの上を片付けて拭く", 3),
    D("l_floor", "living", "ロボット掃除機 or フロアワイパーをかける", 5),
    D("l_air", "living", "窓を開けて換気（5〜10分）", 1),
    D("l_cushion", "living", "クッション・ブランケットを整える", 1),
    D("l_bed", "living", "ベッドメイク（布団を整える）", 2),
    # --- 玄関 ---
    D("e_shoes", "entrance", "脱ぎっぱなしの靴を揃える／しまう", 1),
    D("e_mail", "entrance", "郵便物チェック・チラシ即処分", 2),
    # --- 名もなき家事 ---
    D("n_laundry_wash", "nameless", "洗濯機を回す", 2),
    D("n_laundry_dry", "nameless", "洗濯物を干す（or 乾燥機）", 10),
    D("n_laundry_fold", "nameless", "洗濯物を取り込んでたたんでしまう", 10),
    D("n_trash_collect", "nameless", "家中のゴミ箱のゴミをまとめる", 3),
    D("n_tissue", "nameless", "トイレットペーパー・ティッシュの残量チェック＆補充", 1),
    D("n_refill", "nameless", "なくなりかけの洗剤・シャンプーを詰め替える", 2),
    D("n_dishes_put", "nameless", "水切りカゴの食器を棚に戻す", 3),
    D("n_tomorrow", "nameless", "明日の予定・ゴミの日を確認", 1),

    # ================= 週1回（デフォルト日曜） =================
    # --- キッチン ---
    W("k_fridge_check", "kitchen", "冷蔵庫の中身チェック・期限切れ処分", 10, "買い出し前にやると無駄買いが減る"),
    W("k_microwave", "kitchen", "電子レンジの庫内を拭く", 5, "水を入れた耐熱容器を2分チンしてから拭く"),
    W("k_gotoku", "kitchen", "コンロの五徳・受け皿を洗う", 15),
    W("k_sink_scrub", "kitchen", "シンク全体をクレンザーで磨く", 10),
    W("k_drain_bleach", "kitchen", "排水口パーツ・三角コーナーを漂白", 5),
    W("k_fridge_door", "kitchen", "冷蔵庫・家電の扉と取っ手を拭く", 5),
    W("k_trashcan", "kitchen", "キッチンのゴミ箱本体を拭く", 5),
    W("k_towels", "kitchen", "キッチンマット・タオルを洗濯", 2),
    # --- お風呂・水回り ---
    W("b_floor_brush", "bath", "浴室の床・壁・ドアのパッキンをブラシ洗い", 15),
    W("b_drain_parts", "bath", "浴室排水口のパーツを分解して洗う", 10),
    W("b_bottles", "bath", "シャンプーボトル・ラックの底のヌメリ取り", 5),
    W("b_basin_drain", "bath", "洗面台の排水口・オーバーフロー穴を掃除", 5),
    W("b_toilet_full", "bath", "トイレの床・壁・タンク周りを全面拭き", 10),
    W("b_toilet_mat", "bath", "トイレマット・タオル・スリッパを洗濯", 2),
    W("b_lint", "bath", "洗濯機のゴミ取りネット・糸くずフィルター掃除", 3),
    # --- リビング・寝室 ---
    W("l_vacuum", "living", "家全体に掃除機（家具の下・部屋の隅まで）", 20),
    W("l_dust", "living", "棚・テレビ・照明・窓枠のホコリ取り", 10, "上から下へ"),
    W("l_switch", "living", "リモコン・スイッチ・ドアノブを除菌", 5),
    W("l_plants", "living", "観葉植物の水やり・葉のホコリ拭き", 5),
    W("l_sheets", "living", "シーツ・枕カバーを交換して洗濯", 15),
    # --- 玄関・ベランダ ---
    W("e_tataki", "entrance", "玄関のたたきを掃く・水拭き", 5),
    W("e_shoebox_air", "entrance", "靴箱の扉を開けて換気", 1),
    W("e_mat", "entrance", "玄関マットをはたく", 2),
    # --- 名もなき家事 ---
    W("n_stock", "nameless", "日用品の在庫チェック・買い物リスト作成", 10),
    W("n_menu", "nameless", "1週間の献立をざっくり決める／作り置き", 30),
    W("n_paper", "nameless", "書類・レシートを整理", 10),
    # ゴミ出し（※自治体の収集日に合わせて曜日を変更してください）
    W("n_trash_burn", "nameless", "🔥 燃えるゴミを出す", 3, "自治体の収集日に合わせて曜日を変更", weekdays=[MON, THU], carry_over=False),
    W("n_trash_plastic", "nameless", "♻️ プラスチックゴミを出す", 3, weekdays=[WED], carry_over=False),
    W("n_trash_recycle", "nameless", "🥫 缶・ビン・ペットボトルを出す", 3, weekdays=[FRI], carry_over=False),

    # ================= 月1回・季節 =================
    # --- キッチン ---
    M("k_fan_filter", "kitchen", "換気扇（レンジフード）のフィルター交換・洗浄", 30, day=1),
    M("k_fridge_shelf", "kitchen", "冷蔵庫の棚を全部出して拭く", 30, nth=(2, SAT)),
    M("k_dishwasher", "kitchen", "食洗機のフィルター・庫内を洗浄", 15, day=1),
    M("k_kettle", "kitchen", "電気ケトル・ポットをクエン酸洗浄", 5, day=15),
    M("k_cutting_board", "kitchen", "まな板・保存容器・水筒を漂白", 10, day=15),
    M("k_rice_cooker", "kitchen", "炊飯器の内蓋・蒸気口を掃除", 10, day=15),
    M("k_water_filter", "kitchen", "浄水器カートリッジの交換時期を確認", 2, day=1, months=[1, 4, 7, 10]),
    # --- お風呂・水回り ---
    M("b_mirror_scale", "bath", "浴室の鏡のウロコ（水垢）取り", 15, "クエン酸パック", nth=(1, SUN)),
    M("b_ceiling", "bath", "浴室の天井・換気扇カバーを拭く", 15, "天井はフロアワイパー＋アルコール", nth=(1, SUN)),
    M("b_washer_tub", "bath", "洗濯槽クリーナーで洗濯槽を掃除", 10, day=1),
    M("b_mold_smoke", "bath", "浴室の防カビくん煙剤を焚く", 5, day=1, months=[1, 3, 5, 7, 9, 11]),
    M("b_toilet_tank", "bath", "トイレの尿石取り・タンク内・換気扇掃除", 20, nth=(3, SUN)),
    M("b_basin_storage", "bath", "洗面所の収納を整理・期限切れコスメ処分", 15, nth=(3, SUN)),
    M("b_pipe", "bath", "排水管にパイプクリーナーを流す", 5, day=15),
    # --- リビング・寝室 ---
    M("l_aircon", "living", "エアコンのフィルター掃除", 20, day=15),
    M("l_light", "living", "照明カバー・シーリングライトのホコリ取り", 10, nth=(2, SUN)),
    M("l_baseboard", "living", "巾木・ドアの上・家具の裏のホコリ取り", 15, nth=(2, SUN)),
    M("l_futon", "living", "布団を干す／布団乾燥機をかける", 10, nth=(1, SAT)),
    M("l_window", "living", "窓ガラス・網戸・サッシのレールを掃除", 40, nth=(4, SAT), months=[3, 6, 9, 12]),
    M("l_curtain", "living", "カーテンを洗濯", 30, nth=(4, SAT), months=[4, 10]),
    # --- 玄関・ベランダ ---
    M("e_door", "entrance", "玄関ドア・ドアノブ・インターホンを拭く", 10, nth=(1, SAT)),
    M("e_shoebox", "entrance", "靴箱の中を出して拭く・履かない靴を処分", 20, nth=(1, SAT), months=[3, 6, 9, 12]),
    M("e_shoe_care", "entrance", "靴の手入れ（汚れ落とし・防水スプレー）", 15, nth=(1, SAT)),
    M("e_balcony", "entrance", "ベランダの掃き掃除・排水溝の詰まりチェック", 15, nth=(-1, SUN)),
    # --- 名もなき家事・季節 ---
    M("n_bills", "nameless", "公共料金・サブスク・家計の確認", 15, day=25),
    M("n_dryer_filter", "nameless", "乾燥機・除湿機・空気清浄機のフィルター掃除", 10, day=15),
    M("n_emergency", "nameless", "防災グッズ・非常食・水の期限チェック", 15, day=1, months=[3, 9]),
    M("n_smoke_alarm", "nameless", "火災報知器のテスト・電池チェック", 5, day=1, months=[1, 7]),
    M("n_koromogae_summer", "nameless", "衣替え（春夏物を出す）・扇風機を出す", 60, nth=(2, SAT), months=[5]),
    M("n_koromogae_winter", "nameless", "衣替え（秋冬物を出す）・暖房器具を出す", 60, nth=(2, SAT), months=[10]),
    M("n_humidifier", "nameless", "加湿器のタンク・フィルターをクエン酸洗浄", 15, day=15, months=[11, 12, 1, 2, 3]),
    M("n_aircon_pro", "nameless", "エアコン試運転・本格シーズン前点検", 15, day=1, months=[5, 11]),
    M("n_osouji", "nameless", "大掃除の分担を決める", 15, day=1, months=[12]),
]


def seed_tasks(db: Session) -> int:
    """未登録の初期タスクを追加する。追加件数を返す。"""
    existing = set(db.scalars(select(Task.key)))
    added = 0
    for order, data in enumerate(INITIAL_TASKS):
        if data["key"] in existing:
            continue
        db.add(Task(sort_order=order, **data))
        added += 1
    db.commit()
    return added
