"""Smoke test: the app boots and answers the container healthcheck.

This is what `docker-compose.yml` polls, so a broken router registration or an
import error anywhere in `app.main` has to fail here rather than on the server.
"""

from fastapi.testclient import TestClient

from app.core.kanban_db import db_path
from app.main import app


def test_app_starts_and_health_answers_ok(kanban_db):
    # The context manager runs the lifespan, i.e. the same startup path the
    # container takes.
    with TestClient(app) as client:
        response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_health_does_not_touch_the_database(kanban_db):
    """The healthcheck must stay green while the database is unavailable.

    Otherwise a locked or missing SQLite file would mark the container
    unhealthy and restart a backend that still serves the other five tools
    perfectly well.
    """
    with TestClient(app) as client:
        db_path().unlink()
        assert not db_path().exists()

        response = client.get("/health")

    assert response.status_code == 200


def test_every_router_is_reachable():
    """Guard against a feature router silently not being included."""
    paths = {getattr(route, "path", "") for route in app.routes}

    for expected in (
        "/health",
        "/upload",
        "/awin-banner-csv",
        "/convert-images",
        "/qr-code",
        "/protect-pdf",
        "/kanban/board",
    ):
        assert expected in paths
