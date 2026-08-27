"""Anmeldung, Sitzungen und Kontenverwaltung.

Die HTTP-Schicht (`api/auth_api.py`) setzt nur Cookies und übersetzt Fehler in
Statuscodes; alle Entscheidungen fallen hier. `core/auth_db.py` hält das SQL,
`core/security.py` die Kryptografie.

**Hier wird nichts geloggt.** Passwörter, Token und TOTP-Codes dürfen in keiner
Logzeile erscheinen.

Verfahren, Zahlen und Begründungen: `docs/authentifizierung.md`.
"""

import base64
import os
from dataclasses import dataclass
from datetime import timedelta

from app.core import auth_db as db
from app.core.qr_utils import QUIET_ZONE_MODULES, build_matrix, matrix_to_png
from app.core.security import (
    PasswordPolicyError,
    UsernameError,
    check_password_policy,
    check_username,
    generate_password,
    hash_secret,
    needs_rehash,
    new_recovery_codes,
    new_session_token,
    new_totp_secret,
    normalise_recovery_code,
    token_fingerprint,
    totp_provisioning_uri,
    username_key,
    verify_secret,
    verify_totp,
)
from app.schemas.access import CurrentUserResponse, Page
from app.schemas.auth import (
    LoginRequest,
    SessionInfo,
    TotpSetupResponse,
    UserSummary,
)

# --------------------------------------------------------------------------
# Konfiguration
# --------------------------------------------------------------------------


def _hours(name: str, default: int) -> timedelta:
    return timedelta(hours=int(os.getenv(name, str(default))))


def _minutes(name: str, default: int) -> timedelta:
    return timedelta(minutes=int(os.getenv(name, str(default))))


def idle_timeout() -> timedelta:
    """Inaktivitätsgrenze (ASVS 7.3.1). Begründung: docs, Abschnitt 4."""
    return _hours("SESSION_IDLE_HOURS", 8)


def absolute_timeout() -> timedelta:
    """Absolute Höchstdauer einer Sitzung (ASVS 7.3.2)."""
    return _hours("SESSION_ABSOLUTE_HOURS", 24)


def lockout_threshold() -> int:
    return int(os.getenv("LOGIN_LOCKOUT_THRESHOLD", "10"))


def lockout_window() -> timedelta:
    return _minutes("LOGIN_LOCKOUT_WINDOW_MINUTES", 15)


def lockout_duration() -> timedelta:
    return _minutes("LOGIN_LOCKOUT_MINUTES", 15)


# Wie alt `last_seen_at` sein darf, bevor es neu geschrieben wird. Ohne diese
# Schwelle wäre jeder Request ein Schreibvorgang — der 10-Sekunden-Poll des
# Kanban-Boards hielte die Datenbank dann dauerhaft im Schreiblock.
TOUCH_INTERVAL = timedelta(minutes=5)


# --------------------------------------------------------------------------
# Fehler
# --------------------------------------------------------------------------


class AuthError(Exception):
    """Basisklasse. Meldungen sind für Anwender bestimmt."""


class AuthNotFoundError(AuthError):
    """Konto oder Sitzung existiert nicht → 404."""


class AuthConflictError(AuthError):
    """Name vergeben, letzter Administrator, o. ä. → 409."""


class InvalidCredentialsError(AuthError):
    """Anmeldung gescheitert → 401. Bewusst ohne Angabe, was falsch war."""


class TotpRequiredError(AuthError):
    """Passwort stimmt, zweiter Faktor fehlt → 401 mit Marker."""


class LockedOutError(AuthError):
    """Zu viele Fehlversuche → 429."""


class ForbiddenError(AuthError):
    """Vorgang für diesen Aufrufer nicht erlaubt → 403."""


# Einheitliche Meldung für alles, was bei der Anmeldung schiefgehen kann.
# „Benutzer unbekannt" und „Passwort falsch" dürfen nicht unterscheidbar sein.
_GENERIC_LOGIN_ERROR = "Benutzername oder Passwort ist falsch."


# --------------------------------------------------------------------------
# Ergebnis einer Sitzungsauflösung
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class ResolvedSession:
    user_id: str
    username: str
    is_admin: bool
    must_change_password: bool
    totp_enabled: bool
    pages: frozenset[Page]
    token_hash: str


def _pages_of_row(conn, row) -> frozenset[Page]:
    """Rechte eines Kontos. Administratoren sehen immer alles."""
    if row["is_admin"]:
        return frozenset(Page)

    known = {page.value for page in Page}
    return frozenset(
        Page(value) for value in db.pages_of(conn, row["id"]) if value in known
    )


