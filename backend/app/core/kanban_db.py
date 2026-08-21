"""SQLite persistence for the kanban board — the only module with SQL in it.

Why SQLite and not a JSON file: the board is edited by several people at once,
and row-level updates mean two simultaneous drags of different cards do not
overwrite each other. It is also stdlib, so nothing was added to
requirements.txt.

Where the file lives: `KANBAN_DB_PATH`, relative by default, which makes one
value work everywhere — `backend/data/kanban.db` when uvicorn runs from
`backend/`, and `/app/data/kanban.db` in the container (WORKDIR is `/app`).
In production that path must be a mounted volume, otherwise the board is gone
with the next image rebuild.
"""

import os
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator, Sequence

DEFAULT_DB_PATH = "data/kanban.db"

# Waited out by SQLite when another connection holds the write lock, instead of
# failing with "database is locked" straight away.
BUSY_TIMEOUT_MS = 5000

SCHEMA_VERSION = "1"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS cards (
    id          TEXT    PRIMARY KEY,
    column_id   TEXT    NOT NULL,
    position    INTEGER NOT NULL,
    title       TEXT    NOT NULL,
    description TEXT    NOT NULL DEFAULT '',
    created_at  TEXT    NOT NULL,
    updated_at  TEXT    NOT NULL,
    created_by  TEXT    NOT NULL DEFAULT ''
);

CREATE INDEX IF NOT EXISTS idx_cards_column ON cards (column_id, position);

