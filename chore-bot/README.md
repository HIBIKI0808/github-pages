# 🧹 おうち家事ボット（LINE 連動・家事タスク管理）

同居する 2 人向けの、LINE で毎朝「今日の家事リスト」が届き、タップや Web 画面で完了チェックできるボットです。

- **毎日**：毎朝 7:00 に、その日の細かい家事リストが届く
- **週1〜2回**：指定曜日（初期値：日曜。「週2回」のタスクは水・日）に週次タスクが追加で届く
- **月1〜数ヶ月**：「毎月1日」「10日」「第2土曜」「3・6・9・12月だけ」などの指定日にメンテナンス項目が届く
- **完了チェック**：LINE のリストの行をタップ → 完了。返信で「今日の残り◯件」がわかる
- **Web チェックリスト**（LIFF / ブラウザ）：チェックボックスで完了・取り消し。誰が完了したかも記録
- **持ち越し**：週次・月次タスクは終わるまで翌日以降も「⏳持ち越し」として表示
- **夜のリマインド**：21:00 に残りがあるときだけ送信（不要なら cron を消すだけ）

## 技術スタック

| 役割 | 採用 | 理由 |
| --- | --- | --- |
| 言語 / FW | Python 3.12 + FastAPI | 型付きで軽量、Webhook と API を 1 つのアプリで |
| LINE 連携 | Messaging API（httpx で直接呼び出し） | SDK のバージョン差異に左右されない |
| DB | SQLAlchemy（ローカル: SQLite / 本番: **Supabase** の Postgres） | 無料・永続化 |
| ホスティング | **Render**（Free Web Service） | 無料で HTTPS の Webhook を公開できる |
| 定期実行 | **GitHub Actions** の schedule（または cron-job.org） | Render 無料枠はスリープするため外部から起こして配信 |

> ⚠️ Render 無料枠はディスクが永続化されず、15 分アクセスがないとスリープします。
> そのため **DB は Supabase（無料）**、**定期配信は外部 cron から `/cron/morning` を叩く**構成にしています。

## ディレクトリ構成

```
chore-bot/
├── app/
│   ├── main.py          # FastAPI 本体（/callback, /cron/*, /dashboard, /api/*）
│   ├── config.py        # 環境変数の読み込み
│   ├── database.py      # テーブル定義（Task / TaskInstance / Recipient / Member / DeliveryLog）
│   ├── seed_tasks.py    # ★初期タスクリスト（4カテゴリ×3頻度・54件）。ここを編集してカスタマイズ
│   ├── schedule.py      # 「その日にやるタスクか」の判定（毎日 / 曜日 / 日付 / 第N曜日 / 季節）
│   ├── service.py       # タスク発生・完了・持ち越し・集計
│   ├── messages.py      # LINE の Flex Message 組み立て
│   ├── line_api.py      # LINE API クライアント（署名検証・reply・push・LIFF トークン検証）
│   └── static/index.html# スマホ向けチェックリスト画面（LIFF 対応）
├── tests/               # pytest
├── requirements.txt
├── render.yaml          # Render Blueprint
└── .env.example
../.github/workflows/chore-bot-cron.yml  # 毎朝・毎晩の配信トリガー
```

### データモデル

- `Task` … タスクの定義（タイトル・カテゴリ・頻度・曜日・日付・第N週・実施月・所要分数）
- `TaskInstance` … 「11/2 の『食器を洗う』」のような日ごとの実体。`done` / `done_by` / `done_at` を持つ
- `Recipient` … 定期配信の送り先（1:1 トーク or グループ）
- `Member` … LINE ユーザー ID → 表示名キャッシュ
- `DeliveryLog` … 同じ日に二重送信しないための記録

## 使い方（LINE 上のコマンド）

| 送る言葉 | 動作 |
| --- | --- |
| `今日` | 今日のタスク一覧（カテゴリ別カルーセル。行をタップで完了） |
| `残り` | 未完了だけ表示 |
| `明日` | 明日のタスクを先に確認 |
| `リンク` | チェックリスト画面の URL |
| `通知オン` / `通知オフ` | このトークへの定期配信を切り替え |
| `ヘルプ` | 使い方 |

おすすめは **2 人＋ボットの LINE グループ** を作る運用です（配信は 1 か所に届き、どちらが完了したかが一目でわかる）。
グループで使う場合、個別トークにも届いて二重になるなら、個別トークで `通知オフ` と送ってください。

---

## セットアップ手順

### 1. LINE Developers の設定（Messaging API）

