"""HTTP-Schicht der Authentifizierung.

Setzt Cookies, übersetzt Fehler in Statuscodes — mehr nicht. Alle
Entscheidungen fallen in `services/auth_service.py`.

Ohne Guard sind nur die vier Endpunkte, die in `tests/test_access.py` unter
`PUBLIC_PATHS` stehen: `/auth/login` und `/auth/logout` (der Einstieg selbst)
sowie `/auth/me` (antwortet selbst mit 401, wenn niemand angemeldet ist).
Alles unter `/auth/users` hängt an `require_admin`, der Rest an einer Sitzung.

**Hier wird nichts geloggt.** Kein Passwort, kein Token, kein TOTP-Code darf in
eine Logzeile geraten.
"""

from fastapi import APIRouter, Depends, HTTPException, Request, Response

from app.api.deps import (
    CurrentUser,
    client_ip,
    cookie_name,
    cookie_secure,
    current_user,
    optional_user,
    require_admin,
    user_agent,
)
from app.schemas.access import CurrentUserResponse, Page
from app.schemas.auth import (
    CreatedUserResponse,
    LoginRequest,
    PasswordChangeRequest,
    PasswordResetResponse,
    RecoveryCodeStatus,
    SessionInfo,
    TotpConfirmRequest,
    TotpConfirmResponse,
    TotpSetupResponse,
    UserCreateRequest,
    UserPagesRequest,
    UserSummary,
    UserUpdateRequest,
)
from app.services import auth_service as service
from app.services.auth_service import (
    AuthConflictError,
    AuthError,
    AuthNotFoundError,
    InvalidCredentialsError,
    LockedOutError,
    TotpRequiredError,
)

router = APIRouter(prefix="/auth", tags=["auth"])


def _fail(exc: AuthError) -> HTTPException:
    """Bildet einen Servicefehler auf seinen Statuscode ab.

    Reihenfolge zählt — alle Spezialfälle erben von `AuthError`.
    """
    if isinstance(exc, AuthNotFoundError):
        status = 404
    elif isinstance(exc, AuthConflictError):
        status = 409
    elif isinstance(exc, LockedOutError):
        status = 429
    elif isinstance(exc, (InvalidCredentialsError, TotpRequiredError)):
        status = 401
    else:
        status = 400

    detail: object = str(exc)
    if isinstance(exc, TotpRequiredError):
        # Marker, damit das Frontend das Codefeld einblenden kann, statt die
        # Meldung zu parsen.
        detail = {"message": str(exc), "totp_required": True}

    return HTTPException(status_code=status, detail=detail)


# --------------------------------------------------------------------------
# Anmeldung
# --------------------------------------------------------------------------


def _set_session_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        key=cookie_name(),
        value=token,
        httponly=True,
        secure=cookie_secure(),
        # Strict statt Lax: schließt CSRF vollständig aus, statt sich darauf zu
        # verlassen, dass keine Zustandsänderung je hinter einem GET liegt.
        # Preis ist eine zusätzliche Anmeldung beim Einstieg über einen
        # Fremdlink — siehe docs/authentifizierung.md, Abschnitt 4.
        samesite="strict",
        path="/",
        max_age=int(service.absolute_timeout().total_seconds()),
    )


@router.post("/login", response_model=CurrentUserResponse)
def login(
    request: LoginRequest,
    response: Response,
    http_request: Request,
) -> CurrentUserResponse:
    """Meldet an und setzt das Sitzungscookie.

    Ist ein zweiter Faktor eingerichtet und fehlt der Code, kommt 401 mit
    `totp_required` zurück und das Frontend schickt denselben Aufruf noch
    einmal mit Code. Bewusst keine halb-authentifizierte Zwischensitzung.
    """
    try:
        token, _ = service.login(
            request,
            ip=client_ip(http_request),
            user_agent=user_agent(http_request),
        )
    except AuthError as exc:
        raise _fail(exc) from exc

    _set_session_cookie(response, token)

    # Frisch auflösen statt das Ergebnis von `login` zu verwenden: so ist die
    # Antwort exakt das, was ein späteres `/auth/me` auch liefern würde.
    session = service.resolve_session(token)
    if session is None:  # pragma: no cover - unmittelbar nach dem Anlegen
        raise HTTPException(
            status_code=500, detail="Sitzung konnte nicht gelesen werden."
        )

    return service.current_user_response(session)


