"""Fachregeln der Telefonakquise.

Zwei Rollen treffen hier aufeinander:

* **Wer anruft** bekommt genau *einen* Kontakt zu sehen, trägt das Ergebnis
  ein und bekommt den nächsten. Mehr braucht er nicht, und mehr soll er auch
  nicht sehen: eine Liste mit 104 Betrieben, in der man selbst die Stelle
  suchen muss, ist genau das Werkzeug, das dieses hier ersetzt.
* **Wer die Liste pflegt** (Administrator) lädt die CSV hoch, sieht die Zahlen
  pro Liste, legt Listen still und holt die Zusagen als Datei heraus.

Wie beim Kanban-Board antwortet jeder schreibende Aufruf mit dem **ganzen**
Arbeitsstand (`CallState`). Das sind ein paar Kilobyte und erspart die
Buchhaltung darüber, ob der Zähler im Browser noch zu dem in der Datenbank
passt.

Zeitpunkte: der Browser schickt vollständige ISO-8601-Zeitstempel mit
Zeitzone, hier wird in UTC umgerechnet und nur UTC gespeichert. Damit braucht
der Container keine Zeitzonendatenbank, und „morgen früh" bedeutet den Morgen
dessen, der anruft.
"""

import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from io import BytesIO

from app.core import call_list_db as db
from app.core.call_list_csv import (
    FIELD_LABELS,
    FIELD_NAMES,
    MAX_FILE_BYTES,
    MAX_ROWS,
    CallCsvError,
    CallCsvResult,
    CallRecord,
)
from app.core.call_list_csv import parse_csv as parse_call_csv
from app.core.csv_utils import csv_rows_to_str
from app.schemas.call_list import (
    CALLBACK_LEAD_MINUTES,
    MAX_EMAIL,
    MAX_LIST_NAME,
    MAX_SNOOZE_MINUTES,
    MIN_SNOOZE_MINUTES,
    OUTCOME_STATES,
    OUTCOMES,
    STATE_LABELS,
    CallContact,
    CallCounters,
    CallEventInfo,
    CallListInfo,
    CallOutcome,
    CallState,
    ColumnMappingInfo,
    ContactField,
    ContactState,
    ListAnalyseResponse,
    ListImportResponse,
    ListUpdateRequest,
    OutcomeRequest,
    SkippedRowInfo,
)


class CallListError(Exception):
    """Alles, was der Anwender selbst beheben kann → 400."""


class CallListNotFoundError(CallListError):
    """Kontakt oder Liste existiert nicht → 404."""


class CallListConflictError(CallListError):
    """Doppelter Listenname, oder eine Liste mit Protokoll → 409."""


@dataclass
class CallListExport:
    """Fertige Datei, bereit zum Ausliefern durch die api-Schicht."""

    buffer: BytesIO
    filename: str


# --------------------------------------------------------------------------
# Arbeitsstand
# --------------------------------------------------------------------------


def _counters(
    conn: sqlite3.Connection, moment: str, *, list_id: str | None = None
) -> CallCounters:
    """Die Zahlen über dem Kontakt, in einer Abfrage.

    `offen` ist die Zahl, die auf null laufen soll — noch nie angerufen plus
    fällige Wiedervorlagen. Aufgeschobenes zählt separat: an einer Zahl, die
    einen Kontakt enthält, der erst um 16:00 wieder dran ist, kann gerade
    niemand arbeiten.
    """
    totals = db.state_totals(conn, moment, list_id=list_id)

    def due(state: ContactState) -> int:
        return totals.get(state.value, (0, 0))[0]

    def total(state: ContactState) -> int:
        return totals.get(state.value, (0, 0))[1]

    pool = (ContactState.OFFEN, ContactState.WIEDERVORLAGE, ContactState.RUECKRUF)

    return CallCounters(
        gesamt=sum(count for _, count in totals.values()),
        offen=sum(due(state) for state in pool),
        wiedervorlage=sum(total(state) - due(state) for state in pool),
        zugesagt=total(ContactState.ZUGESAGT),
        abgelehnt=total(ContactState.ABGELEHNT),
        ungueltig=total(ContactState.UNGUELTIG),
        zugesagt_ohne_email=db.promised_without_email(conn, list_id=list_id),
    )


