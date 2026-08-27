"""Anmeldung, Sitzungen, zweiter Faktor und Kontenverwaltung.

Die Zuordnung zu ASVS steht in `docs/auth-umsetzungsplan.md`; hier steht in
jedem Docstring, *warum* die Anforderung existiert — eine Nummer allein sagt
beim Debuggen um zwei Uhr nachts nichts.
"""

from datetime import datetime, timezone

import pyotp
import pytest
from fastapi.testclient import TestClient

from app.core import auth_db as db
from app.core.security import MIN_PASSWORD_LENGTH
from app.schemas.access import Page
from tests.conftest import ADMIN_PASSWORD, ADMIN_USERNAME, app_instance

GOOD_PASSWORD = "Sieben-Blaue-Voegel-Fliegen"


# --------------------------------------------------------------------------
# Anmeldung
# --------------------------------------------------------------------------


def test_login_sets_an_httponly_cookie(anon_client):
    response = anon_client.post(
        "/auth/login",
        json={"username": ADMIN_USERNAME, "password": ADMIN_PASSWORD},
    )

    assert response.status_code == 200
    assert response.json()["username"] == ADMIN_USERNAME

    cookie = response.headers["set-cookie"]
    assert "HttpOnly" in cookie
    assert "SameSite=strict" in cookie.replace("samesite", "SameSite")
    assert "Path=/" in cookie


def test_the_session_token_never_appears_in_the_database(anon_client):
    """Gespeichert wird nur der SHA-256 — eine kopierte Datei ist wertlos."""
    anon_client.post(
        "/auth/login",
        json={"username": ADMIN_USERNAME, "password": ADMIN_PASSWORD},
    )
    token = anon_client.cookies["session"]

    with db.connect() as conn:
        stored = [row["token_hash"] for row in conn.execute("SELECT * FROM sessions")]

    assert stored
    assert token not in stored


@pytest.mark.parametrize(
    "payload",
    [
        {"username": ADMIN_USERNAME, "password": "voellig-falsches-passwort"},
        {"username": "gibtesnicht", "password": "voellig-falsches-passwort"},
    ],
    ids=["falsches-passwort", "unbekannter-benutzer"],
)
def test_a_failed_login_never_says_which_half_was_wrong(anon_client, payload):
    """Sonst ist der Endpunkt ein Benutzerverzeichnis (ASVS 6.3.1)."""
    response = anon_client.post("/auth/login", json=payload)

    assert response.status_code == 401
    assert response.json()["detail"] == "Benutzername oder Passwort ist falsch."


def test_ten_failures_lock_the_pair_of_ip_and_username(anon_client):
    """Und zwar das Paar, nicht den Benutzernamen allein.

    Eine reine Benutzersperre wäre selbst eine Waffe: zehn falsche Versuche
    würden genügen, um eine Kollegin auszusperren.
    """
    for _ in range(10):
        anon_client.post(
            "/auth/login", json={"username": ADMIN_USERNAME, "password": "falsch"}
        )

    # Auch mit dem *richtigen* Passwort ist jetzt Schluss.
    response = anon_client.post(
        "/auth/login",
        json={"username": ADMIN_USERNAME, "password": ADMIN_PASSWORD},
    )

    assert response.status_code == 429
    assert "Fehlversuche" in response.json()["detail"]


def test_another_ip_is_not_locked_out_by_someone_elses_failures(anon_client):
    for _ in range(10):
        anon_client.post(
            "/auth/login",
            json={"username": ADMIN_USERNAME, "password": "falsch"},
            headers={"X-Real-IP": "10.0.0.1"},
        )

    response = anon_client.post(
        "/auth/login",
        json={"username": ADMIN_USERNAME, "password": ADMIN_PASSWORD},
        headers={"X-Real-IP": "10.0.0.2"},
    )

    assert response.status_code == 200


def test_a_successful_login_clears_the_failure_counter(anon_client):
    for _ in range(3):
        anon_client.post(
            "/auth/login", json={"username": ADMIN_USERNAME, "password": "falsch"}
        )

    anon_client.post(
        "/auth/login",
        json={"username": ADMIN_USERNAME, "password": ADMIN_PASSWORD},
    )

    with db.connect() as conn:
        assert conn.execute("SELECT * FROM login_attempts").fetchall() == []