def _summary(conn, row, pages: set[str] | None = None) -> UserSummary:
    granted = pages if pages is not None else db.pages_of(conn, row["id"])
    known = {page.value for page in Page}
    sessions = db.sessions_of(conn, row["id"])

    return UserSummary(
        id=row["id"],
        username=row["username"],
        is_admin=bool(row["is_admin"]),
        active=bool(row["active"]),
        must_change_password=bool(row["must_change_password"]),
        totp_enabled=row["totp_secret"] is not None,
        pages=[Page(value) for value in sorted(granted) if value in known],
        created_at=row["created_at"],
        password_changed_at=row["password_changed_at"],
        session_count=len(sessions),
    )


def current_user_response(session: ResolvedSession) -> CurrentUserResponse:
    return CurrentUserResponse(
        id=session.user_id,
        username=session.username,
        is_admin=session.is_admin,
        must_change_password=session.must_change_password,
        totp_enabled=session.totp_enabled,
        # Katalogreihenfolge statt der (ungeordneten) Menge, damit die Antwort
        # zwischen zwei Aufrufen stabil ist.
        pages=[page for page in Page if page in session.pages],
    )


# --------------------------------------------------------------------------
# Anmeldung
# --------------------------------------------------------------------------


def login(
    request: LoginRequest, *, ip: str, user_agent: str
) -> tuple[str, ResolvedSession]:
    """Prüft Zugangsdaten und legt eine Sitzung an.

    Gibt das Klartext-Token zurück — es existiert genau hier und im Cookie des
    Aufrufers, gespeichert wird nur sein SHA-256.
    """
    key = username_key(request.username)
    ip_key = ip or "unbekannt"

    with db.connect() as conn:
        until = db.locked_until(conn, ip_key, key)
        if until is not None:
            raise LockedOutError(
                "Zu viele Fehlversuche. Bitte in einigen Minuten erneut versuchen."
            )

        row = db.user_by_key(conn, key)

        # Auch ohne Treffer wird verifiziert (gegen einen Dummy-Hash), damit
        # die Antwortzeit kein Benutzerverzeichnis ist.
        stored = row["password_hash"] if row is not None else None
        password_ok = verify_secret(stored, request.password)

        if row is None or not password_ok or not row["active"]:
            with db.transaction(conn):
                db.record_failure(
                    conn,
                    ip_key,
                    key,
                    window=lockout_window(),
                    threshold=lockout_threshold(),
                    lock_for=lockout_duration(),
                )
            raise InvalidCredentialsError(_GENERIC_LOGIN_ERROR)

        # Zweiter Faktor, falls eingerichtet.
        if row["totp_secret"] is not None:
            accepted_step = _check_second_factor(conn, row, request)
            if accepted_step is None:
                with db.transaction(conn):
                    db.record_failure(
                        conn,
                        ip_key,
                        key,
                        window=lockout_window(),
                        threshold=lockout_threshold(),
                        lock_for=lockout_duration(),
                    )
                if not request.totp_code and not request.recovery_code:
                    raise TotpRequiredError(
                        "Bitte den Code aus der Authenticator-App eingeben."
                    )
                raise InvalidCredentialsError("Der Code ist nicht gültig.")

        token = new_session_token()
        fingerprint = token_fingerprint(token)

        with db.transaction(conn):
            db.clear_failures(conn, ip_key, key)

            # Argon2-Parameter angehoben? Dann wandert das Passwort jetzt mit.
            if needs_rehash(row["password_hash"]):
                db.update_user_fields(
                    conn, row["id"], password_hash=hash_secret(request.password)
                )

            db.insert_session(
                conn,
                token_hash=fingerprint,
                user_id=row["id"],
                expires_at=db.now() + absolute_timeout(),
                user_agent=user_agent[:200],
                ip=ip_key[:64],
            )
            db.delete_stale_sessions(conn, db.now() - idle_timeout())

            row = db.user_by_id(conn, row["id"])

        resolved = ResolvedSession(
            user_id=row["id"],
            username=row["username"],
            is_admin=bool(row["is_admin"]),
            must_change_password=bool(row["must_change_password"]),
            totp_enabled=row["totp_secret"] is not None,
            pages=_pages_of_row(conn, row),
            token_hash=fingerprint,
        )

    return token, resolved


