# 認証 API・DB 仕様書

## 1. 概要

| 項目 | 内容 |
|------|------|
| 役割 | ログイン・ログアウト、JWT 発行（HttpOnly Cookie）、自身のユーザー情報取得 |
| 想定 URL | Nginx 経由で `/api/auth` 以下（バックエンドでは `/login` 等） |
| 認証方式 | JWT（Cookie 名は既定 `access_token`） |
| トークン有効期限 | 30 分（環境変数 `ACCESS_TOKEN_EXPIRE_MINUTES` で変更可） |

他の FastAPI（`/api/recipe`、`/api/schedule` 等）は **JWT を発行せず**、Cookie の JWT を検証するだけです。検証ロジックは `JWTVerifier`（`auth_api/app/security/jwt_verifier.py`）を共有してください。

---

## 2. データベース

### 2.1 接続

接続情報は **リポジトリルートの `.env`** で指定します。

| 環境変数 | 説明 | 初期値（例） |
|----------|------|----------------|
| `DB_HOST` | ホスト | `localhost` |
| `DB_PORT` | ポート | `5432` |
| `DB_NAME` | データベース名 | `tamtdb` |
| `DB_USER` | ユーザー名 | `tamtuser` |
| `DB_PASSWORD` | パスワード | （`.env` 参照） |

SQLAlchemy の接続 URL は内部で  
`postgresql+psycopg2://{DB_USER}:{DB_PASSWORD}@{DB_HOST}:{DB_PORT}/{DB_NAME}`  
として組み立てます。

### 2.2 テーブル `public.accounts`

| カラム | 型 | NULL | 説明 |
|--------|-----|------|------|
| `id` | integer | NOT NULL | PK、シーケンス |
| `username` | varchar | NOT NULL | ログイン ID（一意） |
| `password` | varchar | NOT NULL | **bcrypt ハッシュ**（平文不可） |
| `session_info` | text | NULL | 本システムでは未使用 |
| `last_access` | timestamp (no tz) | NOT NULL | ログイン成功時に更新 |
| `is_deleted` | boolean | NOT NULL | `true` の行はログイン・参照対象外 |
| `created_at` | timestamp (no tz) | NOT NULL | 既定 `now()` |
| `updated_at` | timestamp (no tz) | NOT NULL | 既定 `now()`、ログイン成功時に更新 |
| `random_number` | integer | NULL | 本システムでは未使用 |

**インデックス・制約**

- PRIMARY KEY: `id`
- UNIQUE: `username`（`ix_accounts_username`）

**アプリ側の扱い**

- ログイン・`/me` では `is_deleted = false` の行のみ対象
- `session_info`、`random_number` は読み書きしない

---

## 3. 環境変数（JWT・CORS・Cookie）

| 環境変数 | 必須 | 説明 |
|----------|------|------|
| `SECRET_KEY` | はい | JWT 署名用秘密鍵 |
| `ALGORITHM` | いいえ | 既定 `HS256` |
| `CORS_ORIGINS` | いいえ | 許可オリジンをカンマ区切り（`credentials` 利用のため `*` 不可） |
| `COOKIE_NAME` | いいえ | 既定 `access_token` |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | いいえ | 既定 `30` |

### 3.1 Cookie 属性（ログイン時）

| 属性 | 値 |
|------|-----|
| `HttpOnly` | あり |
| `Secure` | あり |
| `SameSite` | `Lax` |
| `Path` | `/` |
| `Domain` | **指定なし**（IP アクセス向け） |
| `Max-Age` | `ACCESS_TOKEN_EXPIRE_MINUTES × 60` 秒 |

### 3.2 JWT クレーム（参考）

| クレーム | 内容 |
|----------|------|
| `sub` | ユーザー ID（文字列） |
| `username` | ユーザー名 |
| `iat` | 発行時刻（UNIX 秒） |
| `exp` | 有効期限 |