def test_a_deactivated_account_cannot_log_in(client, make_user):
    user_client, body = make_user("stefan", pages=[Page.KANBAN])
    password = body["initial_password"]

    client.patch(f"/auth/users/{body['user']['id']}", json={"active": False})

    fresh = TestClient(app_instance())
    response = fresh.post(
        "/auth/login", json={"username": "stefan", "password": password}
    )

    assert response.status_code == 401


# --------------------------------------------------------------------------
# Sitzungen
# --------------------------------------------------------------------------


def test_logout_deletes_the_row_not_just_the_cookie(client):
    """ASVS 7.4.1 — ein zurückgespieltes Cookie darf nicht wieder gelten."""
    token = client.cookies["session"]

    assert client.post("/auth/logout").status_code == 204

    with db.connect() as conn:
        assert conn.execute("SELECT * FROM sessions").fetchall() == []

    client.cookies.set("session", token)
    assert client.get("/auth/me").status_code == 401


def test_an_expired_session_is_rejected_and_removed(client):
    """Die absolute Höchstdauer (ASVS 7.3.2), hier per Datenbank vorgealtert."""
    with db.connect() as conn:
        with db.transaction(conn):
            conn.execute(
                "UPDATE sessions SET expires_at = ?",
                (db.to_text(db.now() - db.timedelta(minutes=1)),),
            )

    assert client.get("/auth/me").status_code == 401

    with db.connect() as conn:
        assert conn.execute("SELECT * FROM sessions").fetchall() == []


def test_an_idle_session_is_rejected(client):
    """Die Inaktivitätsgrenze (ASVS 7.3.1) — getrennt von der Höchstdauer."""
    stale = db.to_text(db.now() - db.timedelta(hours=9))

    with db.connect() as conn:
        with db.transaction(conn):
            conn.execute("UPDATE sessions SET last_seen_at = ?", (stale,))

    assert client.get("/auth/me").status_code == 401


def test_last_seen_is_not_written_on_every_request(client):
    """Sonst wäre jeder Request ein Schreibvorgang.

    Der Kanban-Poll läuft alle zehn Sekunden — das hielte SQLite dauerhaft im
    Schreiblock.
    """
    with db.connect() as conn:
        before = conn.execute("SELECT last_seen_at FROM sessions").fetchone()[0]

    for _ in range(5):
        client.get("/auth/me")

    with db.connect() as conn:
        after = conn.execute("SELECT last_seen_at FROM sessions").fetchone()[0]

    assert before == after


def test_a_user_sees_their_own_sessions_and_can_end_the_others(client):
    """ASVS 7.5.2 — sichtbar und widerrufbar, das trägt die unbegrenzte Zahl."""
    second = TestClient(app_instance())
    second.post(
        "/auth/login",
        json={"username": ADMIN_USERNAME, "password": ADMIN_PASSWORD},
    )

    sessions = client.get("/auth/sessions").json()
    assert len(sessions) == 2
    assert sum(1 for entry in sessions if entry["current"]) == 1

    remaining = client.post("/auth/sessions/revoke-others").json()
    assert len(remaining) == 1
    assert remaining[0]["current"] is True

    assert second.get("/auth/me").status_code == 401


