from typing import Annotated

from fastapi import Depends, FastAPI
from sqlalchemy.orm import Session

from app.api.v1 import health
from app.api.v1.health import derive_state
from app.core.config import get_settings
from app.db.session import get_db

settings = get_settings()

app = FastAPI(title=settings.app_title, version=settings.app_version)
app.include_router(health.router, prefix="/v1")


@app.get("/")
def root() -> dict[str, str]:
    return {"service": settings.app_title, "version": settings.app_version}


@app.get("/health")
def health_root(db: Annotated[Session, Depends(get_db)]) -> dict[str, str]:
    return derive_state(db)
