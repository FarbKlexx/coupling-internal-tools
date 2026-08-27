"""Kryptografische Primitive und die Passwortrichtlinie.

Hier liegt alles, was mit Geheimnissen rechnet — Hashing, Tokenerzeugung,
Prüfung der Passwortrichtlinie, TOTP. Der Rest der Anwendung ruft diese
Funktionen auf und kennt weder Argon2 noch die Parameter dahinter.

**In diesem Modul wird nichts geloggt.** Weder Passwörter noch Token noch
TOTP-Codes dürfen in eine Logzeile geraten — dieselbe Regel wie im PDF-Schutz.

Verfahren und Begründungen: `docs/authentifizierung.md`, Abschnitt 6.
"""

import hashlib
import hmac
import re
import secrets
import unicodedata
from pathlib import Path

import pyotp
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

# --------------------------------------------------------------------------
# Passwort-Hashing
# --------------------------------------------------------------------------

# OWASP-Minimum für Argon2id (Password Storage Cheat Sheet): 19 MiB Speicher,
# zwei Durchläufe, ein Grad Parallelität. Explizit gesetzt statt geerbt, damit
# im Review sichtbar ist, wogegen gehasht wird.
ARGON2_MEMORY_KIB = 19456
ARGON2_TIME_COST = 2
ARGON2_PARALLELISM = 1
ARGON2_HASH_LEN = 32
ARGON2_SALT_LEN = 16

_hasher = PasswordHasher(
    memory_cost=ARGON2_MEMORY_KIB,
    time_cost=ARGON2_TIME_COST,
    parallelism=ARGON2_PARALLELISM,
    hash_len=ARGON2_HASH_LEN,
    salt_len=ARGON2_SALT_LEN,
)

# Gegen diesen Hash wird verifiziert, wenn es den Benutzer gar nicht gibt.
# Ohne das wäre die Antwortzeit ein Benutzerverzeichnis: "existiert nicht"
# käme messbar schneller zurück als "falsches Passwort".
_DUMMY_HASH = _hasher.hash("dummy-password-for-constant-time-comparison")


def hash_secret(secret: str) -> str:
    """Argon2id-Hash eines Passworts oder Wiederherstellungscodes."""
    return _hasher.hash(secret)


def verify_secret(stored_hash: str | None, secret: str) -> bool:
    """Prüft ein Geheimnis gegen seinen Hash.

    `stored_hash=None` (Benutzer existiert nicht) verifiziert trotzdem gegen
    den Dummy-Hash und gibt dann False zurück — der Aufrufer soll sich nicht
    darum kümmern müssen, dass die Laufzeit gleich bleibt.
    """
    candidate = stored_hash or _DUMMY_HASH

    try:
        _hasher.verify(candidate, secret)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False

    return stored_hash is not None


def needs_rehash(stored_hash: str) -> bool:
    """Ob der Hash mit veralteten Parametern erzeugt wurde.

    Beim Anmelden geprüft: werden die Parameter oben später angehoben, wandern
    bestehende Passwörter bei der nächsten Anmeldung automatisch mit.
    """
    try:
        return _hasher.check_needs_rehash(stored_hash)
    except InvalidHashError:
        return True


# --------------------------------------------------------------------------
# Token
# --------------------------------------------------------------------------

# 32 Byte = 256 Bit. ASVS 7.2.3 verlangt mindestens 128.
TOKEN_BYTES = 32


def new_session_token() -> str:
    """Neues Sitzungstoken aus dem CSPRNG."""
    return secrets.token_urlsafe(TOKEN_BYTES)


def token_fingerprint(token: str) -> str:
    """Was von einem Token in der Datenbank landet.

    SHA-256 genügt hier, wo für Passwörter Argon2 nötig ist: das Token hat
    volle Entropie, es gibt kein Wörterbuch dagegen. Eine kopierte
    Datenbankdatei liefert damit keine nutzbaren Sitzungen.
    """
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def tokens_equal(left: str, right: str) -> bool:
    """Vergleich in konstanter Zeit."""
    return hmac.compare_digest(left, right)


# --------------------------------------------------------------------------
# Passwortrichtlinie
# --------------------------------------------------------------------------

MIN_PASSWORD_LENGTH = 15
# Keine Sicherheits-, sondern eine Verfügbarkeitsgrenze: Argon2 hasht die
# Eingabe vollständig, ein Megabyte-Passwort wäre ein billiger DoS.
MAX_PASSWORD_LENGTH = 256

_WORDLIST_DIR = Path(__file__).resolve().parent.parent / "assets" / "wordlists"