def _event(row: sqlite3.Row) -> CallEventInfo:
    outcome = CallOutcome(row["outcome"])

    return CallEventInfo(
        occurred_at=row["occurred_at"],
        username=row["username"],
        outcome=outcome,
        outcome_label=next(info.label for info in OUTCOMES if info.id == outcome),
        note=row["note"],
        email=row["email"],
        appointment_at=row["appointment_at"],
        due_at=row["due_at"],
    )


def _contact(conn: sqlite3.Connection, row: sqlite3.Row) -> CallContact:
    state = ContactState(row["state"])
    extras: dict[str, str] = json.loads(row["extras"] or "{}")

    return CallContact(
        id=row["id"],
        list_id=row["list_id"],
        list_name=row["list_name"],
        betrieb=row["betrieb"],
        telefon=row["telefon"],
        email=row["email"],
        ort=row["ort"],
        plz=row["plz"],
        website=row["website"],
        gewerk=row["gewerk"],
        prio=row["prio"],
        befunde=row["befunde"],
        extras=[
            ContactField(label=label, value=value) for label, value in extras.items()
        ],
        state=state,
        state_label=STATE_LABELS[state],
        attempts=row["attempts"],
        due_at=row["due_at"],
        appointment_at=row["appointment_at"],
        note=row["note"],
        history=[_event(event) for event in db.events_of_contact(conn, row["id"])],
    )


def _list_info(conn: sqlite3.Connection, row: sqlite3.Row, moment: str) -> CallListInfo:
    return CallListInfo(
        id=row["id"],
        name=row["name"],
        source_filename=row["source_filename"],
        created_at=row["created_at"],
        created_by=row["created_by"],
        archived=bool(row["archived"]),
        counters=_counters(conn, moment, list_id=row["id"]),
    )


def _build_state(conn: sqlite3.Connection) -> CallState:
    """Der ganze Arbeitsstand. Einzige Stelle, die `CallState` erzeugt."""
    moment = db.now()
    row = db.next_contact(conn, moment)

    return CallState(
        revision=db.revision(conn),
        counters=_counters(conn, moment),
        contact=_contact(conn, row) if row is not None else None,
        next_due_at=db.next_due_at(conn, moment),
        outcomes=list(OUTCOMES),
        lists=[_list_info(conn, entry, moment) for entry in db.all_lists(conn)],
    )


def get_state() -> CallState:
    with db.connect() as conn:
        return _build_state(conn)


# --------------------------------------------------------------------------
# Ergebnis eines Anrufs
# --------------------------------------------------------------------------


def _parse_moment(raw: str, label: str) -> datetime:
    """Einen Zeitstempel aus dem Browser einlesen.

    Verlangt eine Zeitzone. Ein Zeitstempel ohne Zeitzone wäre eine Einladung,
    ihn als UTC zu deuten — und dann liegt jeder Rückruf um zwei Stunden
    daneben, im Sommer.
    """
    try:
        moment = datetime.fromisoformat(raw)
    except ValueError as exc:
        raise CallListError(
            f"{label} ist kein gültiger Zeitpunkt. Bitte erneut auswählen."
        ) from exc

    if moment.tzinfo is None:
        raise CallListError(
            f"{label} kam ohne Zeitzone an. Bitte die Seite neu laden und "
            "erneut auswählen."
        )

    return moment.astimezone(timezone.utc)


def _format(moment: datetime) -> str:
    return moment.strftime("%Y-%m-%dT%H:%M:%SZ")


