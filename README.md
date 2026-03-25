# ルーティン管理 API（FastAPI）

PostgreSQL に保存されたルーティン定義の参照・登録・論理削除、および指定年月への `public.schedules` への反映を行う REST API です。

## 前提条件

- Python 3.11 以上推奨（3.12 で動作確認）
- 既存の PostgreSQL に、仕様どおりのスキーマ（`plan` スキーマ、`public.schedules` / `public.activity_categories` / `public.holidays` など）が作成済みであること

## セットアップ

### 1. 仮想環境と依存関係

```powershell
cd d:\h\github\m_routine
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

### 2. 接続設定（`.env`）

プロジェクト直下の `.env` に PostgreSQL 接続情報を記載します。初期値は次のとおりです。

| 変数名 | 意味 | 初期値 |
|--------|------|--------|
| `POSTGRES_HOST` | ホスト | `localhost` |
| `POSTGRES_PORT` | ポート | `5432` |
| `POSTGRES_DB` | データベース名 | `tamtdb` |
| `POSTGRES_USER` | ユーザー | `tamtuser` |
| `POSTGRES_PASSWORD` | パスワード | （`.env` 参照） |

`app/config.py` の `Settings` が上記環境変数を読み込み、`postgresql://...` 形式の DSN を組み立てます。

### 3. サーバー起動

プロジェクトルート（`m_routine`）をカレントにして実行します。

```powershell
.\.venv\Scripts\Activate.ps1
cd d:\h\github\m_routine
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

- API ベース URL: `http://localhost:8000`
- 対話ドキュメント（Swagger UI）: `http://localhost:8000/docs`
- ReDoc: `http://localhost:8000/redoc`
- ヘルスチェック: `GET http://localhost:8000/health`

## エンドポイント概要

| メソッド | パス | 説明 |
|----------|------|------|
| GET | `/api/routines` | ルーティン定義一覧（削除済み除く） |
| POST | `/api/routines` | ルーティン定義の新規登録 |
| DELETE | `/api/routines/{routine_id}` | ルーティン定義の論理削除（`is_deleted`） |
| POST | `/api/routines/{routine_id}/apply` | 指定ルーティンを基準年月に反映（`schedules` へ挿入） |
| POST | `/api/routines/apply-all` | 削除されていない全ルーティンを同様に反映 |
| GET | `/api/categories` | アクティビティカテゴリ一覧（削除済み除く） |

リクエスト／レスポンスの型、DB との対応、日付算出ルールの詳細は **`API_DB_SPEC.md`** を参照してください。

## プロジェクト構成（主要ファイル）

- `app/main.py` — FastAPI アプリ生成、ルーター登録、`lifespan` で DB プール初期化
- `app/config.py` — `.env` から接続設定を読み込み
- `app/database.py` — `asyncpg` コネクションプール、`get_db` 依存注入
- `app/schemas.py` — Pydantic モデル（型ヒント付き API 入出力）
- `app/routers/routines.py` — ルーティン関連エンドポイント
- `app/routers/categories.py` — カテゴリ一覧
- `app/services/routine_dates.py` — `routine_adapt_day` に基づく日付計算
- `app/services/adjust_date.py` — 祝日・曜日除外と代替日
- `app/services/routine_apply.py` — 反映処理（休日取得、`schedules` 挿入）

## 注意事項

- **同一ルーティン・同一日付**の未削除スケジュールが既にある場合、反映 API は重複挿入を避けるため **新規行を追加しません**（冪等性に近い動作）。
- `apply-all` はルーティンごとにベストエフォートで処理し、失敗・スキップ内容はレスポンスの `errors` に積み上げます（HTTP は 200）。