def test_the_session_list_drops_sessions_that_are_only_idle_expired(client):
    """Eine tote Sitzung darf nicht als aktiv in der Liste stehen (ASVS 7.5.2).

    Aufgefallen im Livetest: durch Inaktivität verfallene Sitzungen wurden zwar
    korrekt abgewiesen, aber nicht aufgeräumt — nur die absolut abgelaufenen.
    """
    second = TestClient(app_instance())
    second.post(
        "/auth/login",
        json={"username": ADMIN_USERNAME, "password": ADMIN_PASSWORD},
    )
    assert len(client.get("/auth/sessions").json()) == 2

    # Die eigene Kennung *vor* dem Oeffnen der Verbindung holen: ein
    # HTTP-Aufruf innerhalb der Schreibtransaktion laeuft in "database is
    # locked" – die Anwendung wuerde auf sich selbst warten.
    mine = next(
        entry["id"] for entry in client.get("/auth/sessions").json() if entry["current"]
    )

    # Nur die zweite vergammeln lassen, die eigene bleibt frisch.
    stale = db.to_text(db.now() - db.timedelta(hours=9))
    with db.connect() as conn:
        with db.transaction(conn):
            conn.execute(
                "UPDATE sessions SET last_seen_at = ? WHERE token_hash != ?",
                (stale, mine),
            )

    remaining = client.get("/auth/sessions").json()

    assert len(remaining) == 1
    assert remaining[0]["current"] is True


def test_one_user_cannot_end_another_users_session(client, make_user):
    user_client, _ = make_user("nadja", pages=[Page.KANBAN])
    foreign = client.get("/auth/sessions").json()[0]["id"]

    response = user_client.delete(f"/auth/sessions/{foreign}")

    assert response.status_code == 404
    assert client.get("/auth/me").status_code == 200


# --------------------------------------------------------------------------
# Passwortwechsel
# --------------------------------------------------------------------------


def test_changing_the_password_requires_the_current_one(client):
    """ASVS 6.2.3 — zugleich die Re-Authentifizierung aus 7.5.1."""
    response = client.post(
        "/auth/password",
        json={"current_password": "falsch", "new_password": GOOD_PASSWORD},
    )

    assert response.status_code == 401


def test_changing_the_password_ends_all_other_sessions(client):
    """ASVS 7.4.3 — sonst bliebe ein übernommener Zugang bestehen."""
    second = TestClient(app_instance())
    second.post(
        "/auth/login",
        json={"username": ADMIN_USERNAME, "password": ADMIN_PASSWORD},
    )
    assert second.get("/auth/me").status_code == 200

    response = client.post(
        "/auth/password",
        json={"current_password": ADMIN_PASSWORD, "new_password": GOOD_PASSWORD},
    )

    assert response.status_code == 204
    assert second.get("/auth/me").status_code == 401
    # Die eigene Sitzung überlebt.
    assert client.get("/auth/me").status_code == 200


@pytest.mark.parametrize(
    "password, expected",
    [
        ("kurz", "mindestens"),
        ("a" * (MIN_PASSWORD_LENGTH - 1), "mindestens"),
        ("CouplingMedia-2026-XX", "coupling"),
        ("willkommen2026", "mindestens"),
    ],
)
def test_the_password_policy_rejects_with_a_reason(client, password, expected):
    response = client.post(
        "/auth/password",
        json={"current_password": ADMIN_PASSWORD, "new_password": password},
    )

    assert response.status_code == 400
    assert expected.casefold() in response.json()["detail"].casefold()


def test_a_password_may_contain_anything_it_likes(client):
    """ASVS 6.2.5 — keine Regeln zu Zeichenklassen, auch nicht wohlmeinend."""
    response = client.post(
        "/auth/password",
        json={
            "current_password": ADMIN_PASSWORD,
            "new_password": "nur kleinbuchstaben und leerzeichen",
        },
    )

    assert response.status_code == 204


def test_a_password_is_stored_exactly_as_received(anon_client, client):
    """ASVS 6.2.8 — kein strip(), kein Kürzen. Randleerzeichen zählen mit."""
    padded = "  Randleerzeichen Zaehlen Mit  "
    assert (
        client.post(
            "/auth/password",
            json={"current_password": ADMIN_PASSWORD, "new_password": padded},
        ).status_code
        == 204
    )

    fresh = TestClient(app_instance())
    assert (
        fresh.post(
            "/auth/login", json={"username": ADMIN_USERNAME, "password": padded.strip()}
        ).status_code
        == 401
    )
    assert (
        fresh.post(
            "/auth/login", json={"username": ADMIN_USERNAME, "password": padded}
        ).status_code
        == 200
    )


# --------------------------------------------------------------------------
# Zweiter Faktor
# --------------------------------------------------------------------------