def _check_second_factor(conn, row, request: LoginRequest) -> int | bool | None:
    """Prüft TOTP oder Wiederherstellungscode. `None` heißt abgelehnt."""
    if request.totp_code:
        step = verify_totp(
            row["totp_secret"],
            request.totp_code,
            last_step=row["totp_last_step"],
        )
        if step is None:
            return None

        # Verbrauchten Zeitschritt festhalten (ASVS 6.5.1): derselbe Code darf
        # innerhalb seines 30-Sekunden-Fensters kein zweites Mal funktionieren.
        with db.transaction(conn):
            db.update_user_fields(conn, row["id"], totp_last_step=step)
        return step

    if request.recovery_code:
        candidate = normalise_recovery_code(request.recovery_code)
        for entry in db.unused_recovery_codes(conn, row["id"]):
            if verify_secret(entry["code_hash"], candidate):
                with db.transaction(conn):
                    db.consume_recovery_code(conn, row["id"], entry["code_hash"])
                return True
        return None

    return None


def logout(token: str | None) -> None:
    """Beendet die Sitzung. Die Zeile wird gelöscht, nicht nur das Cookie."""
    if not token:
        return

    with db.connect() as conn:
        with db.transaction(conn):
            db.delete_session(conn, token_fingerprint(token))


# --------------------------------------------------------------------------
# Sitzungsauflösung
# --------------------------------------------------------------------------


def resolve_session(token: str | None) -> ResolvedSession | None:
    """Löst ein Cookie in einen Benutzer auf, oder gibt None zurück.

    Fail closed: jeder Zweifel führt hier zu None, nie zu einem Benutzer.
    Prüft beide Grenzen aus ASVS 7.3 — Inaktivität und Höchstdauer.
    """
    if not token:
        return None

    fingerprint = token_fingerprint(token)

    with db.connect() as conn:
        session = db.session_by_hash(conn, fingerprint)
        if session is None:
            return None

        moment = db.now()

        if db.from_text(session["expires_at"]) <= moment:
            with db.transaction(conn):
                db.delete_session(conn, fingerprint)
            return None

        last_seen = db.from_text(session["last_seen_at"])
        if last_seen + idle_timeout() <= moment:
            with db.transaction(conn):
                db.delete_session(conn, fingerprint)
            return None

        row = db.user_by_id(conn, session["user_id"])
        if row is None or not row["active"]:
            # Deaktiviert, während die Sitzung lief (ASVS 7.4.2).
            with db.transaction(conn):
                db.delete_sessions_of(conn, session["user_id"])
            return None

        if last_seen + TOUCH_INTERVAL <= moment:
            with db.transaction(conn):
                db.touch_session(conn, fingerprint, moment)

        return ResolvedSession(
            user_id=row["id"],
            username=row["username"],
            is_admin=bool(row["is_admin"]),
            must_change_password=bool(row["must_change_password"]),
            totp_enabled=row["totp_secret"] is not None,
            pages=_pages_of_row(conn, row),
            token_hash=fingerprint,
        )


# --------------------------------------------------------------------------
# Eigenes Konto
# --------------------------------------------------------------------------


def change_own_password(
    session: ResolvedSession, current_password: str, new_password: str
) -> None:
    """Passwortwechsel (ASVS 6.2.3, 7.4.3, 7.5.1).

    Verlangt das aktuelle Passwort — das ist zugleich die geforderte
    Re-Authentifizierung — und beendet danach alle übrigen Sitzungen.
    """
    with db.connect() as conn:
        row = db.user_by_id(conn, session.user_id)
        if row is None:
            raise AuthNotFoundError("Konto nicht gefunden.")

        if not verify_secret(row["password_hash"], current_password):
            raise InvalidCredentialsError("Das aktuelle Passwort ist falsch.")

        if current_password == new_password:
            raise AuthError("Das neue Passwort muss sich vom bisherigen unterscheiden.")

        try:
            check_password_policy(new_password, username=row["username"])
        except PasswordPolicyError as exc:
            raise AuthError(str(exc)) from exc

        with db.transaction(conn):
            db.set_password(conn, row["id"], hash_secret(new_password))
            db.delete_sessions_of(conn, row["id"], keep_token_hash=session.token_hash)


