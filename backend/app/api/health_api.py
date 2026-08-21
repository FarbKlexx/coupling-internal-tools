"""Liveness endpoint for the container healthcheck.

Deliberately touches nothing: no database, no filesystem, no imports beyond
FastAPI. A healthcheck that reaches into SQLite would report the whole service
as unhealthy while the board is merely locked by a concurrent write, and would
restart a backend that is perfectly able to serve the other five tools.
"""

from fastapi import APIRouter
from pydantic import BaseModel

router = APIRouter()


class HealthStatus(BaseModel):
    status: str


@router.get("/health", response_model=HealthStatus)
def health() -> HealthStatus:
    """Answer 200 as long as the ASGI app is up and serving."""
    return HealthStatus(status="ok")
