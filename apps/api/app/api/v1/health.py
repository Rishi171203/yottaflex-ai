from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.db.session import get_db

router = APIRouter(tags=["health"])


def derive_state(db: Session) -> dict[str, str]:
    try:
        db.execute(text("SELECT 1")).fetchall()
        db_state, version = "ok", ""
    except Exception:  # pragma: no cover — exercised against a live DB only
        return {"status": "degraded", "api": "ok", "db": "error"}
    result = db.execute(text("SELECT version_num FROM ops.alembic_version")).scalar()
    version = f"v{result}" if result else "not_migrated"
    return {"status": "ok", "api": "ok", "db": db_state, "schema": version}


@router.get("/health")
def derived_health(db: Annotated[Session, Depends(get_db)]) -> dict[str, str]:
    return derive_state(db)
