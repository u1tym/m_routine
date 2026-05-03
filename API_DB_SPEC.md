# API・データベース仕様書（生成 AI 向け）

このドキュメントは、本リポジトリの FastAPI サービスと PostgreSQL スキーマの対応関係、およびビジネスルールを機械的に解釈できるよう整理したものです。

---

## 1. 接続設定

- アプリケーションは **環境変数**（`.env` 経由）から PostgreSQL に接続します。
- 変数名と意味:
  - `POSTGRES_HOST`, `POSTGRES_PORT`, `POSTGRES_DB`, `POSTGRES_USER`, `POSTGRES_PASSWORD`
- DSN 形式: `postgresql://{USER}:{PASSWORD}@{HOST}:{PORT}/{DB}`
- 実装: `app/config.py` の `Settings.database_dsn`

---

## 2. 認証（ルーティン API 共通）

ルーティン系エンドポイント（`/routines` 以下）は **認証必須**。カテゴリ一覧・`/health` は認証不要。

### 2.1 JWT とアカウント ID（`aid`）

1. HTTP の **Cookie**（既定名 `access_token`、`COOKIE_NAME` で変更可）から JWT 文字列を取得する。
2. **署名検証付き**でデコードする（平文デコードのみは認可に使わない）。実装: `app/jwt_auth.py`。
3. 検証済みペイロードの **`username`** クレーム（非空文字列）をログインユーザー名とする。詳細は `JWT_USERNAME_TECH_SPEC.md`。
4. `public.accounts` を **`accounts.username = username` かつ `is_deleted = false`** で検索し、ヒットした行の **`id` を `aid`** とする。実装: `app/deps.py` の `get_current_aid`。

### 2.2 環境変数（JWT）

| 変数 | 説明 |
|------|------|
| `JWT_SECRET_KEY` または `SECRET_KEY` | 署名検証用秘密鍵（発行側と同一） |
| `JWT_ALGORITHM` | 既定 `HS256` |
| `COOKIE_NAME` | JWT を載せる Cookie 名、既定 `access_token` |

秘密鍵未設定時は JWT 検証で **503**（設定不備）となる。

### 2.3 認可エラー（例）

| 状況 | HTTP |
|------|------|
| Cookie なし／トークン不正／期限切れ／`username` 不正 | **401** |
| JWT は正しいが該当アカウントなし／削除済み | **401** |
| 秘密鍵未設定 | **503** |

---

## 3. スキーマとテーブル

### 3.1 `public.accounts`（参照のみ）

| 列 | 用途（本サービス） |
|----|---------------------|
| `id` | `plan.routine.aid` の参照先 |
| `username` | JWT の `username` と突合 |
| `is_deleted` | `true` の行はログイン対象外 |

---

### 3.2 `plan.routine_adapt_day`（適用日マスタ）

| 列 | 型 | 意味 |
|----|-----|------|
| `id` | serial PK | ID |
| `explain` | text NOT NULL | 説明（API 登録時は自動生成文を格納） |
| `what_number` | int NOT NULL | 何番目。正数は先頭から、**負数は末尾から** |
| `order_week` | int NOT NULL | **0=日曜 … 6=土曜**、**-1=曜日指定なし**（カレンダー日ベース） |
| `adapt_jan` … `adapt_dec` | boolean | **その月に「反映」処理の対象にするか**。`true`＝対象、`false`＝その月は反映しない。NULL は **`true` と同様**に扱う（実装上の解釈） |

**日付算出ルール（実装: `app/services/routine_dates.py`）**

- `order_week == -1`（月内の「日」指定）  
  - `what_number > 0` → その月の **what_number 日**（存在しない日付ならその月は対象なし）  
  - `what_number == -1` → **月末日**  
  - `what_number <= -2` → 月末から数えて **|what_number| 番目**（例: -2 は「末日の前日」相当の位置付け。実装では `末日 - (|n|-1)` 日）
- `order_week in [0,6]`（特定曜日の第 N 回）  
  - 当月の該当曜日の日付を昇順に並べる  
  - `what_number > 0` → **先頭から N 番目**（1 始まり）  
  - `what_number < 0` → **末尾から |N| 番目**（配列インデックスは `len + what_number`）

Python の `date.weekday()`（月=0…日=6）を DB の曜日（日=0…土=6）に直す式: `(weekday + 1) % 7`。

### 3.3 `plan.routine_adjust_day`（調整日マスタ）

| 列 | 型 | 意味 |
|----|-----|------|
| `id` | serial PK | ID |
| `explain` | text NOT NULL | 説明（API 登録時は自動生成） |
| `avoid_holiday` | bool | `public.holidays.date` に含まれる日を除外するか |
| `avoid_sun` … `avoid_sat` | bool | 日〜土をそれぞれ除外するか（DB 曜日 0〜6 と対応） |
| `alt_day` | int IN (1, -1) | **1** = 未来方向に進めて最初の非除外日、**-1** = 過去方向 |

