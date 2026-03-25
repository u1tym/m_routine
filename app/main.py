from fastapi import FastAPI

from app.database import lifespan
from app.routers import categories, routines

app = FastAPI(title="ルーティン管理 API", lifespan=lifespan)

app.include_router(routines.router, prefix="/api")
app.include_router(categories.router, prefix="/api")


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}
