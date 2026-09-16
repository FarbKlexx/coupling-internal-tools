"""SQLite-Persistenz der Telefonakquise — das einzige Modul mit deren SQL.

Die dritte Datenbankdatei der Anwendung, nach `kanban.db` und `auth.db`, und
über denselben Trick am selben Ort: `CALL_DB_PATH` ist standardmäßig
*relativ* (`data/calls.db`), was zu `backend/data/calls.db` auflöst, wenn
uvicorn aus `backend/` läuft, und zu `/app/data/calls.db` im Container. In
Produktion liegt dieses Verzeichnis auf dem Volume aus `docker-compose.yml`
(`./data/kanban:/app/data`) — ohne diese Zeile ist die Anrufliste nach jedem
`--build` weg, und mit ihr das Protokoll der Einwilligungen.

Fünf Tabellen:

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
* `mail_status` — was aus einer Zusage geworden ist (Mailversand). Hängt am
  Kontakt und fährt dessen `ON DELETE CASCADE` mit: anders als das Protokoll
  ist das kein Nachweis, sondern Arbeitsstand. Eine Zusage ohne Zeile hier
  steht auf `offen` — der Ausgangszustand braucht keinen Datensatz.

Der Mailversand ist ein eigenes Werkzeug mit eigener Seitenberechtigung, aber
**keiner eigenen Datenbank**: seine Zeilen *sind* die Kontakte im Zustand
`zugesagt`. Deshalb steht sein SQL hier und nicht in einem zweiten Modul —
eine Datei, zwei Module mit SQL darauf wäre die Sorte Aufteilung, bei der
niemand mehr weiß, wo eine Abfrage hingehört.
"""

import os
import re
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterator, NamedTuple, Sequence

DEFAULT_DB_PATH = "data/calls.db"

BUSY_TIMEOUT_MS = 5000