def own_sessions(session: ResolvedSession) -> list[SessionInfo]:
    """Alle eigenen Sitzungen (ASVS 7.5.2)."""
    with db.connect() as conn:
        with db.transaction(conn):
            db.delete_stale_sessions(conn, db.now() - idle_timeout())

        return [
            SessionInfo(
                # Der Hash ist die Kennung — das Klartext-Token kennt nur der
                # Browser, der die Sitzung besitzt.
                id=row["token_hash"],
                created_at=row["created_at"],
                last_seen_at=row["last_seen_at"],
                expires_at=row["expires_at"],
                user_agent=row["user_agent"],
                ip=row["ip"],
                current=row["token_hash"] == session.token_hash,
            )
            for row in db.sessions_of(conn, session.user_id)
        ]


def revoke_own_session(session: ResolvedSession, token_hash: str) -> None:
    with db.connect() as conn:
        row = db.session_by_hash(conn, token_hash)
        if row is None or row["user_id"] != session.user_id:
            raise AuthNotFoundError("Diese Sitzung gibt es nicht.")

        with db.transaction(conn):
            db.delete_session(conn, token_hash)


def revoke_other_own_sessions(session: ResolvedSession) -> int:
    with db.connect() as conn:
        with db.transaction(conn):
            return db.delete_sessions_of(
                conn, session.user_id, keep_token_hash=session.token_hash
            )


# --------------------------------------------------------------------------
# Zweiter Faktor
# --------------------------------------------------------------------------


def begin_totp_setup(session: ResolvedSession) -> TotpSetupResponse:
    """Erzeugt einen Seed und den QR-Code dazu — noch nicht aktiviert.

    Aktiv wird der Faktor erst, wenn ein gültiger Code bestätigt wurde. Sonst
    sperrt sich aus, wer den QR-Code nicht scannen konnte.
    """
    secret = new_totp_secret()
    uri = totp_provisioning_uri(secret, session.username)

    # Mit Ruhezone: der Standardrand des QR-Generators ist 0, weil die Codes
    # dort in ein Layout eingebettet werden. Dieser hier wird direkt vom
    # Bildschirm abfotografiert und muss allein scannen.
    png = matrix_to_png(build_matrix(uri, border=QUIET_ZONE_MODULES))
    encoded = base64.b64encode(png).decode("ascii")

    return TotpSetupResponse(
        secret=secret,
        provisioning_uri=uri,
        qr_code_data_uri=f"data:image/png;base64,{encoded}",
    )


def confirm_totp_setup(
    session: ResolvedSession, secret: str, code: str, password: str
) -> list[str]:
    """Aktiviert den zweiten Faktor und gibt die Wiederherstellungscodes zurück.

    Verlangt zusätzlich das eigene Passwort (ASVS 7.5.1). Das ist nicht
    Zeremonie: ohne die Prüfung könnte jemand mit einer übernommenen Sitzung
    den zweiten Faktor auf sein eigenes Gerät umhängen, ohne das Passwort zu
    kennen — und wäre danach der schwerer zu vertreibende Besitzer des Kontos.
    Gilt für die Ersteinrichtung genauso wie für einen Wechsel.
    """
    with db.connect() as conn:
        row = db.user_by_id(conn, session.user_id)
        if row is None:
            raise AuthNotFoundError("Konto nicht gefunden.")

        if not verify_secret(row["password_hash"], password):
            raise InvalidCredentialsError("Das Passwort ist falsch.")

    step = verify_totp(secret, code, last_step=None)
    if step is None:
        raise InvalidCredentialsError(
            "Der Code stimmt nicht. Stimmt die Uhrzeit auf dem Telefon?"
        )

    codes = new_recovery_codes()

    with db.connect() as conn:
        with db.transaction(conn):
            db.update_user_fields(
                conn, session.user_id, totp_secret=secret, totp_last_step=step
            )
            db.replace_recovery_codes(
                conn, session.user_id, [hash_secret(code) for code in codes]
            )

    return codes


def disable_own_totp(session: ResolvedSession, password: str) -> None:
    """Zweiten Faktor entfernen — nur gegen das eigene Passwort (ASVS 7.5.1)."""
    with db.connect() as conn:
        row = db.user_by_id(conn, session.user_id)
        if row is None:
            raise AuthNotFoundError("Konto nicht gefunden.")

        if not verify_secret(row["password_hash"], password):
            raise InvalidCredentialsError("Das Passwort ist falsch.")

        with db.transaction(conn):
            db.update_user_fields(
                conn, session.user_id, totp_secret=None, totp_last_step=None
            )
            db.delete_recovery_codes(conn, session.user_id)