def _load_wordlist(name: str) -> frozenset[str]:
    """Liest eine Wortliste; Kommentare und Leerzeilen fallen raus."""
    path = _WORDLIST_DIR / name
    words = set()

    for line in path.read_text(encoding="utf-8").splitlines():
        entry = line.strip()
        if entry and not entry.startswith("#"):
            words.add(entry.casefold())

    return frozenset(words)


COMMON_PASSWORDS = _load_wordlist("common_passwords.txt")
CONTEXT_WORDS = _load_wordlist("context_words.txt")

# Dieselbe Menge, aber in fester Reihenfolge: das längste Wort zuerst. Die
# Prüfung unten nennt das erste Wort, das sie findet, und „CouplingMedia2026"
# enthält zwei — über die Menge iteriert hing es am Hash-Seed des Prozesses,
# ob die Meldung „coupling" oder „media" nannte. Das längste ist das
# aussagekräftigste, und die Meldung ist damit reproduzierbar.
_CONTEXT_WORDS_BY_SPECIFICITY = tuple(
    sorted(CONTEXT_WORDS, key=lambda word: (-len(word), word))
)


class PasswordPolicyError(ValueError):
    """Das Passwort verstößt gegen die Richtlinie. Meldung ist für Anwender."""


def check_password_policy(password: str, *, username: str = "") -> None:
    """Prüft ein neues Passwort. Wirft `PasswordPolicyError` mit Begründung.

    Bewusst *ohne* Regeln zu Zeichenklassen — ASVS 6.2.5 verbietet sie, weil
    sie Passwörter nachweislich schlechter machen. Geprüft wird Länge und ob
    das Passwort erraten wäre.
    """
    if len(password) < MIN_PASSWORD_LENGTH:
        raise PasswordPolicyError(
            f"Das Passwort muss mindestens {MIN_PASSWORD_LENGTH} Zeichen lang sein."
        )

    if len(password) > MAX_PASSWORD_LENGTH:
        raise PasswordPolicyError(
            f"Das Passwort darf höchstens {MAX_PASSWORD_LENGTH} Zeichen lang sein."
        )

    folded = password.casefold()

    if folded in COMMON_PASSWORDS:
        raise PasswordPolicyError(
            "Dieses Passwort ist zu bekannt. Bitte ein anderes wählen."
        )

    # Teilzeichenkette, nicht Gleichheit: "CouplingMedia2026!" soll fallen.
    for word in _CONTEXT_WORDS_BY_SPECIFICITY:
        if word in folded:
            raise PasswordPolicyError(
                f"Das Passwort darf „{word}“ nicht enthalten — Begriffe aus dem "
                "Umfeld dieser Anwendung sind die ersten Rateversuche."
            )

    if username:
        name = username.casefold().strip()
        if len(name) >= 3 and name in folded:
            raise PasswordPolicyError(
                "Das Passwort darf den Benutzernamen nicht enthalten."
            )


# Ohne mehrdeutige Zeichen (0/O, 1/l/I): Startpasswörter werden vorgelesen
# oder abgetippt.
_GENERATED_ALPHABET = "abcdefghijkmnpqrstuvwxyzABCDEFGHJKLMNPQRSTUVWXYZ23456789"


def generate_password(length: int = 20) -> str:
    """Zufälliges Startpasswort (ASVS 6.4.1).

    Ein Administrator tippt nie selbst eins ein. Der Wert wird genau einmal
    angezeigt und muss bei der ersten Anmeldung gewechselt werden.
    """
    if length < MIN_PASSWORD_LENGTH:
        length = MIN_PASSWORD_LENGTH

    while True:
        candidate = "".join(secrets.choice(_GENERATED_ALPHABET) for _ in range(length))
        try:
            check_password_policy(candidate)
        except PasswordPolicyError:  # pragma: no cover - astronomisch selten
            continue

        return candidate


# --------------------------------------------------------------------------
# Benutzernamen
# --------------------------------------------------------------------------

MAX_USERNAME_LENGTH = 60
MIN_USERNAME_LENGTH = 2

# Keine Standardkonten (ASVS 6.3.2).
RESERVED_USERNAMES = frozenset({"admin", "root", "administrator", "sa", "test"})

_USERNAME_ALLOWED = re.compile(r"^[\w.@ -]+$", re.UNICODE)


class UsernameError(ValueError):
    """Der Benutzername ist unzulässig. Meldung ist für Anwender."""