他サービスでは通常 `sub` をユーザー ID として利用します。

---

## 4. HTTP API

ベースパスは **Nginx の `proxy_pass` 設定に依存**します。下表の「アプリパス」は本リポジトリの FastAPI 上のパスです。`location /api/auth/ { proxy_pass http://auth/; }` のように末尾スラッシュ付きで切り出す場合、クライアントからは **`/api/auth/login`** のようにアクセスします。

### 4.1 `POST /login`

ログインに成功した場合、JWT を HttpOnly Cookie にセットし、本文で簡易メッセージを返します。

**リクエスト JSON**

| フィールド | 型 | 必須 |
|------------|-----|------|
| `username` | string | はい |
| `password` | string | はい |

**レスポンス `200`**

```json
{ "message": "ok" }
```

**エラー `401`**

- ユーザー不存在、`is_deleted = true`、パスワード不一致

```json
{ "detail": "ユーザー名またはパスワードが正しくありません" }
```

**副作用**

- `last_access`、`updated_at` を現在時刻で更新

---

### 4.2 `POST /logout`

Cookie を削除します（ログアウト）。

**レスポンス `200`**

```json
{ "message": "ok" }
```

Cookie 削除時も、設定時と同様に `Path=/`、`HttpOnly`、`Secure`、`SameSite=Lax` を指定して削除します。

---

### 4.3 `GET /me`

Cookie 内の JWT を検証し、DB からユーザーを読み取って返します。

**リクエスト**

- 必須: 有効な JWT Cookie（名前は `COOKIE_NAME`）

**レスポンス `200`**

```json
{
  "user": {
    "id": 1,
    "username": "example"
  }
}
```

**エラー `401`**

- Cookie なし、JWT 不正・期限切れ
- `sub` が不正、または該当ユーザーなし / 削除済み

---

### 4.4 `GET /health`

稼働確認用。認証不要。

```json
{ "status": "ok" }
```

---

## 5. CORS

- `Access-Control-Allow-Credentials: true`
- `Allow-Origin` は `CORS_ORIGINS` に列挙したオリジンのみ（ワイルドカードにしない）

Vue の `axios` では `withCredentials: true` が必要です。

---

## 6. 他 FastAPI での JWT 検証（`JWTVerifier`）

クラス: `auth_api.app.security.jwt_verifier.JWTVerifier`

| メソッド | 説明 |
|----------|------|
| `get_raw_token(request)` | Cookie から生トークンを取得（なければ `None`） |
| `decode_token(token)` | JWT を検証しペイロード `dict` を返す。失敗時は `HTTPException 401` |
| `verify_request(request)` | Cookie 取得＋検証 |
| `dependency()` | `Depends(...)` に渡す依存関数を返す |

**利用例**

```python
from fastapi import Depends, FastAPI
from auth_api.app.security.jwt_verifier import JWTVerifier

v = JWTVerifier(secret_key="環境変数から", algorithm="HS256", cookie_name="access_token")
require_user = v.dependency()

app = FastAPI()

@app.get("/protected")
def protected(claims: dict = Depends(require_user)):
    return {"user_id": claims["sub"]}
```

認証 API と **同一の** `SECRET_KEY`・`ALGORITHM`・`COOKIE_NAME` を使う必要があります。

---

## 7. エラーレスポンス形式

FastAPI 既定の JSON 形式です。

```json
{ "detail": "メッセージまたは検証エラー内容" }
```

---

## 8. 関連ファイル

| ファイル | 内容 |
|----------|------|
| `auth_api/app/routers/auth.py` | `/login` `/logout` `/me` |
| `auth_api/app/security/jwt_tokens.py` | JWT 発行 |
| `auth_api/app/security/jwt_verifier.py` | JWT 検証クラス |
| `auth_api/app/security/password.py` | bcrypt 検証・ハッシュ生成 |
| `auth_api/app/models.py` | `Account` モデル |
