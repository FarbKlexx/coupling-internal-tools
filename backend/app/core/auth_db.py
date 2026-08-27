"""SQLite-Persistenz für Konten und Sitzungen — das einzige Modul mit SQL dafür.

Bewusst eine eigene Datei neben `kanban.db` statt zusätzlicher Tabellen dort:
die Kanban-Fixture, `/kanban/export` und die Sicherungssemantik bleiben
unangetastet, und `kanban_db.py` bleibt „das Modul mit dem Kanban-SQL".

Wo die Datei liegt: `AUTH_DB_PATH`, standardmäßig **relativ**, damit ein Wert
überall funktioniert — `backend/data/auth.db`, wenn uvicorn aus `backend/`
läuft, und `/app/data/auth.db` im Container (WORKDIR ist `/app`). Das ist
dasselbe gemountete Verzeichnis wie beim Kanban-Board. **Ohne dieses Mount sind
in Produktion alle Konten beim nächsten Image-Rebuild weg.**

Aufbau und Begründungen: `docs/authentifizierung.md`.
"""

import os
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterator

DEFAULT_DB_PATH = "data/auth.db"

BUSY_TIMEOUT_MS = 5000

SCHEMA_VERSION = "1"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id                   TEXT    PRIMARY KEY,
    username             TEXT    NOT NULL,
    username_key         TEXT    NOT NULL UNIQUE,
    password_hash        TEXT    NOT NULL,
    is_admin             INTEGER NOT NULL DEFAULT 0,
    active               INTEGER NOT NULL DEFAULT 1,
    must_change_password INTEGER NOT NULL DEFAULT 0,
    totp_secret          TEXT,
    totp_last_step       INTEGER,
    created_at           TEXT    NOT NULL,
    password_changed_at  TEXT    NOT NULL
);

CREATE TABLE IF NOT EXISTS user_pages (
    user_id TEXT NOT NULL REFERENCES users (id) ON DELETE CASCADE,
    page    TEXT NOT NULL,
    PRIMARY KEY (user_id, page)
);

CREATE TABLE IF NOT EXISTS sessions (
    token_hash   TEXT    PRIMARY KEY,
    user_id      TEXT    NOT NULL REFERENCES users (id) ON DELETE CASCADE,
    created_at   TEXT    NOT NULL,
    expires_at   TEXT    NOT NULL,
    last_seen_at TEXT    NOT NULL,
    user_agent   TEXT    NOT NULL DEFAULT '',
    ip           TEXT    NOT NULL DEFAULT ''
);

CREATE INDEX IF NOT EXISTS idx_sessions_user ON sessions (user_id);

CREATE TABLE IF NOT EXISTS recovery_codes (
    user_id   TEXT NOT NULL REFERENCES users (id) ON DELETE CASCADE,
    code_hash TEXT NOT NULL,
    used_at   TEXT,
    PRIMARY KEY (user_id, code_hash)
);

CREATE TABLE IF NOT EXISTS login_attempts (
    ip_key       TEXT    NOT NULL,
    username_key TEXT    NOT NULL,
    failed_count INTEGER NOT NULL DEFAULT 0,
    first_failed TEXT    NOT NULL,
    locked_until TEXT,
    PRIMARY KEY (ip_key, username_key)
);

CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""


def db_path() -> Path:
    """Pfad *jetzt* auflösen, nicht beim Import — wie in `kanban_db`."""
    return Path(os.getenv("AUTH_DB_PATH", DEFAULT_DB_PATH))


def now() -> datetime:
    return datetime.now(timezone.utc)


def to_text(moment: datetime) -> str:
    """ISO-8601-Text. SQLite hat keinen Datumstyp; so sortiert und vergleicht es."""
    return moment.strftime("%Y-%m-%dT%H:%M:%SZ")


def from_text(text: str) -> datetime:
    return datetime.strptime(text, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)


def now_text() -> str:
    return to_text(now())


def new_id() -> str:
    return str(uuid.uuid4())


