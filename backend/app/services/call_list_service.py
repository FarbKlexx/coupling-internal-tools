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
    MAX_BLACKLIST_ROWS,
    MAX_FILE_BYTES,
    MAX_NAME_CHARS,
    MAX_ROWS,
    BlacklistRecord,
    CallCsvError,
    CallCsvResult,
    CallRecord,
)
from app.core.call_list_csv import parse_blacklist_csv as parse_blacklist
from app.core.call_list_csv import parse_csv as parse_call_csv
from app.core.csv_utils import csv_rows_to_str
from app.schemas.call_list import (
    BLACKLIST_PAGE_SIZE,
    BLACKLIST_SOURCE_LABELS,
    CALLBACK_LEAD_MINUTES,
    MAX_BLACKLIST_PAGE_SIZE,
    MAX_EMAIL,
    MAX_LIST_NAME,
    MAX_PASTED_NUMBERS,
    MAX_SNOOZE_MINUTES,
    MIN_SNOOZE_MINUTES,
    NO_PRIO_VALUE,
    OUTCOME_STATES,
    OUTCOMES,
    STATE_LABELS,
    BlacklistAddRequest,
    BlacklistEntry,
    BlacklistMutationResponse,
    BlacklistPage,
    BlacklistSource,
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
    PrioOption,
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
        blacklist_count=db.blacklist_total(conn),
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


def _german_date(iso: str) -> str:
    """„2026-03-12T08:00:00Z" → „12.03.2026". Für Meldungen, nicht für Daten."""
    try:
        return datetime.fromisoformat(iso.replace("Z", "+00:00")).strftime("%d.%m.%Y")
    except ValueError:
        return iso[:10]


def _prio_key(raw: str) -> str:
    """Vergleichsschlüssel eines Prio-Werts.

    „A", „a" und „ A " sind dieselbe Prio — sonst steht in der Auswahl dreimal
    dasselbe und der Anwender hakt zwei davon nicht an. Leer ist ein eigener
    Wert und kein fehlender: eine Zeile ohne Prio soll man bewusst mit- oder
    weglassen können.
    """
    collapsed = " ".join(raw.split())

    return collapsed.casefold() if collapsed else NO_PRIO_VALUE


def _blocked_reason(
    record: CallRecord,
    key: str,
    owners: dict[str, str],
    blocked: dict[str, sqlite3.Row],
) -> str | None:
    """Die Meldung zu einer schon bekannten Nummer, oder `None`.

    Die aktive Liste wird zuerst geprüft, obwohl die Blacklist dieselbe Nummer
    auch kennt: „steht in der Liste ‚Handwerker Herford'" sagt, wo der Betrieb
    gerade bearbeitet wird, „steht auf der Blacklist" sagt nur, dass er es
    einmal wurde.
    """
    if not key:
        return None

    betrieb = record.get("betrieb")

    if key in owners:
        return f"{betrieb}: die Nummer steht bereits in der Liste „{owners[key]}“."

    entry = blocked.get(key)
    if entry is None:
        return None

    if entry["source"] == BlacklistSource.MANUELL.value:
        note = f" ({entry['note']})" if entry["note"] else ""
        return f"{betrieb}: die Nummer ist von Hand gesperrt{note}."

    if entry["list_name"]:
        return (
            f"{betrieb}: die Nummer wurde am {_german_date(entry['created_at'])} "
            f"schon einmal importiert (Liste „{entry['list_name']}“)."
        )

    return f"{betrieb}: die Nummer steht bereits auf der Blacklist."


@dataclass
class _ImportPlan:
    """Was aus einer Datei bei dieser Prio-Auswahl würde.

    Dieselbe Rechnung für den Trockenlauf und den Import — die Vorschau kann
    also nichts anderes behaupten als das Ergebnis.
    """

    keep: list[CallRecord]
    duplicates: list[SkippedRowInfo]
    prio_skipped: int
    prio_options: list[PrioOption]


def _plan_import(
    conn: sqlite3.Connection,
    result: CallCsvResult,
    prios: list[str] | None,
) -> _ImportPlan:
    """Prio-Auswahl anwenden, dann Duplikate aussortieren — in dieser Reihenfolge.

    Die Reihenfolge ist der ganze Trick: würde erst entdoppelt, meldete die
    Datei „Zeile 40 ist ein Duplikat von Zeile 12" für eine Zeile 12, die
    wegen ihrer Prio gar nicht importiert wird. Eine Duplikatmeldung, die auf
    eine nicht importierte Zeile zeigt, ist falsch.
    """
    owners = db.phone_key_owners(conn)
    keys = [db.phone_key(record.get("telefon")) for record in result.records]
    blocked = db.blacklist_lookup(conn, keys)

    selection = None if prios is None else {_prio_key(value) for value in prios}

    # Ohne Prio-Spalte gibt es nichts auszuwählen. Ein einzelnes Häkchen
    # „(ohne Prio)" über der ganzen Datei wäre eine Auswahl ohne Alternative.
    has_prio = "prio" in result.mapping

    # Die Gruppen werden unabhängig von der Auswahl aufgebaut, damit man
    # sieht, was man gerade *nicht* anhakt.
    groups: dict[str, PrioOption] = {}
    seen_per_group: dict[str, set[str]] = {}

    keep: list[CallRecord] = []
    duplicates: list[SkippedRowInfo] = []
    prio_skipped = 0
    seen: dict[str, int] = {}

    for record, key in zip(result.records, keys, strict=True):
        raw = record.get("prio")
        group = _prio_key(raw)

        if has_prio and group not in groups:
            groups[group] = PrioOption(
                value=group,
                label=" ".join(raw.split()) or "(ohne Prio)",
                rows=0,
                contacts=0,
            )
            seen_per_group[group] = set()

        reason = _blocked_reason(record, key, owners, blocked)

        if has_prio:
            option = groups[group]
            option.rows += 1

            # Die Vorschauzahl je Prio entdoppelt innerhalb ihrer Gruppe: sie
            # soll aufgehen, wenn genau diese eine Prio gewählt wird.
            if reason is None and not (key and key in seen_per_group[group]):
                option.contacts += 1
                if key:
                    seen_per_group[group].add(key)

        if selection is not None and group not in selection:
            prio_skipped += 1
            continue

        if reason is not None:
            duplicates.append(SkippedRowInfo(line=record.line, reason=reason))
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

    return _ImportPlan(
        keep=keep,
        duplicates=duplicates,
        prio_skipped=prio_skipped,
        prio_options=list(groups.values()),
    )


def _skipped_info(result: CallCsvResult) -> list[SkippedRowInfo]:
    return [SkippedRowInfo(line=row.line, reason=row.reason) for row in result.skipped]


def _parse(data: bytes) -> CallCsvResult:
    try:
        return parse_call_csv(data)
    except CallCsvError as exc:
        raise CallListError(str(exc)) from exc


def analyse_list(data: bytes, filename: str) -> ListAnalyseResponse:
    """Trockenlauf: was der Import ergäbe, ohne etwas zu speichern.

    Läuft immer über *alle* Prios. Die Auswahl trifft der Anwender danach an
    den Zahlen, die hier mitkommen — pro Prio steht dabei sowohl, wie viele
    Zeilen sie hat, als auch, wie viele davon neu sind. Damit rechnet das
    Formular die Auswahl selbst aus und muss die 4-MB-Datei nicht bei jedem
    Häkchen erneut hochladen.
    """
    result = _parse(data)

    with db.connect() as conn:
        plan = _plan_import(conn, result, None)

    return ListAnalyseResponse(
        name_suggestion=_name_suggestion(filename),
        encoding=result.encoding_label,
        delimiter=result.delimiter_label,
        data_rows=result.data_rows,
        contacts=len(plan.keep),
        mapping=_mapping_info(result),
        extra_columns=result.extra_columns,
        skipped_rows=_skipped_info(result),
        duplicates=plan.duplicates,
        warnings=result.warnings,
        prio_column=result.mapping.get("prio"),
        prio_values=plan.prio_options,
    )


def import_list(
    data: bytes,
    filename: str,
    name: str,
    *,
    created_by: str,
    prios: list[str] | None = None,
) -> ListImportResponse:
    """Die hochgeladene Liste speichern und den neuen Arbeitsstand liefern.

    `prios is None` heißt „alle" — dasselbe Muster wie bei der E-Mail im
    Ergebnis: das *Fehlen* des Feldes bedeutet „nicht eingeschränkt", eine
    leere Auswahl dagegen ist eine Fehleingabe und keine leere Liste.

    Jede importierte Nummer wandert zugleich auf die Blacklist. Sie ist die
    Antwort auf zwei Listen, die sich überschneiden: die zweite bringt die
    gemeinsamen Betriebe nicht noch einmal in den Vorrat, auch dann nicht,
    wenn die erste inzwischen archiviert ist.
    """
    result = _parse(data)

    if prios is not None and not prios:
        raise CallListError(
            "Es wurde keine Prio ausgewählt. Bitte mindestens eine anhaken."
        )

    if prios is not None and "prio" not in result.mapping:
        raise CallListError(
            "Diese Datei hat keine Prio-Spalte, es kann also nicht nach Prio "
            "gefiltert werden."
        )

    list_name = " ".join(name.split())[:MAX_LIST_NAME] or _name_suggestion(filename)

    with db.connect() as conn:
        with db.transaction(conn):
            if db.find_list_by_name(conn, list_name) is not None:
                raise CallListConflictError(
                    f"Es gibt bereits eine Liste namens „{list_name}“. Bitte einen "
                    "anderen Namen wählen oder die alte Liste archivieren."
                )

            plan = _plan_import(conn, result, prios)
            keep, duplicates = plan.keep, plan.duplicates

            if not keep:
                raise CallListError(
                    "Aus dieser Datei bleibt bei der gewählten Prio nichts übrig."
                    if plan.prio_skipped
                    else "Jede Nummer dieser Datei ist schon bekannt — sie steht "
                    "in einer aktiven Liste oder auf der Blacklist. Es gibt "
                    "nichts zu importieren."
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

            # In derselben Transaktion wie die Kontakte: eine Liste, deren
            # Nummern nicht gesperrt sind, wäre beim nächsten Import wieder da.
            blacklisted = db.add_to_blacklist(
                conn,
                [
                    (
                        key,
                        record.get("telefon"),
                        record.get("betrieb"),
                        BlacklistSource.IMPORT.value,
                        list_id,
                        list_name,
                        "",
                        timestamp,
                        created_by,
                    )
                    for record in keep
                    if (key := db.phone_key(record.get("telefon")))
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
            prio_skipped=plan.prio_skipped,
            blacklisted=blacklisted,
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

    Gelöscht werden zusätzlich die Blacklist-Einträge, die aus dieser Liste
    stammen und in keiner anderen stecken. Löschen heißt hier „das hat nicht
    stattgefunden" — wer eine falsche Datei erwischt hat, muss die richtige
    danach importieren können. Archivieren heißt „Runde beendet" und behält
    die Sperre.
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

            db.drop_blacklist_of_list(conn, list_id)
            db.delete_list(conn, list_id)
            db.bump_revision(conn)

        return _build_state(conn)


# --------------------------------------------------------------------------
# Blacklist
# --------------------------------------------------------------------------


def _blacklist_entry(row: sqlite3.Row) -> BlacklistEntry:
    source = BlacklistSource(row["source"])

    return BlacklistEntry(
        telefon_key=row["telefon_key"],
        telefon=row["telefon"],
        betrieb=row["betrieb"],
        source=source,
        source_label=BLACKLIST_SOURCE_LABELS[source],
        list_name=row["list_name"],
        note=row["note"],
        created_at=row["created_at"],
        created_by=row["created_by"],
    )


def _blacklist_page(
    conn: sqlite3.Connection, *, query: str, offset: int, limit: int
) -> BlacklistPage:
    rows, matched = db.blacklist_page(conn, query=query, limit=limit, offset=offset)

    return BlacklistPage(
        entries=[_blacklist_entry(row) for row in rows],
        total=db.blacklist_total(conn),
        matched=matched,
        offset=offset,
        limit=limit,
    )


def get_blacklist(
    *, query: str = "", offset: int = 0, limit: int = BLACKLIST_PAGE_SIZE
) -> BlacklistPage:
    """Ein Ausschnitt der Sperrliste.

    Grenzen werden geklemmt statt abgelehnt: das ist keine Eingabe des
    Anwenders, sondern eine URL, und eine Fehlermeldung hilft dort niemandem.
    """
    limit = max(1, min(limit, MAX_BLACKLIST_PAGE_SIZE))
    offset = max(0, offset)

    with db.connect() as conn:
        return _blacklist_page(conn, query=query, offset=offset, limit=limit)


#: Trennzeichen innerhalb einer eingefügten Zeile.
_PASTE_SPLIT = str.maketrans({";": "\t", ",": "\t"})


def _split_pasted_line(line: str) -> tuple[str, str]:
    """Eine eingefügte Zeile in (Nummer, Betrieb) zerlegen.

    Eingefügt wird, was gerade zur Hand ist: eine nackte Nummer, „Zaunbau
    Müller;05221 111" oder dasselbe andersherum. Deshalb wird nicht auf eine
    Spaltenreihenfolge gesetzt, sondern das ziffernreichste Feld ist die
    Nummer und das erste übrige der Betrieb.
    """
    fields = [part.strip() for part in line.translate(_PASTE_SPLIT).split("\t")]
    fields = [part for part in fields if part]

    if not fields:
        return "", ""

    # Über den Index und nicht über den Wert: „111;111" hat zweimal denselben
    # Text, und ein Vergleich auf Gleichheit ließe den Betrieb dann leer.
    chosen = max(
        range(len(fields)),
        key=lambda index: sum(character.isdigit() for character in fields[index]),
    )
    number = fields[chosen]
    betrieb = next((part for index, part in enumerate(fields) if index != chosen), "")

    return number[:MAX_NAME_CHARS], betrieb[:MAX_NAME_CHARS]


def _blacklist_rows(
    conn: sqlite3.Connection,
    entries: list[BlacklistRecord],
    *,
    note: str,
    created_by: str,
) -> tuple[list[tuple[object, ...]], int]:
    """Aus geprüften Zeilen die Datenbankzeilen — und wie viele schon da waren.

    Der Zählweg über `blacklist_lookup` statt über `rowcount`: `INSERT OR
    IGNORE` verschluckt beides, und „37 hinzugefügt, 12 waren schon bekannt"
    ist die Auskunft, die der Anwender hier braucht.
    """
    timestamp = db.now()
    known = db.blacklist_lookup(
        conn, [db.phone_key(entry.telefon) for entry in entries]
    )

    rows: list[tuple[object, ...]] = []
    seen: set[str] = set()
    already = 0

    for entry in entries:
        key = db.phone_key(entry.telefon)

        if not key or key in seen:
            continue

        seen.add(key)

        if key in known:
            already += 1
            continue

        rows.append(
            (
                key,
                entry.telefon,
                entry.betrieb,
                BlacklistSource.MANUELL.value,
                "",
                "",
                note,
                timestamp,
                created_by,
            )
        )

    return rows, already


def _blacklist_mutation(
    entries: list[BlacklistRecord],
    skipped: list[SkippedRowInfo],
    *,
    note: str,
    created_by: str,
) -> BlacklistMutationResponse:
    with db.connect() as conn:
        with db.transaction(conn):
            rows, already = _blacklist_rows(
                conn, entries, note=note, created_by=created_by
            )
            db.add_to_blacklist(conn, rows)
            db.bump_revision(conn)

        return BlacklistMutationResponse(
            added=len(rows),
            already_known=already,
            skipped=skipped,
            page=_blacklist_page(conn, query="", offset=0, limit=BLACKLIST_PAGE_SIZE),
        )


def add_blacklist_numbers(
    request: BlacklistAddRequest, *, created_by: str
) -> BlacklistMutationResponse:
    """Von Hand eingetragene Nummern sperren."""
    lines = [line for line in request.numbers.splitlines() if line.strip()]

    if not lines:
        raise CallListError("Es wurde keine Nummer eingegeben.")

    if len(lines) > MAX_PASTED_NUMBERS:
        raise CallListError(
            f"Mehr als {MAX_PASTED_NUMBERS} Zeilen auf einmal gehen nur über den "
            "CSV-Weg."
        )

    entries: list[BlacklistRecord] = []
    skipped: list[SkippedRowInfo] = []

    for index, line in enumerate(lines, start=1):
        number, betrieb = _split_pasted_line(line)

        if not any(character.isdigit() for character in number):
            skipped.append(
                SkippedRowInfo(
                    line=index,
                    reason=f"„{line.strip()[:80]}“ enthält keine Telefonnummer.",
                )
            )
            continue

        entries.append(BlacklistRecord(line=index, telefon=number, betrieb=betrieb))

    if not entries:
        raise CallListError(
            "Keine der Zeilen enthält eine Telefonnummer. Erwartet wird eine "
            "Nummer pro Zeile, wahlweise mit dem Betrieb davor oder dahinter."
        )

    return _blacklist_mutation(
        entries, skipped, note=request.note.strip(), created_by=created_by
    )


def import_blacklist(data: bytes, *, created_by: str) -> BlacklistMutationResponse:
    """Eine CSV als Sperrliste einlesen.

    Verlangt nur eine Spalte mit Telefonnummern; ein „Betrieb" wird
    mitgenommen, wenn er dabei ist. Die Herkunft steht als Anmerkung im
    Eintrag, damit später nachvollziehbar ist, warum eine Nummer gesperrt ist.
    """
    try:
        result = parse_blacklist(data)
    except CallCsvError as exc:
        raise CallListError(str(exc)) from exc

    return _blacklist_mutation(
        result.records,
        [SkippedRowInfo(line=row.line, reason=row.reason) for row in result.skipped],
        note="",
        created_by=created_by,
    )


def remove_blacklist_entry(
    telefon_key: str, *, query: str = "", offset: int = 0
) -> BlacklistPage:
    """Eine Nummer wieder freigeben.

    Der Ausschnitt wird mit derselben Suche und demselben Versatz
    zurückgegeben, aus dem heraus gelöscht wurde — sonst springt die Ansicht
    nach jedem Entfernen auf die erste Seite zurück.
    """
    with db.connect() as conn:
        with db.transaction(conn):
            if not db.remove_from_blacklist(conn, telefon_key):
                raise CallListNotFoundError(
                    "Diese Nummer steht nicht (mehr) auf der Blacklist."
                )

            db.bump_revision(conn)

        return _blacklist_page(
            conn,
            query=query,
            offset=max(0, offset),
            limit=BLACKLIST_PAGE_SIZE,
        )


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


def export_blacklist() -> CallListExport:
    """Die Sperrliste als CSV.

    Damit lässt sie sich in einem anderen Werkzeug weiterverwenden — und
    genauso wieder hier einlesen: die Spalte „Telefon" ist alles, was der
    Import davon braucht.
    """
    header = [
        "Telefon",
        "Betrieb",
        "Herkunft",
        "Liste",
        "Anmerkung",
        "Gesperrt am (UTC)",
        "Gesperrt von",
    ]

    with db.connect() as conn:
        rows = [
            [
                row["telefon"] or row["telefon_key"],
                row["betrieb"],
                BLACKLIST_SOURCE_LABELS[BlacklistSource(row["source"])],
                row["list_name"],
                row["note"],
                row["created_at"],
                row["created_by"],
            ]
            for row in db.all_blacklist(conn)
        ]

    return _export([header, *rows], "blacklist")


__all__ = [
    "MAX_BLACKLIST_ROWS",
    "MAX_FILE_BYTES",
    "MAX_ROWS",
    "CallListConflictError",
    "CallListError",
    "CallListExport",
    "CallListNotFoundError",
    "add_blacklist_numbers",
    "analyse_list",
    "delete_list",
    "export_blacklist",
    "export_promised",
    "export_protocol",
    "get_blacklist",
    "get_state",
    "import_blacklist",
    "import_list",
    "record_outcome",
    "remove_blacklist_entry",
    "update_list",
]
