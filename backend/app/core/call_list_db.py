"""SQLite-Persistenz der Telefonakquise — das einzige Modul mit deren SQL.

Die dritte Datenbankdatei der Anwendung, nach `kanban.db` und `auth.db`, und
über denselben Trick am selben Ort: `CALL_DB_PATH` ist standardmäßig
*relativ* (`data/calls.db`), was zu `backend/data/calls.db` auflöst, wenn
uvicorn aus `backend/` läuft, und zu `/app/data/calls.db` im Container. In
Produktion liegt dieses Verzeichnis auf dem Volume aus `docker-compose.yml`
(`./data/kanban:/app/data`) — ohne diese Zeile ist die Anrufliste nach jedem
`--build` weg, und mit ihr das Protokoll der Einwilligungen.

Vier Tabellen:

* `lists` — eine importierte CSV.
* `contacts` — eine Zeile daraus, plus Zustand und Wiedervorlage.
* `events` — das Protokoll. Wird **nur angehängt**, nie geändert; `betrieb`
  und `telefon` stehen bewusst redundant darin, damit eine Protokollzeile für
  sich lesbar bleibt und nicht von einer Tabelle abhängt, die sich noch ändern
  kann. Ein Protokoll, das man erst mit einem JOIN versteht, ist als Nachweis
  nur die Hälfte wert. Auch eine *Korrektur* ist nur eine weitere Zeile, die
  über `corrects_event_id` auf die falsche zeigt — ein UPDATE gibt es hier
  nicht, sonst wäre der Nachweis nachträglich formbar.
* `blacklist` — jede Nummer, die je importiert wurde, plus was von Hand
  gesperrt wurde. Sie ist der Grund, dass sich zwei Listen nicht überschneiden
  können, und hält bewusst **keine** Fremdschlüssel: sie muss das Archivieren
  *und* das Löschen ihrer Herkunftsliste überleben, sonst wäre sie genau in
  dem Moment leer, in dem sie gebraucht wird. Herkunft steht deshalb redundant
  als Text darin, wie beim Protokoll.
"""

import os
import re
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator, Sequence

DEFAULT_DB_PATH = "data/calls.db"

BUSY_TIMEOUT_MS = 5000