SCHEMA_VERSION = "5"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS lists (
    id              TEXT    PRIMARY KEY,
    name            TEXT    NOT NULL,
    source_filename TEXT    NOT NULL DEFAULT '',
    columns         TEXT    NOT NULL DEFAULT '[]',
    created_at      TEXT    NOT NULL,
    created_by      TEXT    NOT NULL DEFAULT '',
    archived        INTEGER NOT NULL DEFAULT 0,
    -- Die Sammelliste der von Hand im Mailversand angelegten Betriebe. Es
    -- gibt höchstens eine; gesucht wird sie über dieses Kennzeichen und
    -- nicht über den Namen, damit ein Umbenennen sie nicht verliert. NULL
    -- wie 0 heißt „kam aus einer Datei" — nachträglich hinzugekommen.
    manual          INTEGER
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

-- Mailversand: was aus einer Zusage geworden ist.
--
-- Eine Zeile entsteht erst mit dem ersten Klick; wer keine hat, steht auf
-- `offen`. Die Zustände `nachfassen` und `keine_antwort` werden hier nie
-- gespeichert — sie werden beim Lesen aus `sent_at` gerechnet, siehe
-- `_MAIL_STATE`.
CREATE TABLE IF NOT EXISTS mail_status (
    contact_id  TEXT    PRIMARY KEY REFERENCES contacts (id) ON DELETE CASCADE,
    state       TEXT    NOT NULL DEFAULT 'offen',
    sent_at     TEXT,
    answered_at TEXT,
    -- Wann telefonisch nachgefasst wurde. Eigene Spalte und nicht bloß
    -- `updated_at`: die nächste Anmerkung überschriebe das wieder, und
    -- „wann haben wir angerufen?" ist genau die Frage, die beim zweiten
    -- Anruf gestellt wird. Nachträglich hinzugekommen.
    followed_up_at TEXT,
    note        TEXT    NOT NULL DEFAULT '',
    updated_at  TEXT    NOT NULL,
    updated_by  TEXT    NOT NULL DEFAULT '',
    -- Die Bau-Einschätzung: eine zweite, vom Versandstand unabhängige
    -- Größe (`BuildReadiness`). NULL heißt „noch nicht eingeschätzt" —
    -- genauso wie eine fehlende Zeile `offen` heißt. Nachträglich
    -- hinzugekommen, siehe `_ADDED_COLUMNS`.
    build_readiness TEXT,
    -- „Bigger than expected": die *dritte* Größe, und die einzige, die mit
    -- den anderen beiden kombinierbar ist — eine Seite kann gleichzeitig
    -- „In Development" und größer als ein Onepager sein. Deshalb eine
    -- eigene Spalte und kein weiterer Wert von `build_readiness`: der
    -- Umfang soll über den ganzen Bau stehen bleiben. NULL wie 0 heißt
    -- „niemand hat das gesagt". Nachträglich hinzugekommen.
    oversized INTEGER
);

CREATE INDEX IF NOT EXISTS idx_mail_status_state ON mail_status (state, sent_at);

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
    "lists": (("manual", "manual INTEGER"),),
    "mail_status": (
        ("build_readiness", "build_readiness TEXT"),
        ("oversized", "oversized INTEGER"),
        ("followed_up_at", "followed_up_at TEXT"),
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
# Fristen des Mailversands
# --------------------------------------------------------------------------
#
# Steht hier oben und nicht im Mailversand-Abschnitt, weil beide Werkzeuge es
# brauchen: der Versandstand einer Zusage entscheidet auch, ob ihr Betrieb im
# Anrufvorrat ganz nach vorne rückt (`next_contact`). Eine zweite Rechnung
# dafür wäre die Sorte Abweichung, die erst auffällt, wenn die Warteschlange
# etwas anderes behauptet als die Versandliste.


class MailCutoffs(NamedTuple):
    """Die beiden Stichtage, ab denen eine versendete Mail fällig wird.

    `answer` ist jetzt minus der langen Frist („keine Antwort"), `followup`
    jetzt minus der kurzen („nachfassen"). Zusammen als ein Wert, weil sie
    zusammengehören: beide werden einmal pro Anfrage gerechnet und dann durch
    jede Abfrage gereicht, damit Liste, Zähler und Schreibpfad denselben
    Moment benutzen. Getrennt weitergereicht wäre die nächste Fehlerquelle
    die Reihenfolge ihrer `?`.

    Ausgerechnet wird beides im Service — er kennt die Fristen, dieses Modul
    kennt nur die Vergleiche.
    """

    answer: str
    followup: str


#: Der Zustand einer Zusage im Mailversand, wie ihn jede Abfrage berechnet.
#:
#: Drei Dinge stecken darin. Erstens: eine Zusage ohne Zeile in `mail_status`
#: steht auf `offen` — der Ausgangszustand braucht keinen Datensatz, sonst
#: müsste jeder Import Zeilen anlegen, die niemand angeklickt hat. Zweitens:
#: eine versendete Mail, auf die seit der langen Frist nichts kam, *ist*
#: „keine Antwort". Drittens, davor: nach der kurzen Frist ist sie
#: „nachfassen", also fällig zum Anruf. Beides steht nirgends geschrieben,
#: sondern folgt aus `sent_at`.
#:
#: Die Reihenfolge der beiden Zweige ist load-bearing: die **lange** Frist
#: wird zuerst geprüft, sonst bliebe eine 40 Tage alte Mail für immer auf
#: „nachfassen" hängen und käme nie bei „keine Antwort" an.
#:
#: `nachgefasst` zählt beim ersten Zweig mit (auch ein Anruf macht aus dem
#: Warten irgendwann ein Ende), beim zweiten nicht: dass angerufen wurde, ist
#: genau die Auskunft, die die Zeile aus dem Reiter nimmt.
#:
#: Gerechnet statt gespeichert, weil es in dieser Anwendung keinen
#: Hintergrundjob gibt: ein Feld, das erst beim nächsten Schreibzugriff
#: nachgezogen würde, wäre bis dahin falsch — und zwar genau in der Ansicht,
#: die es beantworten soll. Es gilt damit auch rückwirkend für jede Zeile,
#: die längst verschickt war, als es diese Frist noch nicht gab. Der Preis
#: sind zwei `?` (die Stichtage, in dieser Reihenfolge) in jeder Abfrage, die
#: diesen Ausdruck verwendet — `_state_params` liefert sie.
_MAIL_STATE = (
    "CASE WHEN COALESCE(m.state, 'offen') IN ('versendet', 'nachgefasst')"
    "       AND m.sent_at IS NOT NULL AND m.sent_at <= ?"
    "     THEN 'keine_antwort'"
    "     WHEN COALESCE(m.state, 'offen') = 'versendet'"
    "       AND m.sent_at IS NOT NULL AND m.sent_at <= ?"
    "     THEN 'nachfassen'"
    "     ELSE COALESCE(m.state, 'offen') END"
)


def _state_params(cutoff: MailCutoffs) -> list[object]:
    """Die `?` von `_MAIL_STATE`, in der Reihenfolge seiner Zweige.

    Einzige Stelle, die diese Reihenfolge kennt: der Ausdruck steht in der
    Spaltenliste *und* im Filter, und zwei Stichtage von Hand einzufädeln ist
    genau die Sorte Arbeit, bei der irgendwann die kurze Frist im langen
    Vergleich landet.
    """
    return [cutoff.answer, cutoff.followup]


def mail_cutoffs(answer_days: int, followup_days: int) -> MailCutoffs:
    """Die beiden Stichtage, aus *einem* `now()` gerechnet.

    Die Fristen selbst kommen als Zahlen herein: dieses Modul kennt die
    Schemata nicht, und wie lange „zu lange" ist, entscheidet die Fachschicht.
    Aus einem Zeitpunkt, damit die beiden nicht einen Wimpernschlag
    auseinanderliegen.
    """
    moment = datetime.now(timezone.utc)

    def stamp(days: int) -> str:
        return (moment - timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ")

    return MailCutoffs(answer=stamp(answer_days), followup=stamp(followup_days))


def days_since(stamp: str | None) -> int | None:
    """Volle Tage seit diesem gespeicherten Zeitpunkt, oder `None`.

    Einmal hier statt in jeder Oberfläche: „seit 12 Tagen" steht in der
    Versandliste, in deren Ausgabe und am Kontakt des Anrufers.
    """
    if not stamp:
        return None

    try:
        moment = datetime.fromisoformat(stamp.replace("Z", "+00:00"))
    except ValueError:
        return None

    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)

    return max((datetime.now(timezone.utc) - moment).days, 0)


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
    manual: bool = False,
) -> None:
    conn.execute(
        "INSERT INTO lists"
        " (id, name, source_filename, columns, created_at, created_by, archived,"
        "  manual)"
        " VALUES (?, ?, ?, ?, ?, ?, 0, ?)",
        (
            list_id,
            name,
            source_filename,
            columns,
            now(),
            created_by,
            1 if manual else 0,
        ),
    )


def find_manual_list(conn: sqlite3.Connection) -> sqlite3.Row | None:
    """Die Sammelliste der von Hand angelegten Betriebe, oder `None`.

    Über das Kennzeichen und nicht über den Namen: die Liste steht in der
    Listenverwaltung wie jede andere und darf dort umbenannt werden.
    """
    return conn.execute(
        "SELECT * FROM lists WHERE manual = 1 ORDER BY created_at LIMIT 1"
    ).fetchone()


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


def insert_contact(
    conn: sqlite3.Connection,
    *,
    contact_id: str,
    list_id: str,
    state: str,
    fields: dict[str, str],
) -> None:
    """Einen einzelnen Kontakt anlegen — der von Hand erfasste Betrieb.

    Eigene Funktion neben `insert_contacts`, obwohl beide dasselbe INSERT
    machen: dort kommt eine ganze Datei in fester Spaltenreihenfolge an, hier
    ein Formular mit benannten Feldern. `position` hängt sich hinten an die
    Liste, damit die Reihenfolge der Erfassung erhalten bleibt.

    `attempts` bleibt bei 0: es hat niemand angerufen.
    """
    position = int(
        conn.execute(
            "SELECT COALESCE(MAX(position), -1) + 1 AS next FROM contacts"
            " WHERE list_id = ?",
            (list_id,),
        ).fetchone()["next"]
    )

    conn.execute(
        "INSERT INTO contacts"
        " (id, list_id, position, betrieb, telefon, telefon_key, email, ort,"
        "  plz, website, gewerk, note, state, updated_at)"
        " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            contact_id,
            list_id,
            position,
            fields["betrieb"],
            fields["telefon"],
            phone_key(fields["telefon"]),
            fields["email"],
            fields["ort"],
            fields["plz"],
            fields["website"],
            fields["gewerk"],
            fields["note"],
            state,
            now(),
        ),
    )


