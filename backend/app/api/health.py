from __future__ import annotations

"""Health-check endpoints."""

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from sqlalchemy import text

router = APIRouter()


@router.get("/health")
def health() -> dict[str, str]:
    """Liveness probe — process is up."""
    from app.core.database import using_sqlite

    return {
        "status": "ok",
        "service": "sterling-syndicate-api",
        "database_mode": "sqlite" if using_sqlite() else "postgresql",
    }


@router.get("/health/ready")
def readiness():
    """Readiness probe — database is reachable."""
    from app.core.database import get_engine, using_sqlite

    try:
        with get_engine().connect() as conn:
            conn.execute(text("SELECT 1"))
        return {
            "status": "ready",
            "database": "ok",
            "database_mode": "sqlite" if using_sqlite() else "postgresql",
        }
    except Exception:
        # Must be non-2xx so k8s/LB readiness marks the pod NotReady and stops
        # routing traffic to an instance whose database is unreachable.
        return JSONResponse(
            status_code=503,
            content={"status": "degraded", "database": "unreachable"},
        )