def _code_for_next_step(secret: str) -> str:
    """Code des *nächsten* Zeitschritts.

    Die Bestätigung bei der Einrichtung verbraucht den aktuellen Schritt
    (ASVS 6.5.1), eine Anmeldung in derselben 30-Sekunden-Scheibe scheitert
    also — das ist so gewollt. Im Betrieb vergehen zwischen Einrichtung und
    nächster Anmeldung ohnehin mehr als 30 Sekunden; das Driftfenster von
    ±1 Schritt akzeptiert diesen Code bereits jetzt.
    """
    totp = pyotp.TOTP(secret)
    return totp.generate_otp(totp.timecode(datetime.now(timezone.utc)) + 1)


def _enable_totp(client) -> tuple[str, list[str]]:
    setup = client.post("/auth/totp/setup").json()
    secret = setup["secret"]
    assert setup["qr_code_data_uri"].startswith("data:image/png;base64,")

    confirmed = client.post(
        "/auth/totp/confirm",
        json={
            "secret": secret,
            "code": pyotp.TOTP(secret).now(),
            "current_password": ADMIN_PASSWORD,
        },
    )
    assert confirmed.status_code == 200, confirmed.text

    return secret, confirmed.json()["recovery_codes"]


def test_totp_is_only_active_after_a_confirmed_code(client):
    """Sonst sperrt sich aus, wer den QR-Code nicht scannen konnte."""
    client.post("/auth/totp/setup")

    assert client.get("/auth/me").json()["totp_enabled"] is False


def test_a_wrong_code_does_not_activate_the_second_factor(client):
    secret = client.post("/auth/totp/setup").json()["secret"]

    response = client.post(
        "/auth/totp/confirm",
        json={"secret": secret, "code": "000000", "current_password": ADMIN_PASSWORD},
    )

    assert response.status_code == 401
    assert client.get("/auth/me").json()["totp_enabled"] is False


def test_activating_the_second_factor_needs_the_password(client):
    """ASVS 7.5.1 — Re-Authentifizierung vor Aenderung eines Faktors.

    Ohne diese Pruefung koennte jemand mit einer uebernommenen Sitzung den
    zweiten Faktor auf sein eigenes Geraet umhaengen, ohne das Passwort zu
    kennen, und waere danach schwerer aus dem Konto zu bekommen als der
    rechtmaessige Besitzer.
    """
    secret = client.post("/auth/totp/setup").json()["secret"]

    response = client.post(
        "/auth/totp/confirm",
        json={
            "secret": secret,
            "code": pyotp.TOTP(secret).now(),
            "current_password": "falsches-passwort",
        },
    )

    assert response.status_code == 401
    assert client.get("/auth/me").json()["totp_enabled"] is False


def test_replacing_an_existing_second_factor_also_needs_the_password(client):
    """Der eigentlich gefaehrliche Fall: nicht Einrichten, sondern Umhaengen."""
    _enable_totp(client)
    fresh_secret = client.post("/auth/totp/setup").json()["secret"]

    response = client.post(
        "/auth/totp/confirm",
        json={
            "secret": fresh_secret,
            "code": pyotp.TOTP(fresh_secret).now(),
            "current_password": "falsches-passwort",
        },
    )

    assert response.status_code == 401


def test_with_totp_the_password_alone_is_not_enough(client):
    secret, _ = _enable_totp(client)

    fresh = TestClient(app_instance())
    response = fresh.post(
        "/auth/login",
        json={"username": ADMIN_USERNAME, "password": ADMIN_PASSWORD},
    )

    assert response.status_code == 401
    assert response.json()["detail"]["totp_required"] is True

    with_code = fresh.post(
        "/auth/login",
        json={
            "username": ADMIN_USERNAME,
            "password": ADMIN_PASSWORD,
            "totp_code": _code_for_next_step(secret),
        },
    )
    assert with_code.status_code == 200, with_code.text