#: Was sich an einem von Hand erfassten Kontakt ändern lässt. Der Zustand
#: steht bewusst nicht darin: der ändert sich über Anruf-Ergebnisse und
#: Richtigstellungen, nie über ein Formular.
_EDITABLE_CONTACT_COLUMNS = frozenset(
    {"betrieb", "telefon", "email", "ort", "plz", "website", "gewerk", "note"}
)


def update_contact_fields(
    conn: sqlite3.Connection, contact_id: str, fields: dict[str, str]
) -> None:
    """Stammdaten eines Kontakts überschreiben.

    Die Spaltennamen werden in den SQL-Text interpoliert und deshalb vorher
    gegen `_EDITABLE_CONTACT_COLUMNS` geprüft — dieselbe Vorsichtsmaßnahme
    wie in `auth_db.update_user_fields`. `telefon_key` zieht automatisch nach:
    er ist abgeleitet, und eine Nummer, die sich ändert, ohne dass ihr
    Schlüssel es tut, wäre in der Doppelprüfung unsichtbar.
    """
    unknown = set(fields) - _EDITABLE_CONTACT_COLUMNS
    if unknown:
        raise ValueError(f"Unbekannte Kontaktspalten: {sorted(unknown)}")

    assignments = [f"{column} = ?" for column in fields]
    values: list[object] = list(fields.values())

    if "telefon" in fields:
        assignments.append("telefon_key = ?")
        values.append(phone_key(fields["telefon"]))

    assignments.append("updated_at = ?")
    values.append(now())
    values.append(contact_id)

    conn.execute(f"UPDATE contacts SET {', '.join(assignments)} WHERE id = ?", values)


def find_contact(
    conn: sqlite3.Connection, contact_id: str, cutoff: MailCutoffs
) -> sqlite3.Row | None:
    """Ein Kontakt samt Liste und Versandstand.

    Der Versandstand fährt überall mit, wo ein `CallContact` entsteht: eine
    Zusage, deren Mail zum Nachfassen fällig ist, wird dem Anrufer anders
    vorgelegt als ein Erstanruf — und das darf nicht davon abhängen, über
    welche Abfrage sie gekommen ist.
    """
    return conn.execute(
        "SELECT c.*, l.name AS list_name, l.archived AS list_archived,"
        + _CONTACT_MAIL
        + " FROM contacts c JOIN lists l ON l.id = c.list_id"
        + _CONTACT_MAIL_JOIN
        + " WHERE c.id = ?",
        _state_params(cutoff) + [contact_id],
    ).fetchone()


def search_contacts(
    conn: sqlite3.Connection,
    *,
    query: str,
    limit: int,
    offset: int,
    cutoff: MailCutoffs,
) -> tuple[list[sqlite3.Row], int]:
    """Kontakte zu einem Suchbegriff, plus die Zahl der Treffer.

    Gesucht wird über Betrieb, Adresse und Nummer — dieselben drei Felder wie
    in der Versandliste (`_mail_filter`), damit sich die beiden Suchen der
    Anwendung nicht unterschiedlich verhalten.

    **Archivierte Listen sind eingeschlossen.** Das ist der Unterschied zum
    Anrufvorrat: hier wird nachgesehen, was bei einem Betrieb war, und die
    Antwort „stand mal in einer Liste, die inzwischen beendet ist" ist genau
    die, nach der gefragt wurde. Die Reihenfolge stellt die aktiven Listen
    voran und sortiert darin nach Betrieb — alphabetisch, weil in einer
    Trefferliste gesucht *gelesen* wird.

    Ein leerer Begriff liefert nichts: das ist eine Suche und keine zweite
    Ansicht auf alle Kontakte.
    """
    term = query.strip()

    if not term:
        return [], 0

    # Der Ziffernschlüssel wie in der Blacklist-Suche, damit „+49 5221 111"
    # dieselbe Nummer findet wie „05221111".
    digits = phone_key(term)
    conditions = ["c.betrieb LIKE ?", "c.email LIKE ?", "c.telefon LIKE ?"]
    params: list[object] = [f"%{term}%", f"%{term}%", f"%{term}%"]

    if digits:
        conditions.append("c.telefon_key LIKE ?")
        params.append(f"%{digits}%")

    where = " WHERE (" + " OR ".join(conditions) + ")"
    source = " FROM contacts c JOIN lists l ON l.id = c.list_id"

    matched = int(
        conn.execute("SELECT COUNT(*) AS total" + source + where, params).fetchone()[
            "total"
        ]
    )

    rows = list(
        conn.execute(
            "SELECT c.*, l.name AS list_name, l.archived AS list_archived,"
            + _CONTACT_MAIL
            + source
            + _CONTACT_MAIL_JOIN
            + where
            + " ORDER BY l.archived, c.betrieb, c.id"
            " LIMIT ? OFFSET ?",
            _state_params(cutoff) + params + [limit, offset],
        ).fetchall()
    )

    return rows, matched