@contextmanager
def connect() -> Iterator[sqlite3.Connection]:
    """Eine Verbindung pro Aufruf — `sqlite3`-Verbindungen sind nicht threadsicher."""
    path = db_path()
    if path.parent != Path(""):
        path.parent.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(path, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode = WAL")
    # In SQLite standardmäßig aus. Ohne das ist ON DELETE CASCADE oben
    # Dekoration — und die Sitzung eines gelöschten Kontos bliebe gültig.
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute(f"PRAGMA busy_timeout = {BUSY_TIMEOUT_MS}")

    try:
        yield conn
    finally:
        conn.close()


@contextmanager
def transaction(conn: sqlite3.Connection) -> Iterator[sqlite3.Connection]:
    """Ein Schreibvorgang als ein atomarer Schritt."""
    conn.execute("BEGIN IMMEDIATE")
    try:
        yield conn
    except Exception:
        conn.execute("ROLLBACK")
        raise
    conn.execute("COMMIT")


def init_schema() -> None:
    """Legt die Tabellen an, falls sie fehlen. Idempotent."""
    with connect() as conn:
        conn.executescript(_SCHEMA)
        conn.execute(
            "INSERT OR IGNORE INTO meta (key, value) VALUES ('schema_version', ?)",
            (SCHEMA_VERSION,),
        )


# --------------------------------------------------------------------------
# Konten
# --------------------------------------------------------------------------


def user_by_key(conn: sqlite3.Connection, key: str) -> sqlite3.Row | None:
    return conn.execute("SELECT * FROM users WHERE username_key = ?", (key,)).fetchone()


def user_by_id(conn: sqlite3.Connection, user_id: str) -> sqlite3.Row | None:
    return conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()


def all_users(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return list(conn.execute("SELECT * FROM users ORDER BY username_key").fetchall())


def any_user_exists(conn: sqlite3.Connection) -> bool:
    return conn.execute("SELECT 1 FROM users LIMIT 1").fetchone() is not None


def active_admin_count(conn: sqlite3.Connection, *, excluding: str = "") -> int:
    """Wie viele aktive Administratoren es gibt — ohne den genannten.

    Grundlage der Sperre gegen das Aussperren aller: der letzte aktive
    Administrator darf nicht gelöscht, deaktiviert oder degradiert werden.
    """
    row = conn.execute(
        "SELECT COUNT(*) AS n FROM users"
        " WHERE is_admin = 1 AND active = 1 AND id != ?",
        (excluding,),
    ).fetchone()
    return int(row["n"])


def insert_user(
    conn: sqlite3.Connection,
    *,
    user_id: str,
    username: str,
    key: str,
    password_hash: str,
    is_admin: bool,
    must_change_password: bool,
) -> None:
    timestamp = now_text()
    conn.execute(
        "INSERT INTO users"
        " (id, username, username_key, password_hash, is_admin, active,"
        "  must_change_password, created_at, password_changed_at)"
        " VALUES (?, ?, ?, ?, ?, 1, ?, ?, ?)",
        (
            user_id,
            username,
            key,
            password_hash,
            int(is_admin),
            int(must_change_password),
            timestamp,
            timestamp,
        ),
    )


# Spalten, die `update_user_fields` setzen darf. Die Namen landen per
# String-Interpolation im SQL — heute kommen sie ausschliesslich aus
# literalen Schluesselwortargumenten und sind damit nicht beeinflussbar. Die
# Liste haelt das auch dann so, wenn jemand die Funktion spaeter mit einem
# Dictionary aus einer Anfrage aufruft.
_UPDATABLE_COLUMNS = frozenset(
    {
        "username",
        "username_key",
        "password_hash",
        "is_admin",
        "active",
        "must_change_password",
        "totp_secret",
        "totp_last_step",
    }
)


def update_user_fields(conn: sqlite3.Connection, user_id: str, **fields) -> None:
    """Setzt genannte Spalten. Nur die aus `_UPDATABLE_COLUMNS`."""
    if not fields:
        return

    unknown = set(fields) - _UPDATABLE_COLUMNS
    if unknown:
        raise ValueError(f"Nicht setzbare Spalte(n): {sorted(unknown)}")

    assignments = ", ".join(f"{column} = ?" for column in fields)
    conn.execute(
        f"UPDATE users SET {assignments} WHERE id = ?",
        (*fields.values(), user_id),
    )


def set_password(conn: sqlite3.Connection, user_id: str, password_hash: str) -> None:
    conn.execute(
        "UPDATE users SET password_hash = ?, password_changed_at = ?,"
        " must_change_password = 0 WHERE id = ?",
        (password_hash, now_text(), user_id),
    )


def delete_user(conn: sqlite3.Connection, user_id: str) -> None:
    """Löscht das Konto. Sitzungen, Rechte und Codes gehen per CASCADE mit."""
    conn.execute("DELETE FROM users WHERE id = ?", (user_id,))


# --------------------------------------------------------------------------
# Seitenrechte
# --------------------------------------------------------------------------


def pages_of(conn: sqlite3.Connection, user_id: str) -> set[str]:
    return {
        row["page"]
        for row in conn.execute(
            "SELECT page FROM user_pages WHERE user_id = ?", (user_id,)
        ).fetchall()
    }


def pages_of_all(conn: sqlite3.Connection) -> dict[str, set[str]]:
    """Rechte aller Konten in einem Rutsch — für die Benutzerliste."""
    result: dict[str, set[str]] = {}
    for row in conn.execute("SELECT user_id, page FROM user_pages").fetchall():
        result.setdefault(row["user_id"], set()).add(row["page"])
    return result


def replace_pages(conn: sqlite3.Connection, user_id: str, pages: set[str]) -> None:
    conn.execute("DELETE FROM user_pages WHERE user_id = ?", (user_id,))
    conn.executemany(
        "INSERT INTO user_pages (user_id, page) VALUES (?, ?)",
        [(user_id, page) for page in sorted(pages)],
    )


# --------------------------------------------------------------------------
# Sitzungen
# --------------------------------------------------------------------------


def insert_session(
    conn: sqlite3.Connection,
    *,
    token_hash: str,
    user_id: str,
    expires_at: datetime,
    user_agent: str,
    ip: str,
) -> None:
    timestamp = now_text()
    conn.execute(
        "INSERT INTO sessions"
        " (token_hash, user_id, created_at, expires_at, last_seen_at, user_agent, ip)"
        " VALUES (?, ?, ?, ?, ?, ?, ?)",
        (
            token_hash,
            user_id,
            timestamp,
            to_text(expires_at),
            timestamp,
            user_agent,
            ip,
        ),
    )


def session_by_hash(conn: sqlite3.Connection, token_hash: str) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT * FROM sessions WHERE token_hash = ?", (token_hash,)
    ).fetchone()


def sessions_of(conn: sqlite3.Connection, user_id: str) -> list[sqlite3.Row]:
    return list(
        conn.execute(
            "SELECT * FROM sessions WHERE user_id = ? ORDER BY last_seen_at DESC",
            (user_id,),
        ).fetchall()
    )


def touch_session(conn: sqlite3.Connection, token_hash: str, moment: datetime) -> None:
    conn.execute(
        "UPDATE sessions SET last_seen_at = ? WHERE token_hash = ?",
        (to_text(moment), token_hash),
    )


def delete_session(conn: sqlite3.Connection, token_hash: str) -> None:
    conn.execute("DELETE FROM sessions WHERE token_hash = ?", (token_hash,))


def delete_sessions_of(
    conn: sqlite3.Connection, user_id: str, *, keep_token_hash: str = ""
) -> int:
    """Beendet alle Sitzungen eines Kontos, optional bis auf eine.

    Grundlage für 7.4.2 (Konto deaktiviert oder gelöscht), 7.4.3 (nach
    Passwortwechsel) und 7.4.5 (Administrator wirft jemanden hinaus).
    """
    cursor = conn.execute(
        "DELETE FROM sessions WHERE user_id = ? AND token_hash != ?",
        (user_id, keep_token_hash),
    )
    return cursor.rowcount


def delete_all_sessions(conn: sqlite3.Connection) -> int:
    cursor = conn.execute("DELETE FROM sessions")
    return cursor.rowcount


def delete_stale_sessions(conn: sqlite3.Connection, idle_cutoff: datetime) -> int:
    """Räumt Sitzungen weg, die keine mehr sind.

    Beide Grenzen, nicht nur die absolute: eine durch Inaktivität verfallene
    Sitzung wird beim Nachschlagen ohnehin abgewiesen, stünde aber weiter in
    der Liste unter „Aktive Sitzungen" — und die soll ehrlich sein (ASVS
    7.5.2). Der Schnittpunkt kommt vom Aufrufer, weil die Dauer im Service
    konfiguriert wird.
    """
    cursor = conn.execute(
        "DELETE FROM sessions WHERE expires_at < ? OR last_seen_at < ?",
        (now_text(), to_text(idle_cutoff)),
    )
    return cursor.rowcount


# --------------------------------------------------------------------------
# Wiederherstellungscodes
# --------------------------------------------------------------------------


def replace_recovery_codes(
    conn: sqlite3.Connection, user_id: str, code_hashes: list[str]
) -> None:
    conn.execute("DELETE FROM recovery_codes WHERE user_id = ?", (user_id,))
    conn.executemany(
        "INSERT INTO recovery_codes (user_id, code_hash) VALUES (?, ?)",
        [(user_id, code_hash) for code_hash in code_hashes],
    )


def unused_recovery_codes(conn: sqlite3.Connection, user_id: str) -> list[sqlite3.Row]:
    return list(
        conn.execute(
            "SELECT * FROM recovery_codes WHERE user_id = ? AND used_at IS NULL",
            (user_id,),
        ).fetchall()
    )


def consume_recovery_code(
    conn: sqlite3.Connection, user_id: str, code_hash: str
) -> None:
    conn.execute(
        "UPDATE recovery_codes SET used_at = ? WHERE user_id = ? AND code_hash = ?",
        (now_text(), user_id, code_hash),
    )


def delete_recovery_codes(conn: sqlite3.Connection, user_id: str) -> None:
    conn.execute("DELETE FROM recovery_codes WHERE user_id = ?", (user_id,))


# --------------------------------------------------------------------------
# Fehlversuche und Sperre
# --------------------------------------------------------------------------


def attempt_row(conn: sqlite3.Connection, ip_key: str, key: str) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT * FROM login_attempts WHERE ip_key = ? AND username_key = ?",
        (ip_key, key),
    ).fetchone()


