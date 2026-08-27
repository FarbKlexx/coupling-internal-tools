import pytest
from fastapi.testclient import TestClient

from app.core.auth_db import init_schema as init_auth_schema
from app.core.kanban_db import init_schema as init_kanban_schema

# An einer Stelle, damit Tests dasselbe Passwort verwenden wie die Fixture.
# Erfüllt die Richtlinie: 15+ Zeichen, kein Kontextwort, enthält nicht den
# Benutzernamen (was `check_password_policy` sonst zu Recht ablehnt).
ADMIN_USERNAME = "chefin"
ADMIN_PASSWORD = "Vier-Pferde-Traben-Los"


@pytest.fixture
def kanban_db(tmp_path, monkeypatch):
    """Point the kanban database at a fresh file for one test.

    Works because `kanban_db.db_path()` reads the environment on every call
    instead of capturing it at import time.
    """
    monkeypatch.setenv("KANBAN_DB_PATH", str(tmp_path / "kanban.db"))
    init_kanban_schema()
    return tmp_path / "kanban.db"


@pytest.fixture(autouse=True)
def auth_db(tmp_path, monkeypatch):
    """Frische Konten-Datenbank und Zugangsdaten für den Erststart.

    **autouse**, weil `TestClient(app)` den Lifespan mitfährt: der legt beim
    ersten Start einen Administrator an und verweigert den Start, wenn
    `ADMIN_USERNAME`/`ADMIN_PASSWORD` fehlen. Ohne diese Fixture bräche jeder
    Test, der die App hochfährt — mit einer Meldung über Umgebungsvariablen,
    die mit dem eigentlichen Testgegenstand nichts zu tun hat.
    """
    monkeypatch.setenv("AUTH_DB_PATH", str(tmp_path / "auth.db"))
    monkeypatch.setenv("ADMIN_USERNAME", ADMIN_USERNAME)
    monkeypatch.setenv("ADMIN_PASSWORD", ADMIN_PASSWORD)
    # Weder lokal noch im Test läuft etwas über TLS — ein `Secure`-Cookie käme
    # im TestClient nie zurück.
    monkeypatch.setenv("SESSION_COOKIE_NAME", "session")
    monkeypatch.setenv("SESSION_COOKIE_SECURE", "0")
    init_auth_schema()
    return tmp_path / "auth.db"


@pytest.fixture
def anon_client(kanban_db):
    """Client ohne Anmeldung — für alles, was 401 liefern soll."""
    with TestClient(app_instance()) as client:
        yield client


@pytest.fixture
def client(anon_client):
    """Angemeldet als Administrator.

    Der Administrator hat per Definition jede Seitenberechtigung, deshalb ist
    das der richtige Client für alle Feature-Tests: sie prüfen das Werkzeug,
    nicht die Berechtigung.
    """
    response = anon_client.post(
        "/auth/login",
        json={"username": ADMIN_USERNAME, "password": ADMIN_PASSWORD},
    )
    assert response.status_code == 200, response.text
    return anon_client


@pytest.fixture
def make_user(client):
    """Legt ein eingeschränktes Konto an und meldet es in einem eigenen Client an.

    Gibt `(client, summary)` zurück. Das Startpasswort muss gewechselt werden
    (ASVS 6.4.1), das erledigt die Fixture gleich mit — sonst liefe jeder Test
    gegen das 403 „Bitte zuerst das Passwort ändern".
    """
    created = []

    def make(username: str, *, pages=(), is_admin: bool = False, change_password=True):
        response = client.post(
            "/auth/users",
            json={
                "username": username,
                "is_admin": is_admin,
                "pages": [page.value for page in pages],
            },
        )
        assert response.status_code == 201, response.text
        body = response.json()
        initial = body["initial_password"]

        user_client = TestClient(app_instance())
        login = user_client.post(
            "/auth/login", json={"username": username, "password": initial}
        )
        assert login.status_code == 200, login.text

        if change_password:
            # Enthaelt bewusst nicht den Benutzernamen - die Richtlinie lehnt
            # das ab, und zwar zu Recht.
            new_password = f"Gewechselt-Im-Test-{len(created)}-2026"
            changed = user_client.post(
                "/auth/password",
                json={"current_password": initial, "new_password": new_password},
            )
            assert changed.status_code == 204, changed.text
            # Der Wechsel beendet alle *anderen* Sitzungen, die eigene bleibt.
            body["initial_password"] = new_password

        created.append(user_client)
        return user_client, body

    yield make

    for user_client in created:
        user_client.close()


def app_instance():
    """Importiert die App erst beim Aufruf.

    Auf Modulebene importiert würde `app.main` schon beim Sammeln der Tests
    geladen — noch bevor die Fixtures oben die Umgebung gesetzt haben.
    """
    from app.main import app

    return app