# Die Vorrats-Zustände stehen hier als Text, weil dieses Modul die Schemata
# nicht kennt (`POOL_STATES` in `schemas/call_list.py` ist dieselbe Menge, und
# `test_call_list_service.py` hält beide zusammen). Die Rangfolge zwischen
# ihnen steht in `next_contact`.
#: Der Anrufvorrat: was auf dem Arbeitsplatz landen kann.
#:
#: Drei Zustände aus der Anrufliste — und seit dem Nachfassen ein vierter
#: Fall, der gar nicht aus ihr kommt: eine **Zusage, deren Mail fällig zum
#: Nachfassen ist**. Sie steht auf `zugesagt` und wäre nach der alten Regel
#: nie wieder vorgelegt worden; dass sie es wird, ist der ganze Zweck des
#: Reiters „Nachfassen" im Mailversand.
#:
#: Die Fälligkeit ist *nicht* noch einmal formuliert, sondern derselbe
#: Ausdruck, der sie in der Versandliste erzeugt (`_MAIL_STATE`): eine zweite
#: Fassung wäre die Stelle, an der Warteschlange und Versandliste
#: auseinanderlaufen. Der Preis sind die zwei Stichtage als `?` — sie stehen
#: vor allen anderen Parametern.
#:
#: Die Zeilen, die die lange Frist schon überschritten haben, fallen damit von
#: selbst wieder heraus: `_MAIL_STATE` liefert dort „keine Antwort", und was
#: abgeschrieben ist, gehört nicht an die Spitze der Warteschlange.
_POOL_FILTER = (
    " FROM contacts c"
    " JOIN lists l ON l.id = c.list_id"
    " LEFT JOIN mail_status m ON m.contact_id = c.id"
    " WHERE l.archived = 0 AND ("
    "   c.state IN ('rueckruf', 'offen', 'wiedervorlage')"
    f"   OR (c.state = 'zugesagt' AND {_MAIL_STATE} = 'nachfassen')"
    " )"
)

#: Was eine Kontaktzeile über den Versandstand mitbringt.
#:
#: Drei Spalten an jeder Abfrage, die einen `CallContact` liefert, damit der
#: Anrufer am Nachfass-Kontakt sieht, worum es geht: wann die Mail heraus
#: ging, was dazu notiert wurde, und ob sie gerade fällig ist. `followup_due`
#: kommt aus `_MAIL_STATE` und nicht aus einer Rechnung im Frontend — es ist
#: dieselbe Regel wie im Reiter „Nachfassen", und die soll es genau einmal
#: geben.
_CONTACT_MAIL = (
    " m.sent_at AS mail_sent_at, m.note AS mail_note,"
    f" ({_MAIL_STATE} = 'nachfassen') AS followup_due"
)

_CONTACT_MAIL_JOIN = " LEFT JOIN mail_status m ON m.contact_id = c.id"


def next_contact(
    conn: sqlite3.Connection, moment: str, cutoff: MailCutoffs
) -> sqlite3.Row | None:
    """Der nächste fällige Kontakt, oder `None`.

    Die Rangfolge ist Absicht:

    1. **vereinbarte Rückrufe**, früheste zuerst — dort wurde eine Zusage
       gemacht, die eingehalten werden muss.
    2. **Nachfassen**: Zusagen, deren Mail seit der Frist unbeantwortet ist,
       älteste Mail zuerst. Vor den Erstanrufen, weil dort schon jemand
       zugestimmt hat und die Mail nachweislich liegt — aber hinter den
       Rückrufen, denn die sind einer Person für eine Uhrzeit zugesagt.
    3. **noch nie angerufene** Kontakte in der Reihenfolge der Datei; ältere
       Listen zuerst.
    4. **Wiedervorlagen** — „nach hinten in die Liste" heißt: hinter alles,
       was noch nie versucht wurde.

    Der zweite Sortierschlüssel ist die Fälligkeit, für das Nachfassen das
    Versanddatum und für Gruppe 3 konstant leer, damit sie über Liste und
    Position sortiert.

    `due_at` gilt auch für die Nachfass-Gruppe: „niemanden erreicht" schiebt
    dort genauso auf, nur ohne den Zustand des Kontakts anzufassen — sonst
    fiele die Zusage aus dem Mailversand.
    """
    return conn.execute(
        "SELECT c.*, l.name AS list_name, l.archived AS list_archived,"
        + _CONTACT_MAIL
        + _POOL_FILTER
        + " AND (c.due_at IS NULL OR c.due_at <= ?)"
        " ORDER BY CASE"
        "     WHEN c.state = 'rueckruf' THEN 0"
        "     WHEN c.state = 'zugesagt' THEN 1"
        "     WHEN c.state = 'offen' THEN 2"
        "     ELSE 3 END,"
        "   CASE c.state"
        "     WHEN 'offen' THEN ''"
        "     WHEN 'zugesagt' THEN COALESCE(m.sent_at, '')"
        "     ELSE COALESCE(c.due_at, '') END,"
        "   l.created_at, c.position, c.id"
        " LIMIT 1",
        # Zweimal die Stichtage: einmal für die Spaltenliste, einmal für den
        # Vorrat selbst — beide enthalten `_MAIL_STATE`.
        _state_params(cutoff) * 2 + [moment],
    ).fetchone()


def next_due_at(
    conn: sqlite3.Connection, moment: str, cutoff: MailCutoffs
) -> str | None:
    """Wann der nächste aufgeschobene Kontakt zurückkommt.

    Aufgeschobene Nachfass-Kontakte zählen mit: „niemanden erreicht" schiebt
    auch sie auf, und „nichts zu tun, und jetzt?" wäre ohne sie falsch
    beantwortet.
    """
    row = conn.execute(
        "SELECT MIN(c.due_at) AS due" + _POOL_FILTER + " AND c.due_at > ?",
        _state_params(cutoff) + [moment],
    ).fetchone()

    return row["due"] if row and row["due"] else None


def followup_total(conn: sqlite3.Connection, cutoff: MailCutoffs) -> int:
    """Wie viele Zusagen gerade zum Nachfassen anstehen.

    Eigene Abfrage statt einer Gruppe in `state_totals`: die Zahl ist kein
    Kontaktzustand, sondern ein Versandstand — in der Spalte `state` steht
    bei diesen Zeilen weiter `zugesagt`, und dort soll sie auch mitzählen.
    Aufgeschobene bleiben draußen, aus demselben Grund wie bei `offen`: an
    einer Nummer, die erst in zwei Stunden wieder drankommt, arbeitet gerade
    niemand.
    """
    row = conn.execute(
        "SELECT COUNT(*) AS total"
        + _POOL_FILTER
        + " AND c.state = 'zugesagt' AND (c.due_at IS NULL OR c.due_at <= ?)",
        _state_params(cutoff) + [now()],
    ).fetchone()

    return int(row["total"])


