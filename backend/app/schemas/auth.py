"""DTOs für Anmeldung, Konten und Sitzungen.

Passwörter erscheinen ausschließlich als Eingabefeld, nie in einer Antwort —
die einzige Ausnahme ist das einmalig angezeigte Startpasswort in
`CreatedUserResponse` und `PasswordResetResponse`.
"""

from pydantic import BaseModel, Field

from app.core.security import MAX_PASSWORD_LENGTH, MAX_USERNAME_LENGTH
from app.schemas.access import Page

# Eingabelänge großzügig über der Richtlinie: zu kurz oder zu lang wird mit
# einer verständlichen deutschen Meldung abgelehnt, nicht mit einem rohen 422.
_MAX_INPUT = MAX_PASSWORD_LENGTH + 1


class LoginRequest(BaseModel):
    username: str = Field(max_length=MAX_USERNAME_LENGTH + 1)
    password: str = Field(max_length=_MAX_INPUT)
    # Beide optional: der erste Versuch kommt ohne. Ist ein zweiter Faktor
    # eingerichtet, antwortet der Server mit `totp_required` und das Frontend
    # schickt denselben Aufruf noch einmal mit Code. Bewusst keine
    # halb-authentifizierte Zwischensitzung.
    totp_code: str | None = Field(default=None, max_length=16)
    recovery_code: str | None = Field(default=None, max_length=64)


class LoginChallenge(BaseModel):
    """Antwort, wenn Benutzername und Passwort stimmen, aber der Code fehlt."""

    totp_required: bool = True
    detail: str


class PasswordChangeRequest(BaseModel):
    """ASVS 6.2.3: der Wechsel verlangt immer auch das aktuelle Passwort."""

    current_password: str = Field(max_length=_MAX_INPUT)
    new_password: str = Field(max_length=_MAX_INPUT)


class SessionInfo(BaseModel):
    """Eine aktive Sitzung, wie sie der Anwender selbst sieht (ASVS 7.5.2)."""

    id: str
    created_at: str
    last_seen_at: str
    expires_at: str
    user_agent: str
    ip: str
    current: bool


class UserSummary(BaseModel):
    """Ein Konto in der Verwaltungsliste."""

    id: str
    username: str
    is_admin: bool
    active: bool
    must_change_password: bool
    totp_enabled: bool
    pages: list[Page]
    created_at: str
    password_changed_at: str
    session_count: int


class UserCreateRequest(BaseModel):
    username: str = Field(max_length=MAX_USERNAME_LENGTH + 1)
    is_admin: bool = False
    pages: list[Page] = Field(default_factory=list)


class CreatedUserResponse(BaseModel):
    """Das Startpasswort wird genau einmal angezeigt (ASVS 6.4.1)."""

    user: UserSummary
    initial_password: str


class UserUpdateRequest(BaseModel):
    """Alle Felder optional — gesetzt wird nur, was mitkommt."""

    username: str | None = Field(default=None, max_length=MAX_USERNAME_LENGTH + 1)
    is_admin: bool | None = None
    active: bool | None = None


class UserPagesRequest(BaseModel):
    pages: list[Page]


class PasswordResetResponse(BaseModel):
    user: UserSummary
    initial_password: str


class TotpSetupResponse(BaseModel):
    """Einrichtung des zweiten Faktors — Seed und QR-Code."""

    secret: str
    provisioning_uri: str
    # PNG als data:-URI, lokal erzeugt. Der Seed verlässt den Server nur hier.
    qr_code_data_uri: str


class TotpConfirmRequest(BaseModel):
    # Der Seed kommt aus `/auth/totp/setup` zurueck und wird hier wieder
    # eingereicht — bewusst im Body und nicht als Query-Parameter, sonst
    # stuende er im Zugriffslog jedes Proxys davor.
    secret: str = Field(max_length=64)
    code: str = Field(max_length=16)
    # ASVS 7.5.1 verlangt eine Re-Authentifizierung, *bevor* ein
    # Authentifizierungsmerkmal geaendert wird. Ohne das koennte jemand mit
    # einer uebernommenen Sitzung den zweiten Faktor auf sein eigenes Geraet
    # umhaengen, ohne das Passwort zu kennen — und waere danach der
    # rechtmaessige Besitzer des Kontos.
    current_password: str = Field(max_length=_MAX_INPUT)


class TotpConfirmResponse(BaseModel):
    """Die Wiederherstellungscodes werden genau einmal angezeigt."""

    recovery_codes: list[str]


class RecoveryCodeStatus(BaseModel):
    total: int
    unused: int
