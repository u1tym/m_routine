import json
import logging
import time
import traceback
import uuid
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, Response


logger = logging.getLogger("routine_api")


def setup_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    )


def _safe_decode(raw: bytes) -> str:
    text = raw.decode("utf-8", errors="replace")
    if len(text) > 4000:
        return text[:4000] + "...(truncated)"
    return text


def _to_json_str(data: dict[str, Any]) -> str:
    return json.dumps(data, ensure_ascii=False, default=str)


def register_logging(app: FastAPI) -> None:
    @app.middleware("http")
    async def api_logging_middleware(request: Request, call_next):  # type: ignore[no-untyped-def]
        request_id = str(uuid.uuid4())
        start = time.perf_counter()
        raw_body = await request.body()

        async def receive() -> dict[str, Any]:
            return {"type": "http.request", "body": raw_body, "more_body": False}

        request._receive = receive  # type: ignore[attr-defined]
        req_info = {
            "event": "request_received",
            "request_id": request_id,
            "method": request.method,
            "path": request.url.path,
            "query": str(request.url.query),
            "client": request.client.host if request.client else None,
            "headers": dict(request.headers),
            "body": _safe_decode(raw_body),
        }
        logger.info(_to_json_str(req_info))

        try:
            response = await call_next(request)
        except Exception:
            err = {
                "event": "request_failed",
                "request_id": request_id,
                "method": request.method,
                "path": request.url.path,
                "query": str(request.url.query),
                "body": _safe_decode(raw_body),
                "traceback": traceback.format_exc(),
            }
            logger.exception(_to_json_str(err))
            raise

        response_body = b""
        async for chunk in response.body_iterator:
            response_body += chunk

        elapsed_ms = round((time.perf_counter() - start) * 1000, 2)
        res_info = {
            "event": "response_sent",
            "request_id": request_id,
            "method": request.method,
            "path": request.url.path,
            "status_code": response.status_code,
            "elapsed_ms": elapsed_ms,
            "response_headers": dict(response.headers),
            "response_body": _safe_decode(response_body),
        }
        logger.info(_to_json_str(res_info))

        return Response(
            content=response_body,
            status_code=response.status_code,
            headers=dict(response.headers),
            media_type=response.media_type,
        )

    @app.exception_handler(HTTPException)
    async def http_exception_handler(request: Request, exc: HTTPException) -> JSONResponse:
        detail = {
            "event": "http_exception",
            "method": request.method,
            "path": request.url.path,
            "query": str(request.url.query),
            "status_code": exc.status_code,
            "detail": exc.detail,
        }
        logger.warning(_to_json_str(detail))
        return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})

    @app.exception_handler(Exception)
    async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
        err = {
            "event": "unhandled_exception",
            "method": request.method,
            "path": request.url.path,
            "query": str(request.url.query),
            "exception_type": type(exc).__name__,
            "exception_message": str(exc),
            "traceback": traceback.format_exc(),
        }
        logger.exception(_to_json_str(err))
        return JSONResponse(
            status_code=500,
            content={"detail": "Internal Server Error"},
        )