def touch_mail_state(
    conn: sqlite3.Connection,
    contact_id: str,
    *,
    state: str,
    answered_at: str | None,
    followed_up_at: str | None,
    updated_by: str,
) -> None:
    """Nur den Versandstand und seine Zeitpunkte setzen.

    Das schmale Gegenstück zu `set_mail_status`: Anmerkung, Marker und
    Versanddatum bleiben unangetastet. Gebraucht vom Nachfass-Anruf, der über
    die Telefonakquise eingetragen wird — er sagt etwas über die Mail aus,
    aber nichts über die Einschätzung der Website, und er darf das
    Versanddatum nicht anfassen: die lange Frist läuft weiter ab dem Versand.

    Legt die Zeile an, falls es noch keine gibt. Vorkommen kann das nur über
    eine Richtigstellung, deren Zeile inzwischen zurückgesetzt wurde — dann
    ist eine Zeile ohne Versanddatum das ehrlichere Ergebnis als ein Fehler.
    """
    conn.execute(
        "INSERT INTO mail_status"
        " (contact_id, state, answered_at, followed_up_at, updated_at, updated_by)"
        " VALUES (?, ?, ?, ?, ?, ?)"
        " ON CONFLICT(contact_id) DO UPDATE SET"
        "   state = excluded.state,"
        "   answered_at = excluded.answered_at,"
        "   followed_up_at = excluded.followed_up_at,"
        "   updated_at = excluded.updated_at,"
        "   updated_by = excluded.updated_by",
        (contact_id, state, answered_at, followed_up_at, now(), updated_by),
    )


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


def latest_event_id(conn: sqlite3.Connection, contact_id: str) -> int | None:
    """Die jüngste Protokollzeile dieses Kontakts, oder `None`.

    Nur sie darf richtiggestellt werden — sie allein bestimmt den Zustand des
    Kontakts. Dieselbe Regel wie im Entscheidungs-Protokoll, hier gebraucht,
    damit eine geänderte Adresse auf die Zeile zeigen kann, die sie ersetzt.
    """
    row = conn.execute(
        "SELECT id FROM events WHERE contact_id = ? ORDER BY id DESC LIMIT 1",
        (contact_id,),
    ).fetchone()

    return None if row is None else int(row["id"])


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
#: Die Tabellen dahinter. `lists` und `contacts` hängen per LEFT JOIN daran:
#: eine Protokollzeile liest sich aus sich selbst (`betrieb`/`telefon` stehen
#: darin), die beiden Joins liefern nur das Umfeld — und der Ziffernschlüssel,
#: über den die Suche eine Nummer findet.
_EVENT_FROM = (
    " FROM events e"
    " LEFT JOIN lists l ON l.id = e.list_id"
    " LEFT JOIN contacts c ON c.id = e.contact_id"
)

_EVENT_CONTEXT = (
    " e.*, l.name AS list_name, l.archived AS list_archived,"
    " c.state AS contact_state,"
    " (SELECT MAX(later.id) FROM events later"
    "   WHERE later.contact_id = e.contact_id) AS latest_event_id,"
    " (SELECT COUNT(*) FROM events fix"
    "   WHERE fix.corrects_event_id = e.id) AS correction_count" + _EVENT_FROM
)


def _event_filter(query: str) -> tuple[str, list[object]]:
    """Ein Suchbegriff als WHERE über das Protokoll, plus seine Parameter.

    Dieselben Felder wie die Kontakt- und die Versandsuche — Betrieb, Adresse,
    Nummer —, damit sich die Suchen dieser Anwendung nicht unterschiedlich
    verhalten. Gesucht wird in der *Protokollzeile*: `betrieb`, `telefon` und
    `email` stehen darin und sind der Stand von damals, was hier genau richtig
    ist (unter welcher Nummer wurde angerufen, an welche Adresse ging die
    Zusage). Nur der Ziffernschlüssel kommt vom Kontakt, weil er dort schon
    normalisiert liegt.

    Ein leerer Begriff filtert nicht — dann ist es die gewöhnliche Liste der
    letzten Eintragungen und keine Suche.
    """
    term = query.strip()

    if not term:
        return "", []

    # Der Ziffernschlüssel wie in der Kontaktsuche, damit „+49 5221 111"
    # dieselbe Nummer findet wie „05221111".
    digits = phone_key(term)
    conditions = ["e.betrieb LIKE ?", "e.email LIKE ?", "e.telefon LIKE ?"]
    params: list[object] = [f"%{term}%", f"%{term}%", f"%{term}%"]

    if digits:
        conditions.append("c.telefon_key LIKE ?")
        params.append(f"%{digits}%")

    return " WHERE (" + " OR ".join(conditions) + ")", params


def recent_events(
    conn: sqlite3.Connection, *, limit: int, offset: int, query: str = ""
) -> list[sqlite3.Row]:
    """Die zuletzt eingetragenen Entscheidungen, jüngste zuerst.

    Über die AUTOINCREMENT-ID sortiert und nicht über `occurred_at`: zwei
    Einträge derselben Sekunde hätten denselben Zeitstempel, und eine
    Korrektur würde dann womöglich *über* der Zeile stehen, die sie
    richtigstellt.

    Mit `query` ist es dieselbe Liste, nur auf einen Betrieb eingegrenzt: die
    Suche der Seite geht durch *dieses* Fenster, weil hier auch das Ändern
    hängt. Die Sortierung bleibt die gleiche — die jüngste Eintragung eines
    Betriebs ist die, an der noch etwas geht, und sie steht damit oben.
    """
    where, params = _event_filter(query)

    return list(
        conn.execute(
            "SELECT" + _EVENT_CONTEXT + where + " ORDER BY e.id DESC LIMIT ? OFFSET ?",
            params + [limit, offset],
        ).fetchall()
    )


