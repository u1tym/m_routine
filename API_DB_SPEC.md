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

## 2. スキーマとテーブル

### 2.1 `plan.routine_adapt_day`（適用日マスタ）

| 列 | 型 | 意味 |
|----|-----|------|
| `id` | serial PK | ID |
| `explain` | text NOT NULL | 説明（API 登録時は自動生成文を格納） |
| `what_number` | int NOT NULL | 何番目。正数は先頭から、**負数は末尾から** |
| `order_week` | int NOT NULL | **0=日曜 … 6=土曜**、**-1=曜日指定なし**（カレンダー日ベース） |

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

### 2.2 `plan.routine_adjust_day`（調整日マスタ）

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

### 2.3 `plan.routine`（ルーティン本体）

| 列 | 型 | 意味 |
|----|-----|------|
| `id` | serial PK | ルーティン ID |
| `title` | text NOT NULL | 名称（**ユニーク制約 `uq_routine_title`**） |
| `activity_category_id` | int NOT NULL FK | `public.activity_categories(id)` |
| `adapt_id` | int NOT NULL FK | `plan.routine_adapt_day(id)` |
| `adjust_id` | int NULL FK | `plan.routine_adjust_day(id)`。調整なしの場合は NULL |
| `is_deleted` | bool NOT NULL | **論理削除フラグ** |

一覧・反映対象は通常 **`is_deleted = false`** のみ。

### 2.4 `public.activity_categories`

API のカテゴリ一覧・登録時検証では **`is_deleted = false`** のみ扱う。

### 2.5 `public.holidays`

| 列 | 意味 |
|----|------|
| `date` | 祝日の日付（unique インデックスあり） |

### 2.6 `public.schedules`（反映先）

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

## 3. HTTP API 仕様

ベースパス: `/api`（ルーティン・カテゴリ）。ヘルスチェックは `/health`。

共通: JSON、`Content-Type: application/json`。レスポンスモデルは OpenAPI（`/docs`）と `app/schemas.py` に一致。

### 3.1 GET `/api/routines` — ルーティン定義一覧

- **条件**: `plan.routine.is_deleted = false`
- **結合**: `activity_categories`（名称）、`routine_adapt_day`、`routine_adjust_day`（LEFT。無い場合 `adjust` は JSON で省略／null）

**レスポンス配列要素（概念）**

- `id`: `plan.routine.id`
- `title`: `plan.routine.title`
- `activity_category_id`, `activity_category_name`
- `adapt`: `{ "number": what_number, "week": order_week }`
- `adjust`: ある場合のみ  
  - `avoid`: `{ "holiday", "sun", … "sat" }` ← `avoid_*` 列に対応  
  - `alt`: `alt_day`（1 または -1）

### 3.2 GET `/api/categories` — カテゴリ一覧

- **条件**: `activity_categories.is_deleted = false`
- **レスポンス**: `[{ "id", "name" }, ...]`

### 3.3 POST `/api/routines` — ルーティン定義登録

**ボディ**

- `title`, `activity_category_id`, `adapt`（同上）
- `adjust`: 任意。無い場合 `adjust_id` は NULL

**トランザクション**

1. `routine_adapt_day` INSERT（`explain` はサーバ生成）
2. `adjust` がある場合 `routine_adjust_day` INSERT
3. `routine` INSERT

**エラー**

- カテゴリが存在しない／削除済み: **400**
- `title` ユニーク違反: **409**

**レスポンス**: `{ "id": 新 routine id }`（201）

### 3.4 DELETE `/api/routines/{routine_id}` — 論理削除

- `UPDATE plan.routine SET is_deleted = true WHERE id = ? AND is_deleted = false`
- 更新 0 件: **404**
- レスポンス: メッセージ JSON

### 3.5 POST `/api/routines/{routine_id}/apply` — 個別反映

**ボディ**: `{ "year": int, "month": int }`（1〜12）

**処理概要**

1. 対象ルーティンを `is_deleted = false` で取得（adapt 必須、adjust は任意）
2. `routine_adapt_day` により基準日を 1 日決定（無い月は挿入 0 件）
3. `adjust` 行が紐づく場合は祝日・曜日除外と代替日を適用
4. 条件を満たせば `schedules` に 1 件 INSERT（重複時はスキップ）

**エラー例（400）**

- ルーティンが存在しない／削除済み
- 代替日が決定できない（除外が広すぎる等）

**レスポンス**: `{ "inserted_count", "dates": ["YYYY-MM-DD", ...], "errors": [] }`  
（個別反映では通常 `errors` は空配列）

### 3.6 POST `/api/routines/apply-all` — 全件反映

**ボディ**: 同上 `year`, `month`

- `is_deleted = false` の全 `plan.routine` に対し、**3.5 と同じロジック**を順に適用
- ルーティンごとのエラーは **HTTP 200 のまま** `errors` 配列に `"id={routine_id}: ..."` 形式で追加
- `dates` は全ルーティンで実際に INSERT された日付の結合

---

## 4. 実装上の固定値・補足

- **スキーマ名**: `plan`（ルーティン系）、`public`（カテゴリ・スケジュール・祝日）
- **非同期 DB ドライバ**: `asyncpg`
- **依存注入**: `get_db`（リクエストスコープでコネクション取得）
- OpenAPI タグ: `routines`, `categories`

他エージェントがコードを読む場合は、`app/routers/routines.py` と `app/services/routine_apply.py` を起点に追うと、SQL とドメインロジックの対応が把握しやすいです。