CREATE TABLE IF NOT EXISTS labels (
    id         TEXT    PRIMARY KEY,
    name       TEXT    NOT NULL,
    name_key   TEXT    NOT NULL UNIQUE,
    color      TEXT    NOT NULL,
    created_at TEXT    NOT NULL,
    archived   INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS card_labels (
    card_id  TEXT NOT NULL REFERENCES cards (id)  ON DELETE CASCADE,
    label_id TEXT NOT NULL REFERENCES labels (id) ON DELETE CASCADE,
    PRIMARY KEY (card_id, label_id)
);

CREATE INDEX IF NOT EXISTS idx_card_labels_label ON card_labels (label_id);

CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""


def db_path() -> Path:
    """Resolve the database path *now*, not at import time.

    The modules around `upload_api.py` capture `today` at import time and go
    stale after midnight; reading the environment per call keeps this testable
    (a tmp_path per test) and avoids the same trap.
    """
    return Path(os.getenv("KANBAN_DB_PATH", DEFAULT_DB_PATH))


def now() -> str:
    """Current UTC timestamp as ISO-8601 text.

    SQLite has no date type; ISO-8601 text sorts and compares correctly.
    """
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def new_id() -> str:
    return str(uuid.uuid4())


def name_key(name: str) -> str:
    """Normalised label name used for the duplicate check.

    Not `COLLATE NOCASE`: SQLite's built-in version only folds ASCII A-Z, so
    "Ärzte am Ring" and "ärzte am ring" would end up as two customers.
    `casefold()` handles umlauts.
    """
    return " ".join(name.split()).casefold()


@contextmanager
def connect() -> Iterator[sqlite3.Connection]:
    """Open a connection for the duration of one request.

    A connection per call rather than a shared one: sync FastAPI handlers run
    in a threadpool and `sqlite3` connections are not thread-safe. Opening one
    is cheap.
    """
    path = db_path()
    if path.parent != Path(""):
        path.parent.mkdir(parents=True, exist_ok=True)

    # isolation_level=None turns off the implicit transaction handling of the
    # driver, so the BEGIN IMMEDIATE below is the only transaction control.
    conn = sqlite3.connect(path, isolation_level=None)
    conn.row_factory = sqlite3.Row
    # WAL lets readers work while a writer holds the lock, and keeps a future
    # `uvicorn --workers N` safe (a JSON file would not be).
    conn.execute("PRAGMA journal_mode = WAL")
    # Off by default in SQLite — without it the ON DELETE CASCADE above is
    # documentation and card_labels keeps orphan rows.
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute(f"PRAGMA busy_timeout = {BUSY_TIMEOUT_MS}")

    try:
        yield conn
    finally:
        conn.close()


@contextmanager
def transaction(conn: sqlite3.Connection) -> Iterator[sqlite3.Connection]:
    """Wrap a write in one atomic step.

    IMMEDIATE takes the write lock up front instead of upgrading halfway
    through, which is what would otherwise turn two concurrent moves into a
    "database is locked" error.
    """
    conn.execute("BEGIN IMMEDIATE")
    try:
        yield conn
    except Exception:
        conn.execute("ROLLBACK")
        raise
    conn.execute("COMMIT")


def init_schema() -> None:
    """Create the tables if they are missing. Idempotent.

    Called from the app lifespan in `main.py` and from the test fixture.
    """
    with connect() as conn:
        conn.executescript(_SCHEMA)
        conn.execute(
            "INSERT OR IGNORE INTO meta (key, value) VALUES ('schema_version', ?)",
            (SCHEMA_VERSION,),
        )
        conn.execute("INSERT OR IGNORE INTO meta (key, value) VALUES ('revision', '0')")


# --------------------------------------------------------------------------
# revision
# --------------------------------------------------------------------------


def revision(conn: sqlite3.Connection) -> int:
    row = conn.execute("SELECT value FROM meta WHERE key = 'revision'").fetchone()
    return int(row["value"]) if row else 0


def bump_revision(conn: sqlite3.Connection) -> int:
    """Raise the board revision. Must run inside the same transaction as the write."""
    conn.execute(
        "UPDATE meta SET value = CAST(CAST(value AS INTEGER) + 1 AS TEXT)"
        " WHERE key = 'revision'"
    )
    return revision(conn)


# --------------------------------------------------------------------------
# cards
# --------------------------------------------------------------------------


def all_cards(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return list(
        conn.execute(
            "SELECT * FROM cards ORDER BY column_id, position, created_at"
        ).fetchall()
    )


def card_exists(conn: sqlite3.Connection, card_id: str) -> bool:
    return (
        conn.execute("SELECT 1 FROM cards WHERE id = ?", (card_id,)).fetchone()
        is not None
    )


def _ordered_ids(conn: sqlite3.Connection, column_id: str) -> list[str]:
    return [
        row["id"]
        for row in conn.execute(
            "SELECT id FROM cards WHERE column_id = ? ORDER BY position, created_at",
            (column_id,),
        )
    ]


def _write_positions(conn: sqlite3.Connection, ids: Sequence[str]) -> None:
    """Renumber a column densely from 0 in the order given.

    There is no UNIQUE constraint on (column_id, position) on purpose —
    renumbering passes through colliding intermediate states.
    """
    conn.executemany(
        "UPDATE cards SET position = ? WHERE id = ?",
        [(index, card_id) for index, card_id in enumerate(ids)],
    )


def insert_card(
    conn: sqlite3.Connection,
    *,
    card_id: str,
    column_id: str,
    title: str,
    description: str,
    created_by: str,
) -> None:
    """Add a card at the top of its column."""
    timestamp = now()
    conn.execute(
        "UPDATE cards SET position = position + 1 WHERE column_id = ?", (column_id,)
    )
    conn.execute(
        "INSERT INTO cards"
        " (id, column_id, position, title, description, created_at, updated_at, created_by)"
        " VALUES (?, ?, 0, ?, ?, ?, ?, ?)",
        (card_id, column_id, title, description, timestamp, timestamp, created_by),
    )


def update_card(
    conn: sqlite3.Connection,
    card_id: str,
    *,
    title: str | None,
    description: str | None,
) -> None:
    """Write only the fields that were given."""
    assignments = []
    values: list[str] = []

    if title is not None:
        assignments.append("title = ?")
        values.append(title)
    if description is not None:
        assignments.append("description = ?")
        values.append(description)

    assignments.append("updated_at = ?")
    values.append(now())
    values.append(card_id)

    conn.execute(f"UPDATE cards SET {', '.join(assignments)} WHERE id = ?", values)


def delete_card(conn: sqlite3.Connection, card_id: str) -> bool:
    row = conn.execute(
        "SELECT column_id FROM cards WHERE id = ?", (card_id,)
    ).fetchone()
    if row is None:
        return False

    # card_labels rows go with it via ON DELETE CASCADE (needs the pragma).
    conn.execute("DELETE FROM cards WHERE id = ?", (card_id,))
    _write_positions(conn, _ordered_ids(conn, row["column_id"]))
    return True


def move_card(
    conn: sqlite3.Connection, card_id: str, column_id: str, position: int
) -> bool:
    """Move a card to `position` in `column_id` and renumber what it touched.

    `position` is clamped instead of rejected: on a cross-column drop
    sortablejs can report an index that no longer exists once the card has been
    taken out of its old column.
    """
    row = conn.execute(
        "SELECT column_id FROM cards WHERE id = ?", (card_id,)
    ).fetchone()
    if row is None:
        return False

    source = row["column_id"]

    if source == column_id:
        ids = _ordered_ids(conn, column_id)
        ids.remove(card_id)
        # Remove first, then insert — otherwise dragging a card down by one
        # position is a no-op.
        ids.insert(min(position, len(ids)), card_id)
        _write_positions(conn, ids)
    else:
        source_ids = _ordered_ids(conn, source)
        source_ids.remove(card_id)

        target_ids = _ordered_ids(conn, column_id)
        target_ids.insert(min(position, len(target_ids)), card_id)

        conn.execute(
            "UPDATE cards SET column_id = ? WHERE id = ?", (column_id, card_id)
        )
        _write_positions(conn, source_ids)
        _write_positions(conn, target_ids)

    conn.execute("UPDATE cards SET updated_at = ? WHERE id = ?", (now(), card_id))
    return True


# --------------------------------------------------------------------------
# labels
# --------------------------------------------------------------------------


def all_labels(
    conn: sqlite3.Connection, *, include_archived: bool = False
) -> list[sqlite3.Row]:
    query = "SELECT * FROM labels"
    if not include_archived:
        query += " WHERE archived = 0"
    query += " ORDER BY name_key"
    return list(conn.execute(query).fetchall())


def find_label(conn: sqlite3.Connection, label_id: str) -> sqlite3.Row | None:
    return conn.execute("SELECT * FROM labels WHERE id = ?", (label_id,)).fetchone()


def find_label_by_name(conn: sqlite3.Connection, name: str) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT * FROM labels WHERE name_key = ?", (name_key(name),)
    ).fetchone()


def existing_label_ids(conn: sqlite3.Connection, label_ids: Sequence[str]) -> set[str]:
    if not label_ids:
        return set()

    placeholders = ", ".join("?" * len(label_ids))
    return {
        row["id"]
        for row in conn.execute(
            f"SELECT id FROM labels WHERE id IN ({placeholders})", tuple(label_ids)
        )
    }


def color_usage(conn: sqlite3.Connection) -> dict[str, int]:
    """How often each palette colour is already taken, archived ones included."""
    return {
        row["color"]: row["total"]
        for row in conn.execute(
            "SELECT color, COUNT(*) AS total FROM labels GROUP BY color"
        )
    }


def insert_label(
    conn: sqlite3.Connection, *, label_id: str, name: str, color: str
) -> None:
    conn.execute(
        "INSERT INTO labels (id, name, name_key, color, created_at, archived)"
        " VALUES (?, ?, ?, ?, ?, 0)",
        (label_id, name, name_key(name), color, now()),
    )


def update_label(
    conn: sqlite3.Connection,
    label_id: str,
    *,
    name: str | None,
    color: str | None,
    archived: bool | None,
) -> None:
    assignments = []
    values: list[object] = []

    if name is not None:
        assignments.extend(["name = ?", "name_key = ?"])
        values.extend([name, name_key(name)])
    if color is not None:
        assignments.append("color = ?")
        values.append(color)
    if archived is not None:
        assignments.append("archived = ?")
        values.append(1 if archived else 0)

    if not assignments:
        return

    values.append(label_id)
    conn.execute(f"UPDATE labels SET {', '.join(assignments)} WHERE id = ?", values)


def label_usage_count(conn: sqlite3.Connection, label_id: str) -> int:
    row = conn.execute(
        "SELECT COUNT(*) AS total FROM card_labels WHERE label_id = ?", (label_id,)
    ).fetchone()
    return int(row["total"])


def delete_label(conn: sqlite3.Connection, label_id: str) -> None:
    """Remove a label. Its card assignments go with it via ON DELETE CASCADE."""
    conn.execute("DELETE FROM labels WHERE id = ?", (label_id,))


# --------------------------------------------------------------------------
# card <-> label
# --------------------------------------------------------------------------


def labels_by_card(conn: sqlite3.Connection) -> dict[str, list[sqlite3.Row]]:
    """All assignments in one query, so building the board needs no N+1."""
    grouped: dict[str, list[sqlite3.Row]] = {}

    for row in conn.execute(
        "SELECT cl.card_id AS card_id, l.* FROM card_labels cl"
        " JOIN labels l ON l.id = cl.label_id"
        " ORDER BY l.name_key"
    ):
        grouped.setdefault(row["card_id"], []).append(row)

    return grouped


def set_card_labels(
    conn: sqlite3.Connection, card_id: str, label_ids: Sequence[str]
) -> None:
    """Replace the whole label set of a card."""
    conn.execute("DELETE FROM card_labels WHERE card_id = ?", (card_id,))

    if label_ids:
        conn.executemany(
            "INSERT OR IGNORE INTO card_labels (card_id, label_id) VALUES (?, ?)",
            [(card_id, label_id) for label_id in dict.fromkeys(label_ids)],
        )