**代替日解決（実装: `app/services/adjust_date.py`）**

1. 算出した基準日が除外に該当しない → その日を採用  
2. 該当する → `alt_day` の符号に応じて 1 日ずつ移動し、**最初に除外に該当しない日**を採用（最大約 400 日探索。見つからなければ失敗扱い）

`public.holidays` は **基準年の前後 1 年分**をクエリしてキャッシュし、月をまたいだ移動にも利用する。

### 3.4 `plan.routine`（ルーティン本体）

| 列 | 型 | 意味 |
|----|-----|------|
| `id` | serial PK | ルーティン ID |
| `title` | text NOT NULL | 名称（**ユニーク制約 `uq_routine_title`**） |
| `activity_category_id` | int NOT NULL FK | `public.activity_categories(id)` |
| `adapt_id` | int NOT NULL FK | `plan.routine_adapt_day(id)` |
| `adjust_id` | int NULL FK | `plan.routine_adjust_day(id)`。調整なしの場合は NULL |
| `aid` | int NOT NULL FK | **`public.accounts(id)`**。JWT で特定したログインユーザーのアカウント ID |
| `is_deleted` | bool NOT NULL | **論理削除フラグ** |

一覧・取得・更新・削除・反映は、原則 **`is_deleted = false` かつ `aid` = 現在ユーザーのアカウント ID** に限定する。

月ごとの反映可否（`adapt_jan`～`adapt_dec`）は **`plan.routine` には持たず**、`plan.routine_adapt_day` に保持する。

### 3.5 `public.activity_categories`

API のカテゴリ一覧・登録時検証では **`is_deleted = false`** のみ扱う。

### 3.6 `public.holidays`

| 列 | 意味 |
|----|------|
| `date` | 祝日の日付（unique インデックスあり） |

### 3.7 `public.schedules`（反映先）

反映 API が挿入する行のマッピング:

| 列 | 設定値 |
|----|--------|
| `title` | `plan.routine.title` |
| `start_datetime` | 算出（＋調整後）の日付の **00:00:00**（`timestamp without time zone`） |
| `duration` | `1` |
| `is_all_day` | `true` |
| `activity_category_id` | `plan.routine.activity_category_id` |
| `schedule_type` | `'TODO'`（文字列） |
| `location` | `''` |
| `details` | `''` |
| `is_todo_completed` | `false` |
| `is_deleted` | `false` |
| `routine_id` | `plan.routine.id` |

**重複回避**: 同一 `routine_id` かつ同一カレンダー日（`start_datetime::date`）で **`is_deleted = false` の行が既に存在する場合、新規 INSERT は行わない**（`WHERE NOT EXISTS`）。

---

## 4. HTTP API 仕様

ベースパス: `/`（ルーティン・カテゴリ）。ヘルスチェックは `/health`。

共通: JSON、`Content-Type: application/json`。レスポンスモデルは OpenAPI（`/docs`）と `app/schemas.py` に一致。

### 4.1 認証の要否

| パス | 認証 |
|------|------|
| `GET /health` | 不要 |
| `GET /categories` | 不要 |
| `GET /routines`, `POST /routines`, `PUT /routines/{id}`, `DELETE /routines/{id}`, `POST /routines/{id}/apply`, `POST /routines/apply-all` | **必須**（Cookie JWT → `aid`） |

### 4.2 GET `/routines` — ルーティン定義一覧

- **条件**: `plan.routine.is_deleted = false` **かつ** `plan.routine.aid = <現在の aid>`
- **結合**: `activity_categories`（名称）、`routine_adapt_day`（適用日・**月次フラグ**）、`routine_adjust_day`（LEFT。無い場合 `adjust` は null）

**レスポンス配列要素（概念）**

- `id`, `title`, `activity_category_id`, `activity_category_name`
- `adapt_jan` … `adapt_dec`（`routine_adapt_day` 由来。API では boolean、既定 true）
- `adapt`: `{ "number": what_number, "week": order_week }`
- `adjust`: ある場合のみ  
  - `avoid`: `{ "holiday", "sun", … "sat" }` ← `avoid_*` 列に対応  
  - `alt`: `alt_day`（1 または -1）

### 4.3 GET `/categories` — カテゴリ一覧

- **条件**: `activity_categories.is_deleted = false`
- **レスポンス**: `[{ "id", "name" }, ...]`

### 4.4 POST `/routines` — ルーティン定義登録

**前提**: 認証済み。登録行の `aid` は **トークンから解決したアカウント ID**。