def test_a_totp_code_works_exactly_once(client):
    """ASVS 6.5.1 — sonst ist ein abgefangener Code 30 Sekunden lang gültig."""
    secret, _ = _enable_totp(client)
    code = _code_for_next_step(secret)

    first = TestClient(app_instance())
    assert (
        first.post(
            "/auth/login",
            json={
                "username": ADMIN_USERNAME,
                "password": ADMIN_PASSWORD,
                "totp_code": code,
            },
        ).status_code
        == 200
    )

    second = TestClient(app_instance())
    replay = second.post(
        "/auth/login",
        json={
            "username": ADMIN_USERNAME,
            "password": ADMIN_PASSWORD,
            "totp_code": code,
        },
    )

    assert replay.status_code == 401


def test_a_recovery_code_works_once_and_is_then_spent(client):
    _, codes = _enable_totp(client)

    first = TestClient(app_instance())
    assert (
        first.post(
            "/auth/login",
            json={
                "username": ADMIN_USERNAME,
                "password": ADMIN_PASSWORD,
                "recovery_code": codes[0],
            },
        ).status_code
        == 200
    )

    second = TestClient(app_instance())
    assert (
        second.post(
            "/auth/login",
            json={
                "username": ADMIN_USERNAME,
                "password": ADMIN_PASSWORD,
                "recovery_code": codes[0],
            },
        ).status_code
        == 401
    )


def test_recovery_codes_are_hashed_at_rest(client):
    """ASVS 6.5.2 — unter 112 Bit Entropie gehört ein Passwort-Hash darüber."""
    _, codes = _enable_totp(client)

    with db.connect() as conn:
        stored = [
            row["code_hash"] for row in conn.execute("SELECT * FROM recovery_codes")
        ]

    assert len(stored) == len(codes)
    for code in codes:
        assert code not in stored
    for entry in stored:
        assert entry.startswith("$argon2")


def test_disabling_the_second_factor_needs_the_password(client):
    """ASVS 7.5.1 — Re-Authentifizierung vor Änderung eines Faktors."""
    _enable_totp(client)

    assert (
        client.post(
            "/auth/totp/disable",
            json={"current_password": "falsch", "new_password": "x"},
        ).status_code
        == 401
    )

    assert (
        client.post(
            "/auth/totp/disable",
            json={"current_password": ADMIN_PASSWORD, "new_password": "x"},
        ).status_code
        == 204
    )
    assert client.get("/auth/me").json()["totp_enabled"] is False


# --------------------------------------------------------------------------
# Kontenverwaltung
# --------------------------------------------------------------------------


def test_a_new_account_gets_a_generated_password_it_must_change(client):
    """ASVS 6.4.1 — der Administrator tippt nie selbst eins ein."""
    response = client.post("/auth/users", json={"username": "pia", "pages": ["kanban"]})

    assert response.status_code == 201
    body = response.json()
    assert len(body["initial_password"]) >= MIN_PASSWORD_LENGTH
    assert body["user"]["must_change_password"] is True


def test_usernames_are_unique_regardless_of_case_and_umlauts(client):
    """Dieselbe Falle wie bei den Kanban-Labels: NOCASE faltet nur ASCII."""
    assert client.post("/auth/users", json={"username": "Jörg"}).status_code == 201

    response = client.post("/auth/users", json={"username": "jörg"})

    assert response.status_code == 409
    assert "vergeben" in response.json()["detail"]


@pytest.mark.parametrize("name", ["admin", "root", "Administrator"])
def test_default_account_names_are_refused(client, name):
    """ASVS 6.3.2 — keine Standardkonten, auch nicht selbst angelegte."""
    response = client.post("/auth/users", json={"username": name})

    assert response.status_code == 400


def test_the_last_active_admin_cannot_lock_everyone_out(client):
    """Der Klassiker, den man sich sonst genau einmal einfängt."""
    admins = [user for user in client.get("/auth/users").json() if user["is_admin"]]
    assert len(admins) == 1
    only_admin = admins[0]["id"]

    for payload in ({"is_admin": False}, {"active": False}):
        response = client.patch(f"/auth/users/{only_admin}", json=payload)
        assert response.status_code == 409, payload
        assert "Administrator" in response.json()["detail"]

    assert client.delete(f"/auth/users/{only_admin}").status_code == 409