def _resolve_times(
    outcome: CallOutcome, request: OutcomeRequest
) -> tuple[str | None, str | None]:
    """Wiedervorlage und Termin für dieses Ergebnis bestimmen.

    Liefert `(due_at, appointment_at)`. `due_at` ist der Zeitpunkt, zu dem der
    Kontakt wieder im Vorrat auftaucht; `appointment_at` der abgesprochene
    Termin, der nur angezeigt wird.
    """
    now = datetime.now(timezone.utc)
    horizon = now + timedelta(minutes=MAX_SNOOZE_MINUTES)

    if outcome is CallOutcome.NICHT_ERREICHBAR:
        if request.snooze_minutes is not None:
            minutes = request.snooze_minutes
            if not MIN_SNOOZE_MINUTES <= minutes <= MAX_SNOOZE_MINUTES:
                raise CallListError(
                    f"Die Wiedervorlage muss zwischen {MIN_SNOOZE_MINUTES} Minuten "
                    f"und {MAX_SNOOZE_MINUTES // (24 * 60)} Tagen liegen."
                )
            return _format(now + timedelta(minutes=minutes)), None

        if request.due_at:
            due = _parse_moment(request.due_at, "Die Wiedervorlage")
            if due > horizon:
                raise CallListError(
                    "Die Wiedervorlage liegt mehr als "
                    f"{MAX_SNOOZE_MINUTES // (24 * 60)} Tage in der Zukunft."
                )
            # Ein Zeitpunkt, der schon vorbei ist, ist keine Fehleingabe wert:
            # der Kontakt ist dann eben sofort wieder fällig.
            return _format(max(due, now)), None

        raise CallListError(
            "Für „nicht erreichbar“ fehlt der Zeitpunkt der Wiedervorlage."
        )

    if outcome is CallOutcome.RUECKRUF:
        if not request.appointment_at:
            raise CallListError("Für einen vereinbarten Rückruf fehlt der Termin.")

        appointment = _parse_moment(request.appointment_at, "Der Rückruftermin")

        if appointment > horizon:
            raise CallListError(
                "Der Rückruftermin liegt mehr als "
                f"{MAX_SNOOZE_MINUTES // (24 * 60)} Tage in der Zukunft."
            )

        # Der Kontakt erscheint mit Vorlauf wieder, aber nie in der
        # Vergangenheit: ein Termin „in 5 Minuten" ist sofort fällig.
        due = max(appointment - timedelta(minutes=CALLBACK_LEAD_MINUTES), now)

        return _format(due), _format(appointment)

    return None, None


def _validated_email(raw: str | None) -> str | None:
    """Adresse aus dem Gespräch prüfen. `None` = unverändert, `""` = löschen.

    Bewusst keine strenge Prüfung: alles, was ein Postfach beschreibt, hat ein
    `@` und keine Leerzeichen. Wer hier mehr prüft, lehnt irgendwann eine
    gültige Adresse ab, die am Telefon mühsam erfragt wurde.
    """
    if raw is None:
        return None

    email = raw.strip()

    if not email:
        return ""

    if len(email) > MAX_EMAIL:
        raise CallListError(f"Die E-Mail-Adresse ist länger als {MAX_EMAIL} Zeichen.")

    if email.count("@") != 1 or any(character.isspace() for character in email):
        raise CallListError(
            f"„{email}“ sieht nicht wie eine E-Mail-Adresse aus (genau ein @, "
            "keine Leerzeichen)."
        )

    local, _, domain = email.partition("@")
    if not local or "." not in domain or domain.startswith(".") or domain.endswith("."):
        raise CallListError(f"„{email}“ sieht nicht wie eine E-Mail-Adresse aus.")

    return email