**ボディ**

- `title`, `activity_category_id`, `adapt`（`number` / `week`）
- `adapt_jan` … `adapt_dec`（任意項目だがスキーマ上は既定 `true`。登録時は `routine_adapt_day` に保存）
- `adjust`: 任意。無い場合 `adjust_id` は NULL

**トランザクション**

1. `routine_adapt_day` INSERT（`explain` はサーバ生成、**月次フラグ含む**）
2. `adjust` がある場合 `routine_adjust_day` INSERT
3. `routine` INSERT（**`aid` をセット**）

**エラー**

- カテゴリが存在しない／削除済み: **400**
- `title` ユニーク違反: **409**

**レスポンス**: `{ "id": 新 routine id }`（201）

### 4.5 DELETE `/routines/{routine_id}` — 論理削除

- `UPDATE plan.routine SET is_deleted = true WHERE id = ? AND aid = <現在の aid> AND is_deleted = false`
- 更新 0 件: **404**
- レスポンス: メッセージ JSON

### 4.6 PUT `/routines/{routine_id}` — ルーティン定義編集

**前提**: 対象行は **`aid` が現在ユーザーと一致**すること。

**ボディ**

- `title`, `activity_category_id`, `adapt`, **`adapt_jan`～`adapt_dec`**
- `adjust`: 無い（または null）場合は調整を解除、ある場合は登録と同じ形で調整内容を更新

**処理概要**

1. 対象ルーティンを `id`・**`aid`**・`is_deleted = false` で取得（存在しなければ 404）
2. `public.activity_categories` を検証（削除済みは無効。無効なら 400）
3. `plan.routine_adapt_day` を更新（`adapt_id` は変更しない。**説明・適用ルール・月次フラグ**をすべて反映）
4. `adjust` の有無に応じて `plan.routine_adjust_day`（既存更新 or 新規追加）または `plan.routine.adjust_id = NULL`
5. `plan.routine` の `title` / `activity_category_id`（および必要なら `adjust_id`）を更新（`title` はユニーク）

**エラー**

- ルーティンが見つからない／削除済み／他ユーザーのデータ: **404**
- `activity_category_id` が無効: **400**
- `title` ユニーク違反: **409**

**レスポンス**: `{ "id": 編集対象 routine id }`（200）

### 4.7 POST `/routines/{routine_id}/apply` — 個別反映

**ボディ**: `{ "year": int, "month": int }`（1〜12）

**前提**: 対象ルーティンは **`aid` が現在ユーザーと一致**すること。

**処理概要**

1. 対象ルーティンを取得（**`id`・`aid`・未削除`**）。見つからなければ **400**（メッセージで通知）。
2. **`adapt_<month>`**（例: 1 月なら `adapt_jan`）が **偽**のとき、その月は **スケジュールを挿入しない**（エラーにしない。`inserted_count` は 0）。
3. 月が対象のとき、`routine_adapt_day` により基準日を 1 日決定（無い月は挿入 0 件）。
4. `adjust` 行が紐づく場合は祝日・曜日除外と代替日を適用。
5. 条件を満たせば `schedules` に 1 件 INSERT（重複時はスキップ）。

**エラー例（400）**

- ルーティンが存在しない／削除済み／他ユーザー
- 代替日が決定できない（除外が広すぎる等）

**レスポンス**: `{ "inserted_count", "dates": ["YYYY-MM-DD", ...], "errors": [] }`  
（個別反映では通常 `errors` は空配列）

### 4.8 POST `/routines/apply-all` — 全件反映

**ボディ**: 同上 `year`, `month`

- **`aid = <現在の aid>` かつ `is_deleted = false`** の `plan.routine` のみを対象に、**4.7 と同じロジック**を順に適用
- ルーティンごとのエラーは **HTTP 200 のまま** `errors` 配列に `"id={routine_id}: ..."` 形式で追加
- `dates` は全ルーティンで実際に INSERT された日付の結合

---

## 5. 実装上の固定値・補足

- **スキーマ名**: `plan`（ルーティン系）、`public`（アカウント・カテゴリ・スケジュール・祝日）
- **非同期 DB ドライバ**: `asyncpg`
- **依存注入**: `get_db`（コネクション）、**ルーティン API** では `get_current_aid`（認証＋アカウント解決）
- OpenAPI タグ: `routines`, `categories`

関連ファイル:

- `app/routers/routines.py` — ルーティン HTTP と SQL
- `app/services/routine_apply.py` — 反映・祝日読込・月次判定
- `app/deps.py`, `app/jwt_auth.py`, `app/config.py` — 認証・設定

他エージェントがコードを読む場合は、上記を起点に SQL とドメインロジックの対応が把握しやすいです。