@router.post("/logout", status_code=204)
def logout(response: Response, http_request: Request) -> Response:
    """Beendet die Sitzung. Funktioniert auch mit bereits ungültigem Cookie."""
    service.logout(http_request.cookies.get(cookie_name()))
    response.delete_cookie(
        key=cookie_name(),
        httponly=True,
        secure=cookie_secure(),
        samesite="strict",
        path="/",
    )
    return Response(status_code=204)


@router.get("/me", response_model=CurrentUserResponse)
def read_me(user: CurrentUser | None = Depends(optional_user)) -> CurrentUserResponse:
    """Der Aufrufer und die Bereiche, die er öffnen darf."""
    if user is None:
        raise HTTPException(status_code=401, detail="Nicht angemeldet.")

    return service.current_user_response(user.session)


# --------------------------------------------------------------------------
# Eigenes Konto
# --------------------------------------------------------------------------


@router.post("/password", status_code=204)
def change_password(
    request: PasswordChangeRequest,
    user: CurrentUser = Depends(current_user),
) -> Response:
    """Passwortwechsel. Beendet alle übrigen Sitzungen."""
    try:
        service.change_own_password(
            user.session, request.current_password, request.new_password
        )
    except AuthError as exc:
        raise _fail(exc) from exc

    return Response(status_code=204)


@router.get("/sessions", response_model=list[SessionInfo])
def read_sessions(user: CurrentUser = Depends(current_user)) -> list[SessionInfo]:
    """Alle eigenen Sitzungen (ASVS 7.5.2)."""
    return service.own_sessions(user.session)


@router.delete("/sessions/{token_hash}", response_model=list[SessionInfo])
def revoke_session(
    token_hash: str, user: CurrentUser = Depends(current_user)
) -> list[SessionInfo]:
    try:
        service.revoke_own_session(user.session, token_hash)
    except AuthError as exc:
        raise _fail(exc) from exc

    return service.own_sessions(user.session)


@router.post("/sessions/revoke-others", response_model=list[SessionInfo])
def revoke_other_sessions(
    user: CurrentUser = Depends(current_user),
) -> list[SessionInfo]:
    service.revoke_other_own_sessions(user.session)
    return service.own_sessions(user.session)


# --------------------------------------------------------------------------
# Zweiter Faktor
# --------------------------------------------------------------------------


@router.post("/totp/setup", response_model=TotpSetupResponse)
def start_totp_setup(user: CurrentUser = Depends(current_user)) -> TotpSetupResponse:
    """Erzeugt Seed und QR-Code. Aktiv wird der Faktor erst nach Bestätigung."""
    return service.begin_totp_setup(user.session)


@router.post("/totp/confirm", response_model=TotpConfirmResponse)
def confirm_totp(
    request: TotpConfirmRequest,
    user: CurrentUser = Depends(current_user),
) -> TotpConfirmResponse:
    """Bestätigt die Einrichtung und gibt die Wiederherstellungscodes zurück."""
    try:
        codes = service.confirm_totp_setup(
            user.session, request.secret, request.code, request.current_password
        )
    except AuthError as exc:
        raise _fail(exc) from exc

    return TotpConfirmResponse(recovery_codes=codes)


@router.post("/totp/disable", status_code=204)
def disable_totp(
    request: PasswordChangeRequest,
    user: CurrentUser = Depends(current_user),
) -> Response:
    """Entfernt den zweiten Faktor — nur gegen das eigene Passwort.

    Nutzt `PasswordChangeRequest` wieder und liest nur `current_password`;
    ein eigenes Schema mit einem einzigen Feld wäre hier Zeremonie.
    """
    try:
        service.disable_own_totp(user.session, request.current_password)
    except AuthError as exc:
        raise _fail(exc) from exc

    return Response(status_code=204)


@router.get("/totp/recovery-status", response_model=RecoveryCodeStatus)
def recovery_status(user: CurrentUser = Depends(current_user)) -> RecoveryCodeStatus:
    total, unused = service.recovery_code_status(user.session)
    return RecoveryCodeStatus(total=total, unused=unused)