def record_outcome(
    contact_id: str,
    request: OutcomeRequest,
    *,
    user_id: str,
    username: str,
) -> CallState:
    """Ergebnis eines Anrufs festschreiben und den nächsten Kontakt liefern.

    Zwei Schreibvorgänge in einer Transaktion: der Kontakt bekommt seinen neuen
    Zustand, und das Protokoll bekommt seine Zeile. Beides zusammen oder gar
    nicht — ein Zustand ohne Protokollzeile wäre eine Zusage, die niemand
    belegen kann.
    """
    email = _validated_email(request.email)
    note = request.note.strip()
    due_at, appointment_at = _resolve_times(request.outcome, request)
    state = OUTCOME_STATES[request.outcome]

    with db.connect() as conn:
        with db.transaction(conn):
            row = db.find_contact(conn, contact_id)

            if row is None:
                raise CallListNotFoundError("Dieser Kontakt existiert nicht (mehr).")

            if row["list_archived"]:
                raise CallListError(
                    "Die Liste dieses Kontakts ist archiviert. Bitte die Seite "
                    "neu laden."
                )

            db.apply_outcome(
                conn,
                contact_id,
                state=state.value,
                due_at=due_at,
                appointment_at=appointment_at,
                note=note,
                email=email,
                # „Nummer falsch“ war kein Anrufversuch beim Betrieb, sondern
                # ein Fund über die Liste.
                count_attempt=request.outcome is not CallOutcome.NUMMER_FALSCH,
            )

            db.insert_event(
                conn,
                contact_id=contact_id,
                list_id=row["list_id"],
                betrieb=row["betrieb"],
                telefon=row["telefon"],
                user_id=user_id,
                username=username,
                outcome=request.outcome.value,
                note=note,
                # Die Adresse, wie sie *nach* diesem Anruf gilt — das ist der
                # Nachweis, für welche Adresse die Zustimmung erteilt wurde.
                email=email if email is not None else row["email"],
                due_at=due_at,
                appointment_at=appointment_at,
            )

            db.bump_revision(conn)

        return _build_state(conn)


# --------------------------------------------------------------------------
# Listen einlesen
# --------------------------------------------------------------------------


def _mapping_info(result: CallCsvResult) -> list[ColumnMappingInfo]:
    empty = result.empty_field_counts()

    return [
        ColumnMappingInfo(
            field=name,
            label=FIELD_LABELS[name],
            column=result.mapping[name],
            empty_count=empty.get(name, 0),
        )
        for name in FIELD_NAMES
        if name in result.mapping
    ]


def _name_suggestion(filename: str) -> str:
    """Listenname aus dem Dateinamen — der Vorschlag im Formular.

    „handwerker-herford-v2-analyse.csv" → „handwerker herford v2 analyse".
    Trennzeichen zu Leerzeichen, weil der Name in der Oberfläche über den
    Zahlen steht und dort gelesen wird.
    """
    stem = filename.rsplit("/", 1)[-1].rsplit(".", 1)[0]
    cleaned = " ".join(stem.replace("_", " ").replace("-", " ").split())

    return cleaned[:MAX_LIST_NAME] or "Anrufliste"


def _duplicate_rows(
    conn: sqlite3.Connection, records: list[CallRecord]
) -> tuple[list[CallRecord], list[SkippedRowInfo]]:
    """Doppelte Nummern heraussortieren — innerhalb der Datei und gegen den Bestand.

    Der Sinn der Prüfung ist ein einziger: denselben Betrieb nicht zweimal
    anrufen. Der erste Treffer in der Datei bleibt, jeder weitere wird mit dem
    Ort des Originals gemeldet — eine Duplikatmeldung ohne diesen Ort kann
    niemand nachvollziehen.
    """
    owners = db.phone_key_owners(conn)
    seen: dict[str, int] = {}

    keep: list[CallRecord] = []
    duplicates: list[SkippedRowInfo] = []

    for record in records:
        key = db.phone_key(record.get("telefon"))

        if key and key in owners:
            duplicates.append(
                SkippedRowInfo(
                    line=record.line,
                    reason=(
                        f"{record.get('betrieb')}: die Nummer steht bereits in "
                        f"der Liste „{owners[key]}“."
                    ),
                )
            )
            continue

        if key and key in seen:
            duplicates.append(
                SkippedRowInfo(
                    line=record.line,
                    reason=(
                        f"{record.get('betrieb')}: dieselbe Nummer steht schon in "
                        f"Zeile {seen[key]} dieser Datei."
                    ),
                )
            )
            continue

        if key:
            seen[key] = record.line

        keep.append(record)

    return keep, duplicates


def _skipped_info(result: CallCsvResult) -> list[SkippedRowInfo]:
    return [SkippedRowInfo(line=row.line, reason=row.reason) for row in result.skipped]