def recovery_code_status(session: ResolvedSession) -> tuple[int, int]:
    with db.connect() as conn:
        unused = len(db.unused_recovery_codes(conn, session.user_id))
        total = len(
            conn.execute(
                "SELECT 1 FROM recovery_codes WHERE user_id = ?",
                (session.user_id,),
            ).fetchall()
        )
    return total, unused


# --------------------------------------------------------------------------
# Kontenverwaltung (nur Administratoren)
# --------------------------------------------------------------------------


def list_users() -> list[UserSummary]:
    with db.connect() as conn:
        by_user = db.pages_of_all(conn)
        return [
            _summary(conn, row, by_user.get(row["id"], set()))
            for row in db.all_users(conn)
        ]


def _validated_pages(pages) -> set[str]:
    return {page.value if isinstance(page, Page) else str(page) for page in pages}


def create_user(username: str, *, is_admin: bool, pages) -> tuple[UserSummary, str]:
    """Legt ein Konto an und erzeugt das Startpasswort selbst (ASVS 6.4.1)."""
    try:
        display = check_username(username)
    except UsernameError as exc:
        raise AuthError(str(exc)) from exc

    key = username_key(display)
    initial = generate_password()

    with db.connect() as conn:
        if db.user_by_key(conn, key) is not None:
            raise AuthConflictError(f"„{display}“ ist bereits vergeben.")

        user_id = db.new_id()
        with db.transaction(conn):
            db.insert_user(
                conn,
                user_id=user_id,
                username=display,
                key=key,
                password_hash=hash_secret(initial),
                is_admin=is_admin,
                must_change_password=True,
            )
            db.replace_pages(conn, user_id, _validated_pages(pages))

        row = db.user_by_id(conn, user_id)
        return _summary(conn, row), initial


def update_user(
    user_id: str,
    *,
    actor: ResolvedSession,
    username: str | None,
    is_admin: bool | None,
    active: bool | None,
) -> UserSummary:
    with db.connect() as conn:
        row = db.user_by_id(conn, user_id)
        if row is None:
            raise AuthNotFoundError("Konto nicht gefunden.")

        fields: dict[str, object] = {}

        if username is not None and username_key(username) != row["username_key"]:
            try:
                display = check_username(username)
            except UsernameError as exc:
                raise AuthError(str(exc)) from exc

            key = username_key(display)
            if db.user_by_key(conn, key) is not None:
                raise AuthConflictError(f"„{display}“ ist bereits vergeben.")

            fields["username"] = display
            fields["username_key"] = key

        # Der letzte aktive Administrator darf sich nicht selbst entfernen.
        losing_admin = is_admin is False and row["is_admin"]
        losing_active = active is False and row["active"]

        if (losing_admin or losing_active) and row["is_admin"] and row["active"]:
            if db.active_admin_count(conn, excluding=user_id) == 0:
                raise AuthConflictError(
                    "Das ist der letzte aktive Administrator — sonst kommt niemand "
                    "mehr in die Benutzerverwaltung."
                )

        if is_admin is not None:
            fields["is_admin"] = int(is_admin)
        if active is not None:
            fields["active"] = int(active)

        with db.transaction(conn):
            db.update_user_fields(conn, user_id, **fields)

            # Deaktivieren beendet sofort alle Sitzungen (ASVS 7.4.2).
            if losing_active:
                db.delete_sessions_of(conn, user_id)

        return _summary(conn, db.user_by_id(conn, user_id))


def set_user_pages(user_id: str, pages) -> UserSummary:
    with db.connect() as conn:
        if db.user_by_id(conn, user_id) is None:
            raise AuthNotFoundError("Konto nicht gefunden.")

        with db.transaction(conn):
            db.replace_pages(conn, user_id, _validated_pages(pages))

        return _summary(conn, db.user_by_id(conn, user_id))


def reset_user_password(user_id: str) -> tuple[UserSummary, str]:
    """Setzt ein neues Startpasswort und erzwingt den Wechsel."""
    initial = generate_password()

    with db.connect() as conn:
        row = db.user_by_id(conn, user_id)
        if row is None:
            raise AuthNotFoundError("Konto nicht gefunden.")

        with db.transaction(conn):
            db.set_password(conn, user_id, hash_secret(initial))
            db.update_user_fields(conn, user_id, must_change_password=1)
            # Ein zurückgesetztes Passwort beendet alle Sitzungen — sonst
            # bliebe jemand angemeldet, dem gerade der Zugang entzogen wird.
            db.delete_sessions_of(conn, user_id)

        return _summary(conn, db.user_by_id(conn, user_id)), initial