def events_total(conn: sqlite3.Connection, query: str = "") -> int:
    """Wie viele Eintragungen es gibt — mit `query` die Zahl der Treffer.

    Zählt über dieselben Joins wie `recent_events`, weil der Ziffernschlüssel
    am Kontakt hängt. Ohne Begriff ist es das ganze Protokoll.
    """
    where, params = _event_filter(query)

    row = conn.execute(
        "SELECT COUNT(*) AS total" + _EVENT_FROM + where, params
    ).fetchone()

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


# --------------------------------------------------------------------------
# Mailversand
# --------------------------------------------------------------------------


# Die beiden Stichtage und der Ausdruck, der den Versandstand berechnet
# (`MailCutoffs`, `_MAIL_STATE`, `_state_params`), stehen weiter oben: seit
# der Anrufvorrat die Nachfass-Fälligen nach vorne holt, gehören sie nicht
# mehr allein diesem Abschnitt.


#: Die Zusagen und sonst nichts. Archivierte Listen zählen mit: eine Zusage
#: gilt weiter, auch wenn die Anrufrunde beendet ist, und die Mail muss
#: trotzdem heraus.
#: Die Bau-Einschätzung, wie sie jede Abfrage liest.
#:
#: Dieselbe Regel wie beim Versandstand: der Ausgangswert braucht keinen
#: Eintrag. NULL steht in zwei Fällen dort — die Zeile ist älter als die
#: Spalte, oder niemand hat die Website angesehen —, und beide bedeuten
#: dasselbe.
#:
#: Der Ausdruck wird überall ausgeschrieben und nie über seinen Alias
#: angesprochen: ein `GROUP BY readiness` hätte in SQLite die *Spalte*
#: `m.build_readiness` treffen können und damit NULL als eigene Gruppe
#: gezählt — deshalb heißt der Alias auch nicht wie die Spalte.
#:
#: **Sie gilt nur, solange die Mail nicht heraus ist**, und ergibt sonst
#: NULL: „Ready to Mail" heißt „gebaut, muss noch zum Betrieb", und neben
#: einem Versandstand „verschickt" wäre das eine Auskunft, die sich selbst
#: widerspricht. Die ganze Reihe ist ein Weg *bis* zur Mail — danach
#: beantwortet der Reiter „Verschickt" dieselbe Frage besser.
#:
#: NULL und nicht `'unbewertet'`, obwohl beides „kein Marker an der Zeile"
#: ergäbe: eine verschickte Zusage soll auch nicht unter „nicht
#: eingeschätzt" auftauchen. NULL fällt aus jedem `GROUP BY`-Zähler heraus,
#: den die Oberfläche kennt, und aus jedem `= ?`-Filter — die Regel steht
#: damit an *einer* Stelle statt in jeder Abfrage noch einmal.
#:
#: Gelesen wird der gespeicherte Wert weiterhin über `stored_readiness`
#: (siehe `_MAIL_SELECT`): er bleibt stehen und kommt zurück, sobald der
#: Versand zurückgesetzt wird.
_MAIL_READINESS = (
    "CASE WHEN COALESCE(m.state, 'offen') = 'offen'"
    "     THEN COALESCE(m.build_readiness, 'unbewertet') END"
)

#: Der Umfangs-Marker, wie ihn jede Abfrage liest.
#:
#: Dritte Größe und die einzige, die *neben* den anderen beiden steht statt
#: in ihnen: gefiltert und gezählt wird sie eigenständig, gesetzt wird sie
#: unabhängig. NULL und 0 sind dasselbe („niemand hat das gesagt"), weil die
#: Spalte nachträglich dazugekommen ist und jede Zeile von vorher NULL trägt.
#:
#: Der Alias heißt aus demselben Grund wie oben nicht wie die Spalte.
_MAIL_OVERSIZED = "COALESCE(m.oversized, 0)"

_MAIL_FROM = (
    " FROM contacts c"
    " JOIN lists l ON l.id = c.list_id"
    " LEFT JOIN mail_status m ON m.contact_id = c.id"
    " WHERE c.state = 'zugesagt'"
)

#: Spalten einer Zeile der Versandliste. `promised_at`/`promised_by` kommen
#: aus dem Protokoll — es ist der Nachweis, auf den sich der Versand stützt,
#: und gehört deshalb neben die Adresse und nicht in eine zweite Abfrage.
#:
#: `prio`, `befunde` und `extras` stehen mit darin, obwohl die Liste sie
#: nirgends anzeigt: sie sind das, was die Zeile zum Kopieren hergibt (die
#: freien Spalten der Analyse, aus der die Anrufliste kam). Ein zweiter
#: Aufruf je Zeile wäre der Alternativweg — für ein paar hundert Byte pro
#: Zusage nicht die Mühe wert.
_MAIL_SELECT = (
    " c.id AS contact_id, c.betrieb, c.telefon, c.email, c.ort, c.plz,"
    " c.website, c.gewerk, c.prio, c.befunde, c.extras,"
    " c.note, c.list_id, l.name AS list_name,"
    " l.archived AS list_archived, COALESCE(l.manual, 0) AS list_manual,"
    " m.state AS stored_state, m.build_readiness AS stored_readiness,"
    " m.sent_at, m.answered_at, m.followed_up_at,"
    " m.note AS mail_note, m.updated_at AS mail_updated_at,"
    " m.updated_by AS mail_updated_by,"
    " (SELECT e.occurred_at FROM events e"
    "   WHERE e.contact_id = c.id AND e.outcome = 'zugesagt'"
    "   ORDER BY e.id DESC LIMIT 1) AS promised_at,"
    " (SELECT e.username FROM events e"
    "   WHERE e.contact_id = c.id AND e.outcome = 'zugesagt'"
    "   ORDER BY e.id DESC LIMIT 1) AS promised_by,"
    f" {_MAIL_STATE} AS mail_state,"
    f" {_MAIL_READINESS} AS readiness,"
    f" {_MAIL_OVERSIZED} AS oversized_flag"
)