def test_a_second_admin_makes_the_first_one_removable(client, make_user):
    """Die Sperre gilt nur dem *letzten* aktiven Administrator."""
    second_client, created = make_user("zweite.chefin", is_admin=True)

    admins = [user for user in client.get("/auth/users").json() if user["is_admin"]]
    assert len(admins) == 2

    first = next(user for user in admins if user["username"] == ADMIN_USERNAME)
    assert (
        client.patch(f"/auth/users/{first['id']}", json={"active": False}).status_code
        == 200
    )

    # Sich selbst zu deaktivieren beendet die eigene Sitzung sofort — der alte
    # Client ist ab hier draussen, weitergearbeitet wird mit dem neuen.
    assert client.get("/auth/me").status_code == 401

    # Und der Neue ist jetzt der letzte, den es zu schuetzen gilt.
    assert (
        second_client.patch(
            f"/auth/users/{created['user']['id']}", json={"is_admin": False}
        ).status_code
        == 409
    )


def test_deactivating_an_account_ends_its_sessions_immediately(client, make_user):
    """ASVS 7.4.2 — der Cascade deckt nur das Löschen ab."""
    user_client, body = make_user("timo", pages=[Page.KANBAN])
    assert user_client.get("/auth/me").status_code == 200

    client.patch(f"/auth/users/{body['user']['id']}", json={"active": False})

    assert user_client.get("/auth/me").status_code == 401


def test_deleting_an_account_takes_its_sessions_and_rights_with_it(client, make_user):
    user_client, body = make_user("olaf", pages=[Page.KANBAN])
    user_id = body["user"]["id"]

    assert client.delete(f"/auth/users/{user_id}").status_code == 204

    assert user_client.get("/auth/me").status_code == 401
    with db.connect() as conn:
        assert db.pages_of(conn, user_id) == set()
        assert db.sessions_of(conn, user_id) == []


def test_an_admin_can_throw_a_single_account_out(client, make_user):
    """ASVS 7.4.5 — der Notaus, wenn ein Notebook wegkommt."""
    user_client, body = make_user("ruth", pages=[Page.KANBAN])

    response = client.post(f"/auth/users/{body['user']['id']}/sessions/revoke")

    assert response.status_code == 200
    assert user_client.get("/auth/me").status_code == 401


def test_an_admin_can_throw_everyone_out_including_themselves(client, make_user):
    user_client, _ = make_user("gerd", pages=[Page.KANBAN])

    assert client.post("/auth/sessions/revoke-all").status_code == 204

    assert user_client.get("/auth/me").status_code == 401
    assert client.get("/auth/me").status_code == 401


def test_resetting_a_password_forces_a_change_and_ends_sessions(client, make_user):
    user_client, body = make_user("bea", pages=[Page.KANBAN])

    reset = client.post(f"/auth/users/{body['user']['id']}/password").json()

    assert reset["user"]["must_change_password"] is True
    assert user_client.get("/auth/me").status_code == 401

    fresh = TestClient(app_instance())
    assert (
        fresh.post(
            "/auth/login",
            json={"username": "bea", "password": reset["initial_password"]},
        ).status_code
        == 200
    )


def test_resetting_the_second_factor_clears_the_recovery_codes(client):
    _enable_totp(client)
    me = client.get("/auth/me").json()

    response = client.post(f"/auth/users/{me['id']}/totp/reset")

    assert response.status_code == 200
    assert response.json()["totp_enabled"] is False
    with db.connect() as conn:
        assert db.unused_recovery_codes(conn, me["id"]) == []


def test_page_rights_are_replaced_not_merged(client, make_user):
    user_client, body = make_user("carla", pages=[Page.KANBAN, Page.QR_CODE])
    user_id = body["user"]["id"]

    client.put(f"/auth/users/{user_id}/pages", json={"pages": ["qr-code"]})

    assert user_client.get("/kanban/board").status_code == 403
    assert user_client.get("/auth/me").json()["pages"] == ["qr-code"]
