from fastapi import HTTPException, Request, status
import jwt

from app.config import settings


def get_raw_token(request: Request) -> str | None:
    return request.cookies.get(settings.cookie_name)


def decode_verified_username(token: str) -> str:
    if not settings.jwt_secret_key:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="JWT 秘密鍵が設定されていません",
        )
    try:
        payload = jwt.decode(
            token,
            settings.jwt_secret_key,
            algorithms=[settings.jwt_algorithm],
        )
    except jwt.PyJWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="無効なトークンです",
        ) from None

    username = payload.get("username")
    if not isinstance(username, str) or not username.strip():
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="ユーザー名クレームが不正です",
        )
    return username.strip()