SCHEMA_VERSION = "3"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS lists (
    id              TEXT    PRIMARY KEY,
    name            TEXT    NOT NULL,
    source_filename TEXT    NOT NULL DEFAULT '',
    columns         TEXT    NOT NULL DEFAULT '[]',
    created_at      TEXT    NOT NULL,
    created_by      TEXT    NOT NULL DEFAULT '',
    archived        INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS contacts (
    id             TEXT    PRIMARY KEY,
    list_id        TEXT    NOT NULL REFERENCES lists (id) ON DELETE CASCADE,
    position       INTEGER NOT NULL,
    betrieb        TEXT    NOT NULL,
    telefon        TEXT    NOT NULL,
    telefon_key    TEXT    NOT NULL DEFAULT '',
    email          TEXT    NOT NULL DEFAULT '',
    ort            TEXT    NOT NULL DEFAULT '',
    plz            TEXT    NOT NULL DEFAULT '',
    website        TEXT    NOT NULL DEFAULT '',
    gewerk         TEXT    NOT NULL DEFAULT '',
    prio           TEXT    NOT NULL DEFAULT '',
    befunde        TEXT    NOT NULL DEFAULT '',
    extras         TEXT    NOT NULL DEFAULT '{}',
    state          TEXT    NOT NULL DEFAULT 'offen',
    due_at         TEXT,
    appointment_at TEXT,
    attempts       INTEGER NOT NULL DEFAULT 0,
    note           TEXT    NOT NULL DEFAULT '',
    updated_at     TEXT    NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_contacts_pool
    ON contacts (state, due_at, position);
CREATE INDEX IF NOT EXISTS idx_contacts_list ON contacts (list_id, position);
CREATE INDEX IF NOT EXISTS idx_contacts_phone ON contacts (telefon_key);

CREATE TABLE IF NOT EXISTS events (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    contact_id     TEXT    NOT NULL REFERENCES contacts (id) ON DELETE CASCADE,
    list_id        TEXT    NOT NULL DEFAULT '',
    betrieb        TEXT    NOT NULL DEFAULT '',
    telefon        TEXT    NOT NULL DEFAULT '',
    occurred_at    TEXT    NOT NULL,
    user_id        TEXT    NOT NULL DEFAULT '',
    username       TEXT    NOT NULL DEFAULT '',
    outcome        TEXT    NOT NULL,
    note           TEXT    NOT NULL DEFAULT '',
    email          TEXT    NOT NULL DEFAULT '',
    due_at         TEXT,
    appointment_at TEXT,
    -- Gesetzt, wenn diese Zeile eine frühere richtigstellt. Eine Korrektur
    -- überschreibt nichts: sie ist selbst eine Protokollzeile und zeigt auf
    -- die, die falsch war. Beide bleiben lesbar — das ist der Unterschied
    -- zwischen „berichtigt" und „nie passiert".
    corrects_event_id INTEGER REFERENCES events (id) ON DELETE SET NULL
);

CREATE INDEX IF NOT EXISTS idx_events_contact ON events (contact_id, id);
CREATE INDEX IF NOT EXISTS idx_events_recent ON events (id DESC);
CREATE INDEX IF NOT EXISTS idx_events_corrects ON events (corrects_event_id);

CREATE TABLE IF NOT EXISTS blacklist (
    telefon_key TEXT    PRIMARY KEY,
    telefon     TEXT    NOT NULL DEFAULT '',
    betrieb     TEXT    NOT NULL DEFAULT '',
    source      TEXT    NOT NULL DEFAULT 'import',
    list_id     TEXT    NOT NULL DEFAULT '',
    list_name   TEXT    NOT NULL DEFAULT '',
    note        TEXT    NOT NULL DEFAULT '',
    created_at  TEXT    NOT NULL,
    created_by  TEXT    NOT NULL DEFAULT ''
);

CREATE INDEX IF NOT EXISTS idx_blacklist_created ON blacklist (created_at DESC);

CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""


def db_path() -> Path:
    """Pfad *jetzt* auflösen, nicht beim Import — wie bei `kanban_db`.

    Macht die Fixture in `conftest.py` möglich, die auf ein `tmp_path` zeigt.
    """
    return Path(os.getenv("CALL_DB_PATH", DEFAULT_DB_PATH))


def now() -> str:
    """Aktueller UTC-Zeitstempel als ISO-8601-Text.

    SQLite hat keinen Datumstyp; ISO-8601-Text sortiert und vergleicht richtig,
    solange alles in UTC steht — deshalb wird jeder Zeitpunkt aus dem Browser
    beim Eintreffen umgerechnet und nie in Ortszeit gespeichert.
    """
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def new_id() -> str:
    return str(uuid.uuid4())


def phone_key(number: str) -> str:
    """Vergleichsschlüssel einer Telefonnummer.

    Dient nur einem Zweck: denselben Betrieb nicht zweimal anrufen. Deshalb
    wird alles außer Ziffern verworfen und die deutsche Landesvorwahl auf die
    führende Null zurückgeführt — „+49 5224 79473", „0049 5224 79473" und
    „05224 / 79473" sind dieselbe Nummer.

    Bewusst keine vollständige Rufnummernnormalisierung: Durchwahlen und
    Auslandsnummern bleiben so, wie sie in der Datei stehen. Ein übersehenes
    Duplikat ist ein doppelter Anruf, ein falsch zusammengeworfenes Duplikat
    ein Betrieb, den nie jemand anruft — das schlechtere von beidem.
    """
    digits = re.sub(r"\D", "", number)

    if not digits:
        return ""

    if digits.startswith("0049"):
        digits = "0" + digits[4:]
    elif digits.startswith("49") and number.strip().startswith("+"):
        digits = "0" + digits[2:]

    return digits


@contextmanager
def connect() -> Iterator[sqlite3.Connection]:
    """Eine Verbindung für die Dauer eines Requests.

    Pro Aufruf statt geteilt: synchrone FastAPI-Handler laufen im Threadpool
    und `sqlite3`-Verbindungen sind nicht threadsicher. Öffnen ist billig.
    """
    path = db_path()
    if path.parent != Path(""):
        path.parent.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(path, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode = WAL")
    # In SQLite standardmäßig aus — ohne diese Zeile ist das ON DELETE CASCADE
    # oben Dokumentation, und gelöschte Listen hinterlassen verwaiste Kontakte.
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute(f"PRAGMA busy_timeout = {BUSY_TIMEOUT_MS}")

    try:
        yield conn
    finally:
        conn.close()


@contextmanager
def transaction(conn: sqlite3.Connection) -> Iterator[sqlite3.Connection]:
    """Ein Schreibvorgang, ein atomarer Schritt.

    IMMEDIATE nimmt die Schreibsperre gleich, statt sie mitten im Vorgang
    hochzustufen — das ist der Unterschied zwischen „warten" und „database is
    locked", wenn zwei Anrufer gleichzeitig ein Ergebnis eintragen.
    """
    conn.execute("BEGIN IMMEDIATE")
    try:
        yield conn
    except Exception:
        conn.execute("ROLLBACK")
        raise
    conn.execute("COMMIT")


def init_schema() -> None:
    """Tabellen anlegen, falls sie fehlen. Idempotent."""
    with connect() as conn:
        # Vor `executescript`, nicht danach: `_SCHEMA` legt auch einen Index
        # über die neue Spalte an, und der scheitert an einer Tabelle, die sie
        # noch nicht hat. Auf einer frischen Datenbank ist der Aufruf ein
        # No-op, weil es die Tabellen dort noch gar nicht gibt.
        _add_missing_columns(conn)
        conn.executescript(_SCHEMA)
        conn.execute(
            "UPDATE meta SET value = ? WHERE key = 'schema_version'",
            (SCHEMA_VERSION,),
        )
        conn.execute(
            "INSERT OR IGNORE INTO meta (key, value) VALUES ('schema_version', ?)",
            (SCHEMA_VERSION,),
        )
        conn.execute("INSERT OR IGNORE INTO meta (key, value) VALUES ('revision', '0')")
        _backfill_blacklist(conn)


#: Spalten, die nach dem ersten Ausliefern dazugekommen sind, je Tabelle als
#: (Name, vollständige Definition). `CREATE TABLE IF NOT EXISTS` fasst eine
#: vorhandene Tabelle nicht mehr an — ohne diese Liste bekäme nur eine frisch
#: angelegte Datenbank die neue Spalte, und in Produktion (wo die Datei auf dem
#: Volume liegt und jeden Build überlebt) liefe die Anwendung gegen ein Schema
#: von gestern.
_ADDED_COLUMNS: dict[str, tuple[tuple[str, str], ...]] = {
    "events": (
        (
            "corrects_event_id",
            "corrects_event_id INTEGER REFERENCES events (id) ON DELETE SET NULL",
        ),
    ),
}


def _add_missing_columns(conn: sqlite3.Connection) -> None:
    """Nachträglich hinzugekommene Spalten ergänzen. Idempotent.

    Bewusst kein Migrationswerkzeug: es geht um einzelne, immer
    NULL-vorbelegte Spalten. Ein `ALTER TABLE ADD COLUMN` mit
    NULL-Vorbelegung ist in SQLite auch mit eingeschalteten Fremdschlüsseln
    erlaubt — mit einer anderen Vorbelegung wäre es das nicht.
    """
    for table, columns in _ADDED_COLUMNS.items():
        present = {
            row["name"]
            for row in conn.execute(f"PRAGMA table_info({table})").fetchall()
        }

        # Leer heißt: die Tabelle gibt es noch nicht. Dann legt `_SCHEMA` sie
        # gleich vollständig an.
        if not present:
            continue

        for name, definition in columns:
            if name not in present:
                conn.execute(f"ALTER TABLE {table} ADD COLUMN {definition}")


def _backfill_blacklist(conn: sqlite3.Connection) -> None:
    """Bestehende Kontakte einmalig in die Blacklist übernehmen.

    Ohne das käme die Sperre erst für Listen zustande, die *nach* diesem
    Update importiert werden — und ausgerechnet die archivierten Runden, die
    der Anwender im Kopf hat, wenn er von Doppelanrufen spricht, wären nicht
    dabei.

    Die Marke steht in `meta` und nicht in „ist die Tabelle leer": wer alle
    Einträge von Hand entfernt hat, hat das so gemeint und bekäme sie sonst
    beim nächsten Start zurück.
    """
    done = conn.execute(
        "SELECT value FROM meta WHERE key = 'blacklist_backfilled'"
    ).fetchone()

    if done is not None:
        return

    conn.execute(
        "INSERT OR IGNORE INTO blacklist"
        " (telefon_key, telefon, betrieb, source, list_id, list_name,"
        "  note, created_at, created_by)"
        " SELECT c.telefon_key, c.telefon, c.betrieb, 'import', c.list_id, l.name,"
        "        '', ?, ''"
        "   FROM contacts c JOIN lists l ON l.id = c.list_id"
        "  WHERE c.telefon_key <> ''",
        (now(),),
    )
    conn.execute(
        "INSERT INTO meta (key, value) VALUES ('blacklist_backfilled', ?)",
        (now(),),
    )


# --------------------------------------------------------------------------
# revision
# --------------------------------------------------------------------------


def revision(conn: sqlite3.Connection) -> int:
    row = conn.execute("SELECT value FROM meta WHERE key = 'revision'").fetchone()
    return int(row["value"]) if row else 0


def bump_revision(conn: sqlite3.Connection) -> int:
    """Zählt jeden Schreibvorgang. Muss in derselben Transaktion laufen."""
    conn.execute(
        "UPDATE meta SET value = CAST(CAST(value AS INTEGER) + 1 AS TEXT)"
        " WHERE key = 'revision'"
    )
    return revision(conn)


# --------------------------------------------------------------------------
# Listen
# --------------------------------------------------------------------------


def insert_list(
    conn: sqlite3.Connection,
    *,
    list_id: str,
    name: str,
    source_filename: str,
    columns: str,
    created_by: str,
) -> None:
    conn.execute(
        "INSERT INTO lists"
        " (id, name, source_filename, columns, created_at, created_by, archived)"
        " VALUES (?, ?, ?, ?, ?, ?, 0)",
        (list_id, name, source_filename, columns, now(), created_by),
    )


def all_lists(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    """Alle Listen, neueste zuerst — auch die archivierten."""
    return list(
        conn.execute("SELECT * FROM lists ORDER BY created_at DESC, name").fetchall()
    )


def find_list(conn: sqlite3.Connection, list_id: str) -> sqlite3.Row | None:
    return conn.execute("SELECT * FROM lists WHERE id = ?", (list_id,)).fetchone()


def find_list_by_name(conn: sqlite3.Connection, name: str) -> sqlite3.Row | None:
    """Namensvergleich ohne Groß-/Kleinschreibung und ohne Randleerzeichen.

    Nicht `COLLATE NOCASE`: das faltet in SQLite nur ASCII A–Z, „Käufer" und
    „käufer" wären zwei Listen. `casefold()` in Python macht es richtig, also
    wird hier verglichen, was Python normalisiert hat.
    """
    key = " ".join(name.split()).casefold()

    for row in conn.execute("SELECT * FROM lists"):
        if " ".join(row["name"].split()).casefold() == key:
            return row

    return None


def update_list(
    conn: sqlite3.Connection,
    list_id: str,
    *,
    name: str | None,
    archived: bool | None,
) -> None:
    assignments: list[str] = []
    values: list[object] = []

    if name is not None:
        assignments.append("name = ?")
        values.append(name)
    if archived is not None:
        assignments.append("archived = ?")
        values.append(1 if archived else 0)

    if not assignments:
        return

    values.append(list_id)
    conn.execute(f"UPDATE lists SET {', '.join(assignments)} WHERE id = ?", values)


def delete_list(conn: sqlite3.Connection, list_id: str) -> None:
    """Liste samt Kontakten und deren Protokollzeilen entfernen.

    Der Service lässt das nur zu, wenn nichts protokolliert ist oder es
    ausdrücklich bestätigt wurde — hier steht bloß das SQL dazu.
    """
    conn.execute("DELETE FROM lists WHERE id = ?", (list_id,))


def documented_calls(conn: sqlite3.Connection, list_id: str) -> int:
    """Wie viele Protokollzeilen an dieser Liste hängen."""
    row = conn.execute(
        "SELECT COUNT(*) AS total FROM events WHERE list_id = ?", (list_id,)
    ).fetchone()
    return int(row["total"])


# --------------------------------------------------------------------------
# Kontakte
# --------------------------------------------------------------------------

#: Spalten, die `insert_contacts` in dieser Reihenfolge erwartet.
CONTACT_COLUMNS = (
    "id",
    "list_id",
    "position",
    "betrieb",
    "telefon",
    "telefon_key",
    "email",
    "ort",
    "plz",
    "website",
    "gewerk",
    "prio",
    "befunde",
    "extras",
    "state",
    "updated_at",
)


def insert_contacts(conn: sqlite3.Connection, rows: Sequence[Sequence[object]]) -> None:
    """Alle Kontakte einer Liste in einem Rutsch.

    `executemany` statt einer Schleife mit Einzeltransaktionen: 100 Kontakte
    sind sonst 100 fsyncs.
    """
    placeholders = ", ".join("?" * len(CONTACT_COLUMNS))
    conn.executemany(
        f"INSERT INTO contacts ({', '.join(CONTACT_COLUMNS)})"
        f" VALUES ({placeholders})",
        rows,
    )


def find_contact(conn: sqlite3.Connection, contact_id: str) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT c.*, l.name AS list_name, l.archived AS list_archived"
        " FROM contacts c JOIN lists l ON l.id = c.list_id"
        " WHERE c.id = ?",
        (contact_id,),
    ).fetchone()


# Die Vorrats-Zustände stehen hier als Text, weil dieses Modul die Schemata
# nicht kennt (`POOL_STATES` in `schemas/call_list.py` ist dieselbe Menge, und
# `test_call_list_service.py` hält beide zusammen). Die Rangfolge zwischen
# ihnen steht in `next_contact`.
_POOL_FILTER = (
    " FROM contacts c JOIN lists l ON l.id = c.list_id"
    " WHERE l.archived = 0 AND c.state IN ('rueckruf', 'offen', 'wiedervorlage')"
)


def next_contact(conn: sqlite3.Connection, moment: str) -> sqlite3.Row | None:
    """Der nächste fällige Kontakt, oder `None`.

    Die Rangfolge ist Absicht:

    1. **vereinbarte Rückrufe**, früheste zuerst — dort wurde eine Zusage
       gemacht, die eingehalten werden muss.
    2. **noch nie angerufene** Kontakte in der Reihenfolge der Datei; ältere
       Listen zuerst.
    3. **Wiedervorlagen** — „nach hinten in die Liste" heißt: hinter alles,
       was noch nie versucht wurde.

    Für Gruppe 2 ist der zweite Sortierschlüssel konstant leer, damit sie über
    Liste und Position sortiert; für 1 und 3 sortiert der fällige Zeitpunkt.
    """
    return conn.execute(
        "SELECT c.*, l.name AS list_name, l.archived AS list_archived"
        + _POOL_FILTER
        + " AND (c.due_at IS NULL OR c.due_at <= ?)"
        " ORDER BY CASE c.state"
        "     WHEN 'rueckruf' THEN 0"
        "     WHEN 'offen' THEN 1"
        "     ELSE 2 END,"
        "   CASE WHEN c.state = 'offen' THEN '' ELSE COALESCE(c.due_at, '') END,"
        "   l.created_at, c.position, c.id"
        " LIMIT 1",
        (moment,),
    ).fetchone()


def next_due_at(conn: sqlite3.Connection, moment: str) -> str | None:
    """Wann der nächste aufgeschobene Kontakt zurückkommt."""
    row = conn.execute(
        "SELECT MIN(c.due_at) AS due" + _POOL_FILTER + " AND c.due_at > ?",
        (moment,),
    ).fetchone()

    return row["due"] if row and row["due"] else None


def state_totals(
    conn: sqlite3.Connection, moment: str, *, list_id: str | None = None
) -> dict[str, tuple[int, int]]:
    """Pro Zustand: (fällig, gesamt).

    Eine Abfrage für alle Zähler. `due` ist nur bei den Vorrats-Zuständen
    interessant, wird aber überall mitgerechnet — das kostet nichts und spart
    die Sonderfälle.

    Ohne `list_id` zählt die Übersicht des Anrufers und lässt archivierte
    Listen aus; mit `list_id` zählt die Verwaltung eine einzelne Liste, auch
    eine archivierte.
    """
    if list_id is None:
        where = " FROM contacts c JOIN lists l ON l.id = c.list_id WHERE l.archived = 0"
        params: tuple[object, ...] = (moment,)
    else:
        where = " FROM contacts c WHERE c.list_id = ?"
        params = (moment, list_id)

    rows = conn.execute(
        "SELECT c.state AS state,"
        "   SUM(CASE WHEN c.due_at IS NULL OR c.due_at <= ? THEN 1 ELSE 0 END) AS due,"
        "   COUNT(*) AS total" + where + " GROUP BY c.state",
        params,
    ).fetchall()

    return {row["state"]: (int(row["due"] or 0), int(row["total"])) for row in rows}


def promised_without_email(
    conn: sqlite3.Connection, *, list_id: str | None = None
) -> int:
    """Zusagen ohne Adresse — die Zusagen, aus denen keine E-Mail wird."""
    if list_id is None:
        row = conn.execute(
            "SELECT COUNT(*) AS total FROM contacts c"
            " JOIN lists l ON l.id = c.list_id"
            " WHERE l.archived = 0 AND c.state = 'zugesagt' AND c.email = ''"
        ).fetchone()
    else:
        row = conn.execute(
            "SELECT COUNT(*) AS total FROM contacts"
            " WHERE list_id = ? AND state = 'zugesagt' AND email = ''",
            (list_id,),
        ).fetchone()

    return int(row["total"])


def existing_phone_keys(conn: sqlite3.Connection) -> set[str]:
    """Alle Nummern, die in einer *aktiven* Liste stehen.

    Grundlage der Duplikatprüfung beim Import. Archivierte Listen zählen nicht
    mit: eine abgeschlossene Runde soll eine neue nicht blockieren.
    """
    return {
        row["telefon_key"]
        for row in conn.execute(
            "SELECT DISTINCT c.telefon_key FROM contacts c"
            " JOIN lists l ON l.id = c.list_id"
            " WHERE l.archived = 0 AND c.telefon_key <> ''"
        )
    }


def phone_key_owners(conn: sqlite3.Connection) -> dict[str, str]:
    """Nummer → Name der aktiven Liste, in der sie schon steht.

    Für die Meldung „steht bereits in „Handwerker Herford"" — eine
    Duplikatmeldung ohne den Ort des Originals ist nicht handlungsfähig.
    """
    owners: dict[str, str] = {}

    for row in conn.execute(
        "SELECT c.telefon_key AS key, l.name AS name FROM contacts c"
        " JOIN lists l ON l.id = c.list_id"
        " WHERE l.archived = 0 AND c.telefon_key <> ''"
        " ORDER BY l.created_at"
    ):
        owners.setdefault(row["key"], row["name"])

    return owners


def apply_outcome(
    conn: sqlite3.Connection,
    contact_id: str,
    *,
    state: str,
    due_at: str | None,
    appointment_at: str | None,
    note: str,
    email: str | None,
    count_attempt: bool,
) -> None:
    """Den Kontakt auf den neuen Stand setzen.

    `email is None` heißt unverändert — ein Anrufer, der das Feld nicht
    anfasst, darf eine bekannte Adresse nicht löschen. `count_attempt` ist
    falsch bei „Nummer falsch": das war kein Anrufversuch beim Betrieb.
    """
    assignments = [
        "state = ?",
        "due_at = ?",
        "appointment_at = ?",
        "note = ?",
        "updated_at = ?",
    ]
    values: list[object] = [state, due_at, appointment_at, note, now()]

    if email is not None:
        assignments.append("email = ?")
        values.append(email)

    if count_attempt:
        assignments.append("attempts = attempts + 1")

    values.append(contact_id)
    conn.execute(f"UPDATE contacts SET {', '.join(assignments)} WHERE id = ?", values)


# --------------------------------------------------------------------------
# Protokoll
# --------------------------------------------------------------------------


def insert_event(
    conn: sqlite3.Connection,
    *,
    contact_id: str,
    list_id: str,
    betrieb: str,
    telefon: str,
    user_id: str,
    username: str,
    outcome: str,
    note: str,
    email: str,
    due_at: str | None,
    appointment_at: str | None,
    corrects_event_id: int | None = None,
) -> int:
    """Eine Protokollzeile anhängen. Es gibt kein UPDATE auf `events`.

    Eine Richtigstellung ist deshalb ebenfalls ein Anhang: sie trägt in
    `corrects_event_id` die Zeile, die falsch war, und lässt sie stehen.
    Liefert die ID der neuen Zeile — die Korrektur einer Korrektur braucht sie.
    """
    cursor = conn.execute(
        "INSERT INTO events"
        " (contact_id, list_id, betrieb, telefon, occurred_at, user_id, username,"
        "  outcome, note, email, due_at, appointment_at, corrects_event_id)"
        " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            contact_id,
            list_id,
            betrieb,
            telefon,
            now(),
            user_id,
            username,
            outcome,
            note,
            email,
            due_at,
            appointment_at,
            corrects_event_id,
        ),
    )

    return int(cursor.lastrowid or 0)


def events_of_contact(conn: sqlite3.Connection, contact_id: str) -> list[sqlite3.Row]:
    """Protokoll eines Kontakts, jüngste Zeile zuerst."""
    return list(
        conn.execute(
            "SELECT * FROM events WHERE contact_id = ? ORDER BY id DESC",
            (contact_id,),
        ).fetchall()
    )


#: Was `recent_events` an jede Protokollzeile hängt, damit die Oberfläche
#: nicht pro Zeile nachfragen muss:
#:
#: * `latest_event_id` — die jüngste Zeile *desselben* Kontakts. Nur sie
#:   bestimmt seinen Zustand und darf deshalb geändert werden.
#: * `correction_count` — ob diese Zeile bereits richtiggestellt wurde.
#: * `contact_state` / `list_archived` — der Stand, auf den eine Korrektur
#:   trifft.
_EVENT_CONTEXT = (
    " e.*, l.name AS list_name, l.archived AS list_archived,"
    " c.state AS contact_state,"
    " (SELECT MAX(later.id) FROM events later"
    "   WHERE later.contact_id = e.contact_id) AS latest_event_id,"
    " (SELECT COUNT(*) FROM events fix"
    "   WHERE fix.corrects_event_id = e.id) AS correction_count"
    " FROM events e"
    " LEFT JOIN lists l ON l.id = e.list_id"
    " LEFT JOIN contacts c ON c.id = e.contact_id"
)


def recent_events(
    conn: sqlite3.Connection, *, limit: int, offset: int
) -> list[sqlite3.Row]:
    """Die zuletzt eingetragenen Entscheidungen, jüngste zuerst.

    Über die AUTOINCREMENT-ID sortiert und nicht über `occurred_at`: zwei
    Einträge derselben Sekunde hätten denselben Zeitstempel, und eine
    Korrektur würde dann womöglich *über* der Zeile stehen, die sie
    richtigstellt.
    """
    return list(
        conn.execute(
            "SELECT" + _EVENT_CONTEXT + " ORDER BY e.id DESC LIMIT ? OFFSET ?",
            (limit, offset),
        ).fetchall()
    )


def events_total(conn: sqlite3.Connection) -> int:
    row = conn.execute("SELECT COUNT(*) AS total FROM events").fetchone()
    return int(row["total"])


def find_event(conn: sqlite3.Connection, event_id: int) -> sqlite3.Row | None:
    """Eine Protokollzeile samt ihrem Umfeld — die Vorlage einer Korrektur."""
    return conn.execute(
        "SELECT" + _EVENT_CONTEXT + " WHERE e.id = ?", (event_id,)
    ).fetchone()


def all_events(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    """Das ganze Protokoll, älteste Zeile zuerst — für die Ausgabe."""
    return list(
        conn.execute(
            "SELECT e.*, l.name AS list_name,"
            "   fixed.occurred_at AS corrects_occurred_at,"
            "   fixed.outcome AS corrects_outcome"
            " FROM events e"
            " LEFT JOIN lists l ON l.id = e.list_id"
            " LEFT JOIN events fixed ON fixed.id = e.corrects_event_id"
            " ORDER BY e.id"
        ).fetchall()
    )


def promised_contacts(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    """Alle Zusagen, mit dem Zeitpunkt und dem Konto der Zusage.

    Grundlage der Ausgabe für den Mailversand. Der JOIN holt die *letzte*
    Zusage aus dem Protokoll — mehr als eine gibt es nur, wenn ein Kontakt neu
    eingelesen und erneut angerufen wurde.
    """
    return list(
        conn.execute(
            "SELECT c.*, l.name AS list_name,"
            "   (SELECT e.occurred_at FROM events e"
            "     WHERE e.contact_id = c.id AND e.outcome = 'zugesagt'"
            "     ORDER BY e.id DESC LIMIT 1) AS promised_at,"
            "   (SELECT e.username FROM events e"
            "     WHERE e.contact_id = c.id AND e.outcome = 'zugesagt'"
            "     ORDER BY e.id DESC LIMIT 1) AS promised_by"
            " FROM contacts c JOIN lists l ON l.id = c.list_id"
            " WHERE c.state = 'zugesagt'"
            " ORDER BY l.created_at, c.position"
        ).fetchall()
    )


# --------------------------------------------------------------------------
# Blacklist
# --------------------------------------------------------------------------

#: Wie viele Nummern eine `IN (...)`-Abfrage auf einmal fragt. SQLite lässt
#: heute 32766 Parameter zu, ältere Builds 999 — 500 liegt sicher unter beidem
#: und kostet bei 5000 Zeilen zehn Abfragen.
_LOOKUP_CHUNK = 500

#: Woher ein Eintrag kommt. Nur Anzeige, aber die Meldung beim Import liest sie.
BLACKLIST_SOURCES = ("import", "manuell")

#: Spalten, die `add_to_blacklist` in dieser Reihenfolge erwartet.
BLACKLIST_COLUMNS = (
    "telefon_key",
    "telefon",
    "betrieb",
    "source",
    "list_id",
    "list_name",
    "note",
    "created_at",
    "created_by",
)


def blacklist_lookup(
    conn: sqlite3.Connection, keys: Sequence[str]
) -> dict[str, sqlite3.Row]:
    """Die Blacklist-Einträge zu genau diesen Nummern.

    Fragt gezielt statt die ganze Tabelle zu laden: die Blacklist wächst mit
    jedem Import und ist die eine Tabelle hier, die keine Obergrenze hat.
    """
    wanted = [key for key in dict.fromkeys(keys) if key]
    found: dict[str, sqlite3.Row] = {}

    for start in range(0, len(wanted), _LOOKUP_CHUNK):
        chunk = wanted[start : start + _LOOKUP_CHUNK]
        placeholders = ", ".join("?" * len(chunk))
        for row in conn.execute(
            f"SELECT * FROM blacklist WHERE telefon_key IN ({placeholders})", chunk
        ):
            found[row["telefon_key"]] = row

    return found


def add_to_blacklist(conn: sqlite3.Connection, rows: Sequence[Sequence[object]]) -> int:
    """Nummern sperren. Vorhandene bleiben, wie sie sind.

    `INSERT OR IGNORE`: der *erste* Eintrag gewinnt, damit die Herkunft auf
    die Liste zeigt, die die Nummer zuerst hatte — das ist die Angabe, die
    eine Duplikatmeldung brauchbar macht.
    """
    if not rows:
        return 0

    placeholders = ", ".join("?" * len(BLACKLIST_COLUMNS))
    cursor = conn.executemany(
        f"INSERT OR IGNORE INTO blacklist ({', '.join(BLACKLIST_COLUMNS)})"
        f" VALUES ({placeholders})",
        rows,
    )

    return cursor.rowcount if cursor.rowcount and cursor.rowcount > 0 else 0


def blacklist_total(conn: sqlite3.Connection) -> int:
    row = conn.execute("SELECT COUNT(*) AS total FROM blacklist").fetchone()
    return int(row["total"])


def blacklist_page(
    conn: sqlite3.Connection, *, query: str, limit: int, offset: int
) -> tuple[list[sqlite3.Row], int]:
    """Ein Ausschnitt der Blacklist, neueste zuerst, plus die Gesamtzahl.

    Die Suche geht über Nummer *und* Betrieb: gesucht wird mal nach „steht die
    05221 111 drauf", mal nach „warum kommt Zaunbau Müller nicht".
    """
    term = query.strip()

    if term:
        # Der Ziffernschlüssel, damit „+49 5221 111" dieselbe Nummer findet
        # wie „05221111"; ist nichts Ziffriges dabei, bleibt er leer und die
        # Bedingung fällt auf den Namen zurück.
        digits = phone_key(term)
        where = " WHERE betrieb LIKE ? OR telefon LIKE ?" + (
            " OR telefon_key LIKE ?" if digits else ""
        )
        params: tuple[object, ...] = (f"%{term}%", f"%{term}%")
        if digits:
            params += (f"%{digits}%",)
    else:
        where = ""
        params = ()

    total = int(
        conn.execute(
            f"SELECT COUNT(*) AS total FROM blacklist{where}", params
        ).fetchone()["total"]
    )

    rows = list(
        conn.execute(
            f"SELECT * FROM blacklist{where}"
            " ORDER BY created_at DESC, betrieb, telefon_key"
            " LIMIT ? OFFSET ?",
            params + (limit, offset),
        ).fetchall()
    )

    return rows, total


def all_blacklist(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    """Die ganze Blacklist, älteste zuerst — für die Ausgabe."""
    return list(
        conn.execute(
            "SELECT * FROM blacklist ORDER BY created_at, betrieb, telefon_key"
        ).fetchall()
    )


def remove_from_blacklist(conn: sqlite3.Connection, telefon_key: str) -> bool:
    """Eine Nummer wieder freigeben. Liefert, ob es sie gab."""
    cursor = conn.execute("DELETE FROM blacklist WHERE telefon_key = ?", (telefon_key,))
    return bool(cursor.rowcount)


def drop_blacklist_of_list(conn: sqlite3.Connection, list_id: str) -> int:
    """Die Sperren freigeben, die aus dieser Liste stammen.

    Gehört zum *Löschen* einer Liste, nicht zum Archivieren: Löschen heißt in
    diesem Werkzeug „das hat nicht stattgefunden" (es nimmt auch das Protokoll
    mit), und dann darf dieselbe Datei erneut importierbar sein. Archivieren
    heißt „Runde beendet" und behält beides.

    Nummern, die noch in einer anderen Liste stecken, bleiben gesperrt.
    """
    cursor = conn.execute(
        "DELETE FROM blacklist WHERE list_id = ? AND telefon_key NOT IN ("
        "  SELECT c.telefon_key FROM contacts c WHERE c.list_id <> ?"
        ")",
        (list_id, list_id),
    )
    return cursor.rowcount if cursor.rowcount and cursor.rowcount > 0 else 0