def _parse(data: bytes) -> CallCsvResult:
    try:
        return parse_call_csv(data)
    except CallCsvError as exc:
        raise CallListError(str(exc)) from exc


def analyse_list(data: bytes, filename: str) -> ListAnalyseResponse:
    """Trockenlauf: was der Import ergäbe, ohne etwas zu speichern."""
    result = _parse(data)

    with db.connect() as conn:
        keep, duplicates = _duplicate_rows(conn, result.records)

    return ListAnalyseResponse(
        name_suggestion=_name_suggestion(filename),
        encoding=result.encoding_label,
        delimiter=result.delimiter_label,
        data_rows=result.data_rows,
        contacts=len(keep),
        mapping=_mapping_info(result),
        extra_columns=result.extra_columns,
        skipped_rows=_skipped_info(result),
        duplicates=duplicates,
        warnings=result.warnings,
    )


def import_list(
    data: bytes,
    filename: str,
    name: str,
    *,
    created_by: str,
) -> ListImportResponse:
    """Die hochgeladene Liste speichern und den neuen Arbeitsstand liefern."""
    result = _parse(data)

    list_name = " ".join(name.split())[:MAX_LIST_NAME] or _name_suggestion(filename)

    with db.connect() as conn:
        with db.transaction(conn):
            if db.find_list_by_name(conn, list_name) is not None:
                raise CallListConflictError(
                    f"Es gibt bereits eine Liste namens „{list_name}“. Bitte einen "
                    "anderen Namen wählen oder die alte Liste archivieren."
                )

            keep, duplicates = _duplicate_rows(conn, result.records)

            if not keep:
                raise CallListError(
                    "Jede Zeile dieser Datei steht schon in einer aktiven Liste. "
                    "Es gibt nichts zu importieren."
                )

            list_id = db.new_id()
            timestamp = db.now()

            db.insert_list(
                conn,
                list_id=list_id,
                name=list_name,
                source_filename=filename[:200],
                columns=json.dumps(result.extra_columns, ensure_ascii=False),
                created_by=created_by,
            )

            db.insert_contacts(
                conn,
                [
                    (
                        db.new_id(),
                        list_id,
                        position,
                        record.get("betrieb"),
                        record.get("telefon"),
                        db.phone_key(record.get("telefon")),
                        record.get("email"),
                        record.get("ort"),
                        record.get("plz"),
                        record.get("website"),
                        record.get("gewerk"),
                        record.get("prio"),
                        record.get("befunde"),
                        json.dumps(record.extras, ensure_ascii=False),
                        ContactState.OFFEN.value,
                        timestamp,
                    )
                    for position, record in enumerate(keep)
                ],
            )

            db.bump_revision(conn)

        return ListImportResponse(
            list_id=list_id,
            imported=len(keep),
            skipped_rows=_skipped_info(result),
            duplicates=duplicates,
            warnings=result.warnings,
            state=_build_state(conn),
        )


# --------------------------------------------------------------------------
# Listen verwalten
# --------------------------------------------------------------------------


def update_list(list_id: str, request: ListUpdateRequest) -> CallState:
    """Umbenennen oder archivieren."""
    with db.connect() as conn:
        with db.transaction(conn):
            row = db.find_list(conn, list_id)
            if row is None:
                raise CallListNotFoundError("Diese Liste existiert nicht (mehr).")

            name = " ".join(request.name.split()) if request.name is not None else None

            if name is not None:
                clash = db.find_list_by_name(conn, name)
                if clash is not None and clash["id"] != list_id:
                    raise CallListConflictError(
                        f"Es gibt bereits eine Liste namens „{name}“."
                    )

            db.update_list(conn, list_id, name=name, archived=request.archived)
            db.bump_revision(conn)

        return _build_state(conn)