def reset_user_totp(user_id: str) -> UserSummary:
    """Zweiten Faktor zurücksetzen (ASVS 6.4.4 — Prüfung erfolgt persönlich)."""
    with db.connect() as conn:
        if db.user_by_id(conn, user_id) is None:
            raise AuthNotFoundError("Konto nicht gefunden.")

        with db.transaction(conn):
            db.update_user_fields(conn, user_id, totp_secret=None, totp_last_step=None)
            db.delete_recovery_codes(conn, user_id)
            db.delete_sessions_of(conn, user_id)

        return _summary(conn, db.user_by_id(conn, user_id))


def delete_user(user_id: str, *, actor: ResolvedSession) -> None:
    with db.connect() as conn:
        row = db.user_by_id(conn, user_id)
        if row is None:
            raise AuthNotFoundError("Konto nicht gefunden.")

        if row["id"] == actor.user_id:
            raise AuthConflictError("Das eigene Konto lässt sich nicht löschen.")

        if row["is_admin"] and row["active"]:
            if db.active_admin_count(conn, excluding=user_id) == 0:
                raise AuthConflictError("Das ist der letzte aktive Administrator.")

        with db.transaction(conn):
            db.delete_user(conn, user_id)


def revoke_user_sessions(user_id: str) -> int:
    """Alle Sitzungen eines Kontos beenden (ASVS 7.4.5)."""
    with db.connect() as conn:
        if db.user_by_id(conn, user_id) is None:
            raise AuthNotFoundError("Konto nicht gefunden.")

        with db.transaction(conn):
            return db.delete_sessions_of(conn, user_id)


def revoke_all_sessions() -> int:
    """Alle Sitzungen aller Konten beenden — der Notaus (ASVS 7.4.5)."""
    with db.connect() as conn:
        with db.transaction(conn):
            return db.delete_all_sessions(conn)


# --------------------------------------------------------------------------
# Erststart
# --------------------------------------------------------------------------


class MissingAdminCredentialsError(RuntimeError):
    """Kein Konto vorhanden und keine Zugangsdaten gesetzt — Start verweigern."""


def ensure_admin() -> None:
    """Legt beim ersten Start den Administrator an (ASVS 6.3.2, 6.4.1).

    `ADMIN_PASSWORD` wirkt **nur beim Anlegen**: sonst würde jeder Neustart ein
    im UI geändertes Passwort überschreiben.

    Existiert noch kein Konto und fehlen die Variablen, verweigert die
    Anwendung den Start. Ein Container, der ohne Zugangsdaten hochkommt, ist
    eine Anwendung, in die niemand mehr hineinkommt — das fällt lieber im
    Deploy auf als später.
    """
    with db.connect() as conn:
        if db.any_user_exists(conn):
            return

        username = os.getenv("ADMIN_USERNAME", "").strip()
        password = os.getenv("ADMIN_PASSWORD", "")

        if not username or not password:
            raise MissingAdminCredentialsError(
                "Es existiert noch kein Benutzerkonto und ADMIN_USERNAME/"
                "ADMIN_PASSWORD sind nicht gesetzt. Ohne beides käme die "
                "Anwendung ohne Zugang hoch. Siehe README, Abschnitt Deployment."
            )

        try:
            display = check_username(username)
        except UsernameError as exc:
            raise MissingAdminCredentialsError(
                f"ADMIN_USERNAME ist unzulässig: {exc}"
            ) from exc

        try:
            check_password_policy(password, username=display)
        except PasswordPolicyError as exc:
            raise MissingAdminCredentialsError(
                f"ADMIN_PASSWORD erfüllt die Richtlinie nicht: {exc}"
            ) from exc

        with db.transaction(conn):
            db.insert_user(
                conn,
                user_id=db.new_id(),
                username=display,
                key=username_key(display),
                password_hash=hash_secret(password),
                is_admin=True,
                must_change_password=False,
            )


def reset_password_from_cli(username: str) -> str:
    """Notausgang für ein vergessenes Administratorpasswort.

    Aufruf: `docker compose exec backend python -m app.admin_cli reset <name>`
    """
    key = username_key(username)

    with db.connect() as conn:
        row = db.user_by_key(conn, key)
        if row is None:
            raise AuthNotFoundError(f"Kein Konto mit dem Namen „{username}“.")

    _, initial = reset_user_password(row["id"])
    return initial