def record_failure(
    conn: sqlite3.Connection,
    ip_key: str,
    key: str,
    *,
    window: timedelta,
    threshold: int,
    lock_for: timedelta,
) -> None:
    """Zählt einen Fehlversuch und sperrt beim Überschreiten der Schwelle.

    Gezählt wird pro (IP, Benutzername), nicht pro Benutzername allein: eine
    reine Benutzersperre ist selbst eine Waffe — zehn falsche Versuche würden
    genügen, um jemanden auszusperren. Siehe `docs/authentifizierung.md`, 3.
    """
    moment = now()
    row = attempt_row(conn, ip_key, key)

    if row is None or from_text(row["first_failed"]) + window < moment:
        # Erster Versuch, oder das Beobachtungsfenster ist abgelaufen.
        conn.execute(
            "INSERT INTO login_attempts"
            " (ip_key, username_key, failed_count, first_failed, locked_until)"
            " VALUES (?, ?, 1, ?, NULL)"
            " ON CONFLICT (ip_key, username_key) DO UPDATE SET"
            " failed_count = 1, first_failed = excluded.first_failed,"
            " locked_until = NULL",
            (ip_key, key, to_text(moment)),
        )
        return

    count = int(row["failed_count"]) + 1
    locked_until = to_text(moment + lock_for) if count >= threshold else None

    conn.execute(
        "UPDATE login_attempts SET failed_count = ?, locked_until = ?"
        " WHERE ip_key = ? AND username_key = ?",
        (count, locked_until, ip_key, key),
    )


def clear_failures(conn: sqlite3.Connection, ip_key: str, key: str) -> None:
    conn.execute(
        "DELETE FROM login_attempts WHERE ip_key = ? AND username_key = ?",
        (ip_key, key),
    )


def locked_until(conn: sqlite3.Connection, ip_key: str, key: str) -> datetime | None:
    """Bis wann gesperrt ist, oder None."""
    row = attempt_row(conn, ip_key, key)
    if row is None or row["locked_until"] is None:
        return None

    until = from_text(row["locked_until"])
    return until if until > now() else None
