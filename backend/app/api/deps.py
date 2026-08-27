"""Wer ruft auf, und welche Bereiche darf er öffnen.

Die einzige Stelle, an der aus einem Request ein Benutzer wird. Jeder
Feature-Router hängt über `require_page(...)` daran, die Kontenverwaltung über
`require_admin`. `tests/test_access.py` läuft die Routentabelle ab und lässt
eine Route nur durch, wenn sie einen der beiden Guards trägt oder namentlich in
`PUBLIC_PATHS` steht — eine ungeschützte Route ist ein fehlschlagender Test,
keine stille Lücke.

**Fail closed:** kein Zweig hier darf bei einem Fehler einen Benutzer
zurückgeben. Im Zweifel 401.

Verfahren und Zahlen: `docs/authentifizierung.md`.
"""

import os
from dataclasses import dataclass

from fastapi import Depends, HTTPException, Request

from app.schemas.access import Page
from app.services.auth_service import ResolvedSession, resolve_session


def cookie_name() -> str:
    """Name des Sitzungscookies.

    In Produktion `__Host-session`: das Präfix erzwingt `Secure` und verbietet
    ein `Domain`-Attribut, wodurch keine Subdomain das Cookie setzen kann.
    Lokal läuft die Anwendung über http, wo `Secure` es unbrauchbar machen
    würde — deshalb kommt der Name aus der Umgebung.
    """
    return os.getenv("SESSION_COOKIE_NAME", "__Host-session")


def cookie_secure() -> bool:
    return os.getenv("SESSION_COOKIE_SECURE", "1") != "0"


@dataclass(frozen=True)
class CurrentUser:
    """Der Aufrufer, wie ihn die Anwendung kennt."""

    id: str
    username: str
    is_admin: bool
    must_change_password: bool
    pages: frozenset[Page]
    session: ResolvedSession

    def may_see(self, page: Page) -> bool:
        return page in self.pages


def _unauthenticated() -> HTTPException:
    return HTTPException(status_code=401, detail="Nicht angemeldet.")


def current_user(request: Request) -> CurrentUser:
    """Löst das Sitzungscookie in einen Benutzer auf, oder wirft 401.

    Liest das Cookie über `request.cookies` statt über `Cookie(...)`, weil der
    Name in Produktion `__Host-session` lautet und damit kein gültiger
    Python-Bezeichner ist.
    """
    token = request.cookies.get(cookie_name())
    session = resolve_session(token)

    if session is None:
        raise _unauthenticated()

    return CurrentUser(
        id=session.user_id,
        username=session.username,
        is_admin=session.is_admin,
        must_change_password=session.must_change_password,
        pages=session.pages,
        session=session,
    )


def optional_user(request: Request) -> CurrentUser | None:
    """Wie `current_user`, aber ohne 401 — für `/auth/me`."""
    try:
        return current_user(request)
    except HTTPException:
        return None


def require_page(page: Page):
    """Baut den Guard, hinter dem ein Router eingehängt wird.

    Als Dependency am Router statt als Prüfung in den Handlern, damit ein neuer
    Endpunkt auf einem bestehenden Router in dem Moment abgedeckt ist, in dem
    er geschrieben wird. Das Attribut `guards_page` ist, wonach
    `tests/test_access.py` die Routentabelle durchsucht.
    """

    def guard(user: CurrentUser = Depends(current_user)) -> CurrentUser:
        # Ein Startpasswort darf kein Dauerpasswort werden (ASVS 6.4.1). Der
        # Router-Guard setzt das durch, nicht nur das Frontend: dort wäre es
        # Kosmetik, hier ist es die Grenze.
        if user.must_change_password:
            raise HTTPException(
                status_code=403,
                detail="Bitte zuerst das Passwort ändern.",
            )

        if not user.may_see(page):
            raise HTTPException(
                status_code=403,
                detail="Für diesen Bereich fehlt die Berechtigung.",
            )

        return user

    guard.guards_page = page

    return guard


def require_admin(user: CurrentUser = Depends(current_user)) -> CurrentUser:
    """Guard für die Kontenverwaltung.

    Hängt am Administratorflag, nicht an einer Seite — deshalb das eigene
    Attribut `requires_admin`, das derselbe Test wie `guards_page` akzeptiert.
    Ohne das müsste man die Verwaltungsendpunkte in `PUBLIC_PATHS` eintragen
    und würde den Test damit stumpf machen.
    """
    if not user.is_admin:
        raise HTTPException(
            status_code=403,
            detail="Dieser Bereich ist Administratoren vorbehalten.",
        )

    return user


require_admin.requires_admin = True


def client_ip(request: Request) -> str:
    """IP des Aufrufers, für die Sperrzählung.

    nginx setzt `X-Real-IP` selbst, ein Client kann ihn nicht fälschen, und der
    Backend-Port ist in Produktion nicht veröffentlicht. Fehlt der Header
    (lokal über den Vite-Proxy), zählt die Adresse der Verbindung.
    """
    forwarded = request.headers.get("x-real-ip", "").strip()
    if forwarded:
        return forwarded[:64]

    return (request.client.host if request.client else "unbekannt")[:64]


def user_agent(request: Request) -> str:
    """Für die Sitzungsliste — reine Anzeige, nie eine Entscheidungsgrundlage."""
    return request.headers.get("user-agent", "")[:200]


__all__ = [
    "CurrentUser",
    "client_ip",
    "cookie_name",
    "cookie_secure",
    "current_user",
    "optional_user",
    "require_admin",
    "require_page",
    "user_agent",
]