def username_key(username: str) -> str:
    """Normalisierte Form für die Eindeutigkeitsprüfung.

    Nicht `COLLATE NOCASE`: SQLites eingebautes NOCASE faltet nur ASCII A-Z,
    "Jörg" und "jörg" wären damit zwei Konten. Dieselbe Falle wie bei den
    Kanban-Labels, siehe `kanban_db.name_key`.

    Zusätzlich NFKC: sonst sind zwei optisch identische Namen mit
    unterschiedlicher Unicode-Komposition verschiedene Konten.
    """
    collapsed = " ".join(username.split())
    return unicodedata.normalize("NFKC", collapsed).casefold()


def check_username(username: str) -> str:
    """Prüft und normalisiert einen Benutzernamen. Gibt die Anzeigeform zurück."""
    display = " ".join(username.split())

    if len(display) < MIN_USERNAME_LENGTH:
        raise UsernameError("Der Benutzername ist zu kurz.")

    if len(display) > MAX_USERNAME_LENGTH:
        raise UsernameError(
            f"Der Benutzername darf höchstens {MAX_USERNAME_LENGTH} Zeichen lang sein."
        )

    if not _USERNAME_ALLOWED.match(display):
        raise UsernameError(
            "Erlaubt sind Buchstaben, Ziffern, Punkt, Leerzeichen, Bindestrich, "
            "Unterstrich und @."
        )

    if username_key(display) in RESERVED_USERNAMES:
        raise UsernameError(
            f"„{display}“ ist als Benutzername nicht zulässig — Standardkonten "
            "wie dieses sind ein bekanntes Angriffsziel."
        )

    return display


# --------------------------------------------------------------------------
# Zweiter Faktor
# --------------------------------------------------------------------------

TOTP_INTERVAL_SECONDS = 30
# Eine Schrittweite Toleranz in jede Richtung gegen Uhrendrift. Mehr würde das
# Zeitfenster für einen abgefangenen Code unnötig verbreitern.
TOTP_DRIFT_STEPS = 1

TOTP_ISSUER = "Coupling Internal Tools"

RECOVERY_CODE_COUNT = 10
# 20 Base32-Zeichen = 100 Bit. ASVS 6.5.4 verlangt mindestens 20 Bit.
RECOVERY_CODE_BYTES = 13


def new_totp_secret() -> str:
    """Neuer TOTP-Seed. `pyotp` nutzt dafür `secrets` (ASVS 6.5.3)."""
    return pyotp.random_base32()


def totp_provisioning_uri(secret: str, username: str) -> str:
    """`otpauth://`-URI für den Einrichtungs-QR-Code."""
    return pyotp.TOTP(secret, interval=TOTP_INTERVAL_SECONDS).provisioning_uri(
        name=username, issuer_name=TOTP_ISSUER
    )


def verify_totp(secret: str, code: str, *, last_step: int | None) -> int | None:
    """Prüft einen TOTP-Code und gibt den akzeptierten Zeitschritt zurück.

    `None` heißt abgelehnt. Der Zeitschritt muss vom Aufrufer gespeichert und
    beim nächsten Mal wieder hereingereicht werden: ASVS 6.5.1 verlangt, dass
    ein Code genau einmal funktioniert. Ohne das ist ein abgefangener Code
    innerhalb seines 30-Sekunden-Fensters beliebig oft einlösbar.
    """
    cleaned = code.strip().replace(" ", "")
    if not cleaned.isdigit():
        return None

    totp = pyotp.TOTP(secret, interval=TOTP_INTERVAL_SECONDS)
    now = totp.timecode(_now())

    for offset in range(-TOTP_DRIFT_STEPS, TOTP_DRIFT_STEPS + 1):
        step = now + offset
        if last_step is not None and step <= last_step:
            # Bereits verbraucht (oder älter als der letzte akzeptierte).
            continue

        if hmac.compare_digest(totp.generate_otp(step), cleaned):
            return step

    return None


def _now():
    """Aktuelle Zeit — als Funktion, damit Tests sie ersetzen können."""
    import datetime

    return datetime.datetime.now(datetime.timezone.utc)


def new_recovery_codes() -> list[str]:
    """Wiederherstellungscodes im Klartext. Werden nur einmal angezeigt."""
    return [
        secrets.token_hex(RECOVERY_CODE_BYTES).upper()
        for _ in range(RECOVERY_CODE_COUNT)
    ]


def normalise_recovery_code(code: str) -> str:
    """Vergleichsform: ohne Leerzeichen und Bindestriche, Großbuchstaben."""
    return code.strip().replace(" ", "").replace("-", "").upper()