#: Reihenfolge der Liste: erst was zu tun ist, dann was wartet, dann was
#: erledigt ist. Innerhalb einer Gruppe die Reihenfolge der Datei (ältere
#: Listen zuerst) — dieselbe, in der auch angerufen wurde.
_MAIL_ORDER = (
    " ORDER BY CASE mail_state"
    "     WHEN 'offen' THEN 0"
    "     WHEN 'nachfassen' THEN 1"
    "     WHEN 'keine_antwort' THEN 2"
    "     WHEN 'nachgefasst' THEN 3"
    "     WHEN 'versendet' THEN 4"
    "     WHEN 'positiv' THEN 5"
    "     ELSE 6 END,"
    "   l.created_at, c.position, c.id"
)


def _mail_filter(
    query: str,
    state: str | None,
    readiness: str | None,
    oversized: bool | None,
    cutoff: MailCutoffs,
) -> tuple[str, list[object]]:
    """Suche, Versandstand, Bau-Einschätzung und Umfang als SQL plus Parameter.

    Die Suche geht über Betrieb, Adresse und Nummer: gesucht wird mal nach dem
    Betrieb, von dem gerade eine Antwort kam, mal nach der Adresse aus dem
    Postfach. Zustand, Einschätzung und Umfang sind *unabhängige* Filter —
    „was ist verschickt", „was können wir bauen" und „was ist größer als ein
    Onepager" sind drei Fragen, und zusammen ergeben sie die vierte
    („verschickt, in Arbeit und größer als gedacht").

    Gibt die Parameter **vollständig** und in der Reihenfolge der Bedingungen
    zurück, die Stichtage des Zustandsfilters eingeschlossen. Vorher hat der
    Aufrufer sie selbst dazwischengeschoben — bei zwei Filtern wäre diese
    Fädelarbeit die nächste Fehlerquelle.
    """
    where = ""
    params: list[object] = []
    term = query.strip()

    if term:
        digits = phone_key(term)
        conditions = ["c.betrieb LIKE ?", "c.email LIKE ?", "c.telefon LIKE ?"]
        params += [f"%{term}%", f"%{term}%", f"%{term}%"]
        if digits:
            conditions.append("c.telefon_key LIKE ?")
            params.append(f"%{digits}%")
        where += " AND (" + " OR ".join(conditions) + ")"

    if state:
        # Die Stichtage ein zweites Mal: gefiltert wird über den *gerechneten*
        # Zustand, sonst zeigte der Filter „keine Antwort" nur die von Hand
        # abgeschlossenen Zeilen — und „nachfassen" wäre überhaupt nicht
        # filterbar, weil es diesen Wert in der Spalte nie gibt.
        where += f" AND {_MAIL_STATE} = ?"
        params += _state_params(cutoff) + [state]

    if readiness:
        # Verschickte Zusagen fallen hier von selbst heraus: `_MAIL_READINESS`
        # ist für sie NULL, und NULL ist nie gleich irgendetwas. Die Regel
        # steht damit nur an dem einen Ort, an dem sie formuliert ist.
        where += f" AND {_MAIL_READINESS} = ?"
        params.append(readiness)

    if oversized is not None:
        where += f" AND {_MAIL_OVERSIZED} = ?"
        params.append(1 if oversized else 0)

    return where, params


def mail_page(
    conn: sqlite3.Connection,
    *,
    cutoff: MailCutoffs,
    query: str = "",
    state: str | None = None,
    readiness: str | None = None,
    oversized: bool | None = None,
    limit: int,
    offset: int,
) -> tuple[list[sqlite3.Row], int, int]:
    """Ein Ausschnitt der Versandliste, plus Treffer und Gesamtzahl.

    `cutoff` sind die beiden Zeitpunkte, vor denen ein Versand fällig wird
    (jetzt minus der jeweiligen Frist). Sie werden durchgereicht statt hier
    gerechnet, damit Liste, Zähler und Schreibpfad einer Anfrage dieselben
    Stichtage benutzen — sonst könnte eine Zeile zwischen zwei Abfragen
    derselben Antwort die Gruppe wechseln.
    """
    where, filter_params = _mail_filter(query, state, readiness, oversized, cutoff)

    total = int(
        conn.execute("SELECT COUNT(*) AS total" + _MAIL_FROM, ()).fetchone()["total"]
    )

    matched = int(
        conn.execute(
            "SELECT COUNT(*) AS total" + _MAIL_FROM + where,
            filter_params,
        ).fetchone()["total"]
    )

    rows = list(
        conn.execute(
            "SELECT"
            + _MAIL_SELECT
            + _MAIL_FROM
            + where
            + _MAIL_ORDER
            + " LIMIT ? OFFSET ?",
            # Die Stichtage zuerst: sie stehen in den `?` der Spaltenliste,
            # die Filterparameter dahinter in der Reihenfolge ihrer
            # Bedingungen.
            _state_params(cutoff) + filter_params + [limit, offset],
        ).fetchall()
    )

    return rows, matched, total


def mail_totals(
    conn: sqlite3.Connection,
    cutoff: MailCutoffs,
    readiness: str | None = None,
    oversized: bool | None = None,
) -> dict[str, tuple[int, int]]:
    """Pro Versandzustand: (Anzahl, davon ohne E-Mail-Adresse).

    Eine Abfrage für die Zähler der Reiterzeile. Die **Suche** bleibt
    ausdrücklich außen vor: die Reiter beantworten „wo stehe ich insgesamt",
    nicht „wie viele Zeilen sehe ich gerade".

    Die *anderen* Filter zählen dagegen mit. Die Oberfläche hat drei
    Filtergrößen, und jede zeigt ihre Zahlen mit den Filtern der anderen,
    aber ohne den eigenen — das ist der einzige Zuschnitt, in dem eine Reihe
    eine Aufteilung zeigt, deren Summe die Liste auch erreicht. Ohne den
    eigenen Filter, weil sonst auf allen Marken außer der angeklickten eine
    Null stünde. Dieselbe Regel in `mail_readiness_totals` und
    `mail_oversized_total`.
    """
    where, params = _mail_filter("", None, readiness, oversized, cutoff)

    rows = conn.execute(
        f"SELECT {_MAIL_STATE} AS mail_state, COUNT(*) AS total,"
        " SUM(CASE WHEN c.email = '' THEN 1 ELSE 0 END) AS ohne_email"
        + _MAIL_FROM
        + where
        + " GROUP BY mail_state",
        # Die Stichtage zuerst: sie stehen in den `?` der Spaltenliste, die
        # Filterparameter dahinter — wie in `mail_page`.
        _state_params(cutoff) + params,
    ).fetchall()

    return {
        row["mail_state"]: (int(row["total"]), int(row["ohne_email"] or 0))
        for row in rows
    }