def delete_list(list_id: str, *, force: bool = False) -> CallState:
    """Liste endgültig entfernen — mit Widerstand, wenn Anrufe dokumentiert sind.

    Archivieren ist der normale Weg, eine Liste zu beenden: die Kontakte
    verschwinden aus dem Vorrat, das Protokoll bleibt. Ein Löschen nimmt über
    `ON DELETE CASCADE` auch die Protokollzeilen mit, und damit den Nachweis
    der Einwilligungen — deshalb antwortet es mit 409, solange etwas
    dokumentiert ist, und braucht `force=true` nach ausdrücklicher Bestätigung.
    """
    with db.connect() as conn:
        with db.transaction(conn):
            row = db.find_list(conn, list_id)
            if row is None:
                raise CallListNotFoundError("Diese Liste existiert nicht (mehr).")

            documented = db.documented_calls(conn, list_id)

            if documented and not force:
                raise CallListConflictError(
                    f"Zu dieser Liste sind {documented} Anrufe protokolliert. "
                    "Löschen entfernt auch diesen Nachweis. Archivieren behält ihn."
                )

            db.delete_list(conn, list_id)
            db.bump_revision(conn)

        return _build_state(conn)


# --------------------------------------------------------------------------
# Ausgaben
# --------------------------------------------------------------------------

#: Excel öffnet eine CSV nur mit BOM zuverlässig als UTF-8 — ohne das steht in
#: der Spalte „Betrieb“ „Zaunbau Müller“ als „MÃ¼ller“.
_EXPORT_ENCODING = "utf-8-sig"


def _export(rows: list[list[str]], prefix: str) -> CallListExport:
    stamp = db.now()[:10].replace("-", "")
    buffer = BytesIO(csv_rows_to_str(rows).encode(_EXPORT_ENCODING))

    return CallListExport(buffer=buffer, filename=f"{prefix}_{stamp}.csv")


def export_promised() -> CallListExport:
    """Die Zusagen als CSV — die Datei, aus der der Mailversand liest.

    Enthält bewusst auch Zusagen ohne Adresse: sie sind die Nacharbeit, die
    sonst niemand sieht.
    """
    header = [
        "Betrieb",
        "E-Mail",
        "Telefon",
        "Ort",
        "PLZ",
        "Website",
        "Gewerk",
        "Liste",
        "Zusage am",
        "Zusage aufgenommen von",
        "Anmerkung",
    ]

    with db.connect() as conn:
        rows = [
            [
                row["betrieb"],
                row["email"],
                row["telefon"],
                row["ort"],
                row["plz"],
                row["website"],
                row["gewerk"],
                row["list_name"],
                row["promised_at"] or "",
                row["promised_by"] or "",
                row["note"],
            ]
            for row in db.promised_contacts(conn)
        ]

    return _export([header, *rows], "zusagen")


def export_protocol() -> CallListExport:
    """Das vollständige Protokoll als CSV.

    Der Nachweis zum Mitnehmen: jede Zeile ein Anruf, mit Zeitpunkt, Konto und
    Ergebnis. Wird nur gelesen, nie zurückgespielt.
    """
    header = [
        "Zeitpunkt (UTC)",
        "Liste",
        "Betrieb",
        "Telefon",
        "Ergebnis",
        "Erfasst von",
        "E-Mail",
        "Wiedervorlage",
        "Termin",
        "Anmerkung",
    ]

    labels = {info.id.value: info.label for info in OUTCOMES}

    with db.connect() as conn:
        rows = [
            [
                row["occurred_at"],
                row["list_name"] or "",
                row["betrieb"],
                row["telefon"],
                labels.get(row["outcome"], row["outcome"]),
                row["username"],
                row["email"],
                row["due_at"] or "",
                row["appointment_at"] or "",
                row["note"],
            ]
            for row in db.all_events(conn)
        ]

    return _export([header, *rows], "telefonprotokoll")


__all__ = [
    "MAX_FILE_BYTES",
    "MAX_ROWS",
    "CallListConflictError",
    "CallListError",
    "CallListExport",
    "CallListNotFoundError",
    "analyse_list",
    "delete_list",
    "export_promised",
    "export_protocol",
    "get_state",
    "import_list",
    "record_outcome",
    "update_list",
]