1. [LINE Developers コンソール](https://developers.line.biz/console/) に LINE アカウントでログイン
2. **プロバイダーを作成**（例：`おうち`）
3. **Messaging API チャネルを作成**
   - 2024 年以降は「LINE 公式アカウントを作成」→ [LINE Official Account Manager](https://manager.line.biz/) で公式アカウントを作り、
     「設定 → Messaging API → Messaging API を利用する」でプロバイダーを選ぶと、コンソールにチャネルができます
4. チャネルの **「チャネル基本設定」タブ** → `チャネルシークレット` をコピー → 環境変数 `LINE_CHANNEL_SECRET`
5. **「Messaging API 設定」タブ**
   - 一番下の `チャネルアクセストークン（長期）` を「発行」→ `LINE_CHANNEL_ACCESS_TOKEN`
   - `Webhook URL` に `https://<デプロイ先>/callback` を入力 → 「更新」→「検証」で成功を確認
   - `Webhook の利用` を **オン**
   - `グループトーク・複数人トークへの参加を許可する` を **オン**（グループで使う場合）
   - `応答メッセージ` と `あいさつメッセージ` は **オフ**（LINE Official Account Manager 側の設定。オンだと定型文が二重に返る）
6. 同タブの QR コードを 2 人とも読み取って **友だち追加** → ボットからウェルカムメッセージと今日のリストが届けば OK
7. グループで使う場合：2 人のグループにボットを招待（招待時に自動で配信先として登録されます）

> 💰 **料金について**：無料の「コミュニケーションプラン」は **push 送信が月 200 通まで**（グループ宛は人数分カウント）。
> 2 人に朝・夜で 1 日 2 回 → 約 120 通/月で収まります。タップ時などの **reply は無料・無制限** です。

### 2. （任意）LIFF の設定 ― LINE 内でチェックリスト画面を開く

LIFF を使うと、LINE 内でログイン済みのままチェックリストが開き、「誰が完了したか」も自動で記録されます。
設定しなくても `BASE_URL/dashboard?key=<DASHBOARD_KEY>` で同じ画面が使えます（メッセージ内ボタンには自動で key 付き URL が入ります）。

1. 同じプロバイダーで **LINE ログインチャネル** を作成（アプリタイプ：ウェブアプリ）
2. `チャネル ID` → 環境変数 `LINE_LOGIN_CHANNEL_ID`
3. 「LIFF」タブ → 追加
   - サイズ：`Full` / エンドポイント URL：`https://<デプロイ先>/dashboard`
   - Scope：`openid`, `profile` にチェック
4. 発行された `LIFF ID` → 環境変数 `LIFF_ID`
5. 作成したチャネルを **「公開済み」** にする（開発中のままだと開発者本人しか開けません）
6. （推奨）2 人の LINE ユーザー ID を `ALLOWED_USER_IDS` にカンマ区切りで設定
   （ユーザー ID は LINE Developers のチャネル基本設定の「あなたのユーザー ID」、またはサーバーログで確認）

### 3. データベース（Supabase・無料）

1. [Supabase](https://supabase.com/) で New project を作成（Region: Tokyo）
2. Project Settings → Database → **Connection string（URI）** をコピー
   - Render から接続するときは **Session pooler**（IPv4 対応）の URI を使う
3. 環境変数 `DATABASE_URL` に設定（`postgres://` / `postgresql://` のどちらでも OK。テーブルは起動時に自動作成）

> Neon など他の無料 Postgres でも同様に動きます。

### 4. Render へデプロイ

1. [Render](https://render.com/) → New → **Web Service** → この GitHub リポジトリを選択
2. 設定
   - Root Directory：`chore-bot`
   - Runtime：Python 3 / Build：`pip install -r requirements.txt`
   - Start：`uvicorn app.main:app --host 0.0.0.0 --port $PORT`
   - Instance type：Free
3. Environment に `.env.example` の項目を設定（`BASE_URL` はデプロイ後の `https://xxxx.onrender.com`）
4. デプロイ後 `https://xxxx.onrender.com/healthz` が `{"ok": true}` を返すことを確認
5. LINE Developers の Webhook URL を `https://xxxx.onrender.com/callback` にして「検証」

（`render.yaml` を使った Blueprint デプロイも可能です。その場合はファイルをリポジトリ直下に置いてください）

### 5. 定期配信（GitHub Actions）

`.github/workflows/chore-bot-cron.yml` が毎朝 7:00 / 毎晩 21:00（JST）にアプリの `/cron/morning` `/cron/evening` を呼びます。

1. GitHub リポジトリの Settings → Secrets and variables → Actions → New repository secret
   - `CHORE_BOT_URL` = `https://xxxx.onrender.com`
   - `CHORE_BOT_CRON_SECRET` = アプリの `CRON_SECRET` と同じ値
2. Actions タブ → `chore-bot-cron` → **Run workflow** で手動テスト
3. 配信時刻を変えるときはワークフローの `cron:`（UTC 表記, JST−9 時間）を編集
   - 例：6:30 JST → `30 21 * * *`

> GitHub Actions の schedule は数分〜十数分遅れることがあり、60 日間リポジトリに更新がないと自動停止します。
> 時刻の正確さを重視するなら [cron-job.org](https://cron-job.org/)（無料）で
> `POST https://xxxx.onrender.com/cron/morning`、ヘッダー `X-Cron-Secret: <CRON_SECRET>` を登録するのがおすすめです。
> 同じ日に 2 回呼ばれても二重送信はされません（強制再送は `?force=true`）。

---

## ローカルで動かす

```bash
cd chore-bot
python -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
cp .env.example .env   # 値を編集
set -a && source .env && set +a
uvicorn app.main:app --reload
# → http://localhost:8000/dashboard?key=<DASHBOARD_KEY>
pytest -q
```

LINE から Webhook を受けるには公開 URL が必要なので、[ngrok](https://ngrok.com/) などで `ngrok http 8000` し、
その URL + `/callback` を Webhook URL に設定します。

配信のテスト：

```bash
curl -X POST -H "X-Cron-Secret: $CRON_SECRET" "http://localhost:8000/cron/morning?force=true"
curl -X POST -H "X-Cron-Secret: $CRON_SECRET" "http://localhost:8000/cron/morning?target_date=2026-11-01&force=true"
```

## API

| メソッド | パス | 説明 |
| --- | --- | --- |
| POST | `/callback` | LINE Webhook（署名検証あり） |
| POST | `/cron/morning` | 朝の配信（`X-Cron-Secret` 必須, `?target_date=` `?force=true`） |
| POST | `/cron/evening` | 夜のリマインド（残りがあるときだけ） |
| GET | `/dashboard` | チェックリスト画面 |
| GET | `/api/board?target_date=YYYY-MM-DD` | その日のタスク＋持ち越し |
| POST | `/api/instances/{id}` | `{"done": true/false}` で完了・取り消し |
| GET | `/api/tasks` | 登録タスクとスケジュールの一覧 |

`/api/*` の認証：LIFF の ID トークン（`Authorization: Bearer ...`）または `X-Dashboard-Key`。

## 初期タスクリストとカスタマイズ

`app/seed_tasks.py` の `TASK_TREE` に、**カテゴリ → 頻度 → タスク** の階層のままタスクを持たせています。

| カテゴリ | 毎日 | 週1〜2回 | 月1〜数ヶ月 |
| --- | --- | --- | --- |
| 🍳 キッチン（水回り・家電の細部） | 5 | 6 | 5 |
| 🛁 お風呂・洗面所・トイレ（水回りの細かいメンテ） | 3 | 6 | 6 |
| 🛋️ リビング・居室（隠れホコリ・細部） | 2 | 4 | 8 |
| 🚪 玄関・廊下・その他（名もなき家事） | 0 | 2 | 7 |

```python
TASK_TREE = {
    "kitchen": {
        "label": "キッチン", "subtitle": "水回り・家電の細部", "emoji": "🍳",
        "daily": [
            T("k_drain_trash", "排水口のゴミ受けのゴミ捨て＆簡単なスポンジ洗い", 3),   # 所要3分
        ],
        "weekly": [
            T("k_grill", "魚焼きグリル（受け皿・網）の分解洗浄", 15),                 # 日曜（WEEKLY_DEFAULT）
            T("k_board_sponge", "まな板・スポンジの除菌・漂白", 5, weekdays=TWICE_A_WEEK),  # 水・日
        ],
        "monthly": [
            T("k_range_hood", "レンジフード・換気扇のフィルター交換…", 30, day=1),     # 毎月1日
            T("k_knife", "包丁やキッチンバサミの研ぎ・点検", 15, day=20, months=EVERY_3_MONTHS),  # 3ヶ月ごと
            # 日付の代わりに nth=(2, SAT) とすると「第2土曜」、nth=(-1, SUN) で「最終日曜」
        ],
    },
    ...
}
```

### 初期スケジュール（要調整ポイント）

- **週1〜2回**：すべて **日曜**。汚れやすい 4 件（まな板・スポンジ除菌／お風呂の排水口／トイレのフチ裏／ゴミ集め）は **水・日の週2回**
  - 日曜は 2 人で合計 3 時間前後になります。分散したい場合は `WEEKLY_DEFAULT = [SAT]` にしたり、カテゴリごとに `weekdays=[SAT]` などを付けてください
- **月1〜数ヶ月**：1日・5日・10日・15日・20日・25日に分散。燻煙剤・エアコンのルーバー・ルーター掃除は 2ヶ月ごと、包丁研ぎ・窓・網戸・下駄箱は 3ヶ月ごと
- **ゴミ集め**と**段ボール・古紙出し**は、お住まいの自治体の収集日に合わせて曜日を変更してください

### 反映のしかた

ファイルを編集して再デプロイ（再起動）すると、起動時に DB へ同期されます。

- 新しい `key` → 追加 / 既存の `key` → タイトル・スケジュールを更新（完了履歴は保持）
- リストから削除した `key` → 停止（`active=false`。過去の履歴は残る）

## 今後の拡張アイデア

- 担当者の割り当て（交互・固定）と、月ごとの「家事ポイント」集計
- ダッシュボードからのタスク追加・編集画面
- LINE リッチメニュー（「今日」「残り」「チェックリスト」ボタン）
- ゴミ出しの前夜リマインド