# --------------------------------------------------------------------------
# Kontenverwaltung — ausschließlich für Administratoren
# --------------------------------------------------------------------------


@router.get("/pages", response_model=list[Page])
def read_pages(_: CurrentUser = Depends(require_admin)) -> list[Page]:
    """Der Katalog aller Berechtigungen — IDs, keine Beschriftungen.

    Die deutschen Beschriftungen stehen in der Route-Meta des Frontends und
    werden hier bewusst nicht wiederholt.
    """
    return list(Page)


@router.get("/users", response_model=list[UserSummary])
def read_users(_: CurrentUser = Depends(require_admin)) -> list[UserSummary]:
    return service.list_users()


@router.post("/users", response_model=CreatedUserResponse, status_code=201)
def add_user(
    request: UserCreateRequest, _: CurrentUser = Depends(require_admin)
) -> CreatedUserResponse:
    """Legt ein Konto an. Das Startpasswort erzeugt der Server."""
    try:
        summary, initial = service.create_user(
            request.username, is_admin=request.is_admin, pages=request.pages
        )
    except AuthError as exc:
        raise _fail(exc) from exc

    return CreatedUserResponse(user=summary, initial_password=initial)


@router.patch("/users/{user_id}", response_model=UserSummary)
def change_user(
    user_id: str,
    request: UserUpdateRequest,
    admin: CurrentUser = Depends(require_admin),
) -> UserSummary:
    try:
        return service.update_user(
            user_id,
            actor=admin.session,
            username=request.username,
            is_admin=request.is_admin,
            active=request.active,
        )
    except AuthError as exc:
        raise _fail(exc) from exc


@router.put("/users/{user_id}/pages", response_model=UserSummary)
def set_pages(
    user_id: str,
    request: UserPagesRequest,
    _: CurrentUser = Depends(require_admin),
) -> UserSummary:
    """Setzt die vollständige Rechtemenge — idempotent, kein Delta."""
    try:
        return service.set_user_pages(user_id, request.pages)
    except AuthError as exc:
        raise _fail(exc) from exc


@router.post("/users/{user_id}/password", response_model=PasswordResetResponse)
def reset_password(
    user_id: str, _: CurrentUser = Depends(require_admin)
) -> PasswordResetResponse:
    """Neues Startpasswort. Erzwingt den Wechsel und beendet alle Sitzungen."""
    try:
        summary, initial = service.reset_user_password(user_id)
    except AuthError as exc:
        raise _fail(exc) from exc

    return PasswordResetResponse(user=summary, initial_password=initial)


@router.post("/users/{user_id}/totp/reset", response_model=UserSummary)
def reset_totp(user_id: str, _: CurrentUser = Depends(require_admin)) -> UserSummary:
    """Zweiten Faktor zurücksetzen — nach persönlicher Prüfung (ASVS 6.4.4)."""
    try:
        return service.reset_user_totp(user_id)
    except AuthError as exc:
        raise _fail(exc) from exc


@router.post("/users/{user_id}/sessions/revoke", response_model=UserSummary)
def revoke_user_sessions(
    user_id: str, _: CurrentUser = Depends(require_admin)
) -> UserSummary:
    """Wirft ein Konto überall hinaus (ASVS 7.4.5)."""
    try:
        service.revoke_user_sessions(user_id)
    except AuthError as exc:
        raise _fail(exc) from exc

    return next(user for user in service.list_users() if user.id == user_id)


@router.post("/sessions/revoke-all", status_code=204)
def revoke_all_sessions(_: CurrentUser = Depends(require_admin)) -> Response:
    """Der Notaus: beendet die Sitzungen aller Konten, auch die eigene."""
    service.revoke_all_sessions()
    return Response(status_code=204)


@router.delete("/users/{user_id}", status_code=204)
def remove_user(user_id: str, admin: CurrentUser = Depends(require_admin)) -> Response:
    try:
        service.delete_user(user_id, actor=admin.session)
    except AuthError as exc:
        raise _fail(exc) from exc

    return Response(status_code=204)