def mail_readiness_totals(
    conn: sqlite3.Connection,
    cutoff: MailCutoffs,
    state: str | None = None,
    oversized: bool | None = None,
) -> dict[str, int]:
    """Pro Bau-Einschätzung: die Anzahl der Zusagen.

    Eigene Abfrage und nicht in `mail_totals` hineingerechnet: eine
    Gruppierung über beide Größen gäbe zwanzig Zeilen, aus denen die Zähler
    wieder zusammenzusummieren wären — und die beiden Reihen brauchen
    verschiedene Filter, siehe dort.

    `state` ist hier dieser andere Filter: steht die Reiterzeile auf „Offen",
    zählt diese Reihe innerhalb der offenen Zusagen, und ihre Zahlen ergeben
    zusammen die Zahl auf dem Reiter. Der Stichtag wird deshalb auch
    hier gebraucht — gefiltert wird über den *gerechneten* Zustand, nicht
    über die Spalte.
    """
    where, params = _mail_filter("", state, None, oversized, cutoff)

    rows = conn.execute(
        f"SELECT {_MAIL_READINESS} AS readiness, COUNT(*) AS total"
        + _MAIL_FROM
        + where
        + f" GROUP BY {_MAIL_READINESS}",
        params,
    ).fetchall()

    # Ohne die NULL-Gruppe: das sind die Zeilen, deren Mail heraus ist, und
    # für die gibt es keine Marke, auf der die Zahl stehen könnte.
    return {
        row["readiness"]: int(row["total"])
        for row in rows
        if row["readiness"] is not None
    }


def mail_oversized_total(
    conn: sqlite3.Connection,
    cutoff: MailCutoffs,
    state: str | None = None,
    readiness: str | None = None,
) -> int:
    """Wie viele Zusagen größer als ein Onepager sind.

    Eine Zahl und keine Aufteilung: der Marker ist gesetzt oder nicht, und
    „nicht gesetzt" ist keine Aussage, sondern deren Fehlen — es gibt hier
    also nichts zu gruppieren.

    Wie die beiden Reihen über ihr zählt sie mit den Filtern der *anderen*
    Größen und ohne den eigenen: sonst stünde auf der einen Marke, die es
    gibt, entweder die Gesamtzahl oder die Zahl der Liste, und ein Rückweg
    wäre es in beiden Fällen nicht.
    """
    where, params = _mail_filter("", state, readiness, True, cutoff)

    return int(
        conn.execute(
            "SELECT COUNT(*) AS total" + _MAIL_FROM + where, params
        ).fetchone()["total"]
    )


def find_mail_entry(
    conn: sqlite3.Connection, contact_id: str, cutoff: MailCutoffs
) -> sqlite3.Row | None:
    """Eine Zeile der Versandliste, oder `None`.

    `None` heißt zweierlei: den Kontakt gibt es nicht — oder er steht nicht
    (mehr) auf „Zusage". Beides beantwortet der Service mit derselben
    Meldung, weil beides denselben Grund hat: hier ist nichts mehr zu tun.
    """
    return conn.execute(
        "SELECT" + _MAIL_SELECT + _MAIL_FROM + " AND c.id = ?",
        _state_params(cutoff) + [contact_id],
    ).fetchone()


def all_mail_entries(
    conn: sqlite3.Connection, cutoff: MailCutoffs
) -> list[sqlite3.Row]:
    """Die ganze Versandliste — für die Ausgabe."""
    return list(
        conn.execute(
            "SELECT" + _MAIL_SELECT + _MAIL_FROM + _MAIL_ORDER,
            _state_params(cutoff),
        ).fetchall()
    )


def set_mail_status(
    conn: sqlite3.Connection,
    contact_id: str,
    *,
    state: str,
    sent_at: str | None,
    answered_at: str | None,
    followed_up_at: str | None,
    note: str,
    readiness: str,
    oversized: bool,
    updated_by: str,
) -> None:
    """Den Versandzustand setzen. Legt die Zeile an, wenn es noch keine gibt.

    Ein Zurücksetzen auf `offen` löscht die Zeile bewusst **nicht**: dann
    stünde dort niemand mehr, der es getan hat. Die Zeile bleibt und trägt
    `offen` mit leerem Versanddatum — der Unterschied zwischen „noch nichts
    passiert" und „zurückgesetzt von Marie" ist genau das, wonach jemand
    fragt, der die Liste morgen ansieht.

    Jedes Feld wird geschrieben, auch Bau-Einschätzung und Umfang: was
    „unverändert" heißt, löst der Service auf. Diese Funktion kennt nur einen Endstand —
    sonst gäbe es hier je Feld ein „oder so lassen", und ein Klick auf einen
    Versand-Knopf würde still einen Marker verwerfen.
    """
    conn.execute(
        "INSERT INTO mail_status"
        " (contact_id, state, sent_at, answered_at, followed_up_at, note,"
        "  build_readiness, oversized, updated_at, updated_by)"
        " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"
        " ON CONFLICT(contact_id) DO UPDATE SET"
        "   state = excluded.state,"
        "   sent_at = excluded.sent_at,"
        "   answered_at = excluded.answered_at,"
        "   followed_up_at = excluded.followed_up_at,"
        "   note = excluded.note,"
        "   build_readiness = excluded.build_readiness,"
        "   oversized = excluded.oversized,"
        "   updated_at = excluded.updated_at,"
        "   updated_by = excluded.updated_by",
        (
            contact_id,
            state,
            sent_at,
            answered_at,
            followed_up_at,
            note,
            readiness,
            1 if oversized else 0,
            now(),
            updated_by,
        ),
    )
