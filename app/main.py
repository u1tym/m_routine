from fastapi import FastAPI

from app.database import lifespan
from app.logging_utils import register_logging, setup_logging
from app.routers import categories, routines

app = FastAPI(title="ルーティン管理 API", lifespan=lifespan)
setup_logging()
register_logging(app)

app.include_router(routines.router, prefix="/api")
app.include_router(categories.router, prefix="/api")


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}
