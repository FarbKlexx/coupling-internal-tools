"""Fachregeln des Mailversands.

Was nach der Zusage passiert. Die Telefonakquise beantwortet „dürfen wir
schreiben?" und legt den Nachweis dafür an; hier steht die andere Hälfte:
*haben* wir geschrieben, und was kam zurück.

Vier Entscheidungen prägen dieses Modul:

* **Keine eigenen Kontakte.** Die Zeilen sind die Kontakte der
  Telefonakquise im Zustand `zugesagt`. Ein Betrieb, dessen Zusage
  richtiggestellt wird, verschwindet damit von selbst aus der Liste — und
  nicht erst, wenn jemand daran denkt.
* **Die Fristen werden gerechnet, nicht geschrieben.** „Nachfassen nach 10
  Tagen" und „keine Antwort nach 30 Tagen" folgen beide aus dem Versanddatum
  (siehe `MailState` und `_MAIL_STATE` im Datenmodul). Es gibt in dieser
  Anwendung keinen Hintergrundjob, und ein Feld, das erst beim nächsten Klick
  nachgezogen würde, wäre bis dahin falsch. Dass beides rückwirkend für längst
  verschickte Zeilen gilt, ist keine Migration, sondern dieselbe Rechnung.
* **Die Bau-Einschätzung ist eine zweite Dimension**, kein sechster
  Zustand: `BuildReadiness` sagt, ob aus der bestehenden Website eine neue
  werden kann — und, mit `in_development`/`ready_to_mail`, dass sie gebaut
  wird bzw. schon gebaut ist und nur noch zum Betrieb muss. Damit
  beantwortet sie eine andere Frage als der Versandstand. Sie hat aus demselben Grund keine Übergangstabelle —
  eingeschätzt wird jederzeit, in jedem Versandstand, in jede Richtung.
* **Die Übergänge stehen in einer Tabelle**, und dieselbe Tabelle bestückt die
  Knöpfe der Zeile (`MAIL_TRANSITIONS`). Die Oberfläche kann deshalb keinen
  Übergang anbieten, den das Schreiben ablehnt — das Muster von
  `CallDecision.correctable`.

Wie überall in dieser Anwendung antwortet jeder schreibende Aufruf mit der
*ganzen* Ansicht. Anders als beim Kanban-Board und beim Arbeitsstand ist die
hier geblättert: Zusagen sammeln sich an und werden nie weniger.
"""

import json
import sqlite3
from datetime import datetime, timedelta, timezone
from io import BytesIO

from app.core import call_list_db as db
from app.core.csv_utils import csv_rows_to_str
from app.schemas.call_list import (
    BlacklistSource,
    CallOutcome,
    ContactField,
    ContactState,
)
from app.schemas.mail_followup import (
    MAIL_ACTIONS,
    MAIL_FOLLOWUP_DAYS,
    MAIL_PAGE_SIZE,
    MAIL_STATE_LABELS,
    MAIL_TIMEOUT_DAYS,
    MAIL_TRANSITIONS,
    MANUAL_LIST_NAME,
    MAX_MAIL_PAGE_SIZE,
    READINESS_LABELS,
    READINESS_OPTIONS,
    SCOPE_MARKER,
    BuildReadiness,
    MailBoard,
    MailCounters,
    MailEntry,
    MailState,
    MailUpdateRequest,
    ManualEntryRequest,
)
from app.services import call_list_service
from app.services.call_list_service import CallListError, CallListExport

#: Kodierung der Ausgabe. Mit BOM, weil diese Datei in Excel geöffnet wird —
#: ohne sie steht dort „Zaunbau MÃ¼ller". Dieselbe Begründung wie bei den
#: Ausgaben der Telefonakquise.
_EXPORT_ENCODING = "utf-8-sig"


class MailFollowupError(Exception):
    """Alles, was der Anwender selbst beheben kann → 400."""


class MailFollowupNotFoundError(MailFollowupError):
    """Diese Zusage gibt es nicht (mehr) → 404."""


class MailFollowupConflictError(MailFollowupError):
    """Diese Nummer ist schon bekannt → 409.

    Eigener Fehler und eigener Status, weil die Oberfläche darauf anders
    antwortet als auf einen Tippfehler: sie nennt den Befund und bietet an,
    ihn zu übergehen. Dasselbe Verfahren wie beim Löschen einer Liste mit
    Protokoll.
    """


def _cutoff() -> db.MailCutoffs:
    """Die beiden Zeitpunkte, vor denen ein Versand fällig wird.

    Einmal pro Anfrage gerechnet und dann durchgereicht: Liste, Zähler und
    Schreibpfad sollen dieselben Stichtage benutzen, sonst wechselt eine Zeile
    zwischen zwei Abfragen derselben Antwort die Gruppe. Aus *einem*
    `now()` gerechnet, damit die beiden Fristen nicht einen Wimpernschlag
    auseinanderliegen.
    """
    now = datetime.now(timezone.utc)

    def stamp(days: int) -> str:
        return (now - timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ")

    return db.MailCutoffs(
        answer=stamp(MAIL_TIMEOUT_DAYS), followup=stamp(MAIL_FOLLOWUP_DAYS)
    )


def _parse(stamp: str | None) -> datetime | None:
    """Einen gespeicherten Zeitstempel lesen. Gespeichert wird nur UTC."""
    if not stamp:
        return None

    try:
        moment = datetime.fromisoformat(stamp.replace("Z", "+00:00"))
    except ValueError:
        return None

    return moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)


def _days_since(stamp: str | None) -> int | None:
    """Volle Tage seit diesem Zeitpunkt, oder `None`.

    Hier gerechnet und nicht in der Oberfläche: „seit 12 Tagen" steht in der
    Liste *und* in der Ausgabe, und zwei Rechnungen wären eine zu viel.
    """
    moment = _parse(stamp)
    if moment is None:
        return None

    return max((datetime.now(timezone.utc) - moment).days, 0)


def _actions(row: sqlite3.Row, state: MailState) -> list[MailState]:
    """Welche Knöpfe diese Zeile zeigt.

    Ohne Adresse fällt „Mail versendet" heraus: es gibt nichts, wohin sie
    hätte gehen können. Die Zeile bleibt trotzdem stehen — sie ist die
    Nacharbeit, die sonst niemand sieht.
    """
    allowed = MAIL_TRANSITIONS[state]

    if not row["email"]:
        return [action for action in allowed if action is not MailState.VERSENDET]

    return list(allowed)


#: Die Marker, die an einer Zeile stehen können — der Katalog ohne den
#: Rückweg: `unbewertet` ist kein Knopf, sondern das Ausschalten des
#: gesetzten.
_READINESS_MARKERS: tuple[BuildReadiness, ...] = tuple(
    option.id
    for option in READINESS_OPTIONS
    if option.id is not BuildReadiness.UNBEWERTET
)


def _readiness_actions(state: MailState) -> list[BuildReadiness]:
    """Welche Marker diese Zeile setzen kann.

    Keine, sobald die Mail heraus ist: die Reihe beschreibt den Weg *bis* zur
    Mail („lässt sich bauen" → „ist gebaut, muss noch raus"), und neben einem
    „verschickt" widerspricht sie sich selbst. Wiedergefunden werden diese
    Zeilen über den Reiter — dieselbe Auskunft, nur an der Stelle, an der sie
    stimmt.
    """
    return [] if state is not MailState.OFFEN else list(_READINESS_MARKERS)


def _entry(row: sqlite3.Row) -> MailEntry:
    state = MailState(row["mail_state"])
    stored = MailState(row["stored_state"] or MailState.OFFEN.value)
    # NULL heißt hier „gilt nicht mehr" (die Mail ist heraus) und nicht „noch
    # nicht angesehen" — an der Zeile sieht beides gleich aus, gezählt wird
    # nur das zweite.
    readiness = BuildReadiness(row["readiness"] or BuildReadiness.UNBEWERTET.value)
    # Die freien Spalten der Anrufliste, so wie der Kontakt sie drüben auch
    # liefert: eine Zusage ohne Zusatzspalten hat hier eine leere Liste.
    extras: dict[str, str] = json.loads(row["extras"] or "{}")

    return MailEntry(
        contact_id=row["contact_id"],
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
        list_id=row["list_id"],
        list_name=row["list_name"] or "",
        list_archived=bool(row["list_archived"]),
        manual=bool(row["list_manual"]),
        promised_at=row["promised_at"],
        promised_by=row["promised_by"] or "",
        note=row["note"] or "",
        state=state,
        state_label=MAIL_STATE_LABELS[state],
        readiness=readiness,
        readiness_label=READINESS_LABELS[readiness],
        readiness_actions=_readiness_actions(state),
        oversized=bool(row["oversized_flag"]),
        # Der einzige Fall, in dem sich der angezeigte vom gespeicherten
        # Zustand unterscheidet: eine abgelaufene Frist. Ohne diesen Hinweis
        # sähe die Zeile aus, als hätte jemand sie abgeschlossen.
        automatic=state is not stored,
        sent_at=row["sent_at"],
        answered_at=row["answered_at"],
        followed_up_at=row["followed_up_at"],
        days_since_sent=_days_since(row["sent_at"]),
        mail_note=row["mail_note"] or "",
        updated_at=row["mail_updated_at"],
        updated_by=row["mail_updated_by"] or "",
        actions=_actions(row, state),
    )


def _counters(
    conn: sqlite3.Connection,
    cutoff: db.MailCutoffs,
    *,
    state: MailState | None,
    readiness: BuildReadiness | None,
    oversized: bool | None,
) -> MailCounters:
    """Die Zahlen der drei Filtergrößen.

    Jede zählt mit den Filtern der *anderen*, aber ohne ihren eigenen:
    steht die Reiterzeile auf „Offen", nennen die Marker die offenen Zusagen,
    und ihre Zahlen ergeben zusammen die Zahl auf dem Reiter. Umgekehrt
    genauso. Sonst stehen über der Liste zwei Aufteilungen derselben Menge,
    von denen nur eine zur Auswahl passt — und die andere zählt Zeilen mit,
    die gerade nicht in der Liste stehen.

    Ohne den eigenen Filter, weil eine Reihe sonst nur noch eine Zahl hätte:
    ein Filter über „Ready to Build" nullt die übrigen Marker, und damit gäbe
    es keinen Weg zurück, der eine Zahl nennt.

    Die **Suche** bleibt aus beiden Reihen heraus (siehe `mail_totals`).
    """
    state_filter = state.value if state else None
    marker_filter = readiness.value if readiness else None

    totals = db.mail_totals(conn, cutoff, marker_filter, oversized)
    # Zweite Abfrage, weil es eine zweite Frage ist — und weil sie andere
    # Filter braucht als die erste.
    markers = db.mail_readiness_totals(conn, cutoff, state_filter, oversized)
    # Dritte, aus demselben Grund: der Umfang zählt in der Auswahl der
    # beiden anderen und ohne sich selbst.
    oversized_total = db.mail_oversized_total(conn, cutoff, state_filter, marker_filter)

    def count(value: MailState) -> int:
        return totals.get(value.value, (0, 0))[0]

    def marked(value: BuildReadiness) -> int:
        return markers.get(value.value, 0)

    return MailCounters(
        gesamt=sum(total for total, _ in totals.values()),
        offen=count(MailState.OFFEN),
        versendet=count(MailState.VERSENDET),
        nachfassen=count(MailState.NACHFASSEN),
        nachgefasst=count(MailState.NACHGEFASST),
        positiv=count(MailState.POSITIV),
        abgelehnt=count(MailState.ABGELEHNT),
        keine_antwort=count(MailState.KEINE_ANTWORT),
        ohne_email=sum(without for _, without in totals.values()),
        ready_to_build=marked(BuildReadiness.READY_TO_BUILD),
        in_development=marked(BuildReadiness.IN_DEVELOPMENT),
        ready_to_mail=marked(BuildReadiness.READY_TO_MAIL),
        missing_content=marked(BuildReadiness.MISSING_CONTENT),
        oversized=oversized_total,
        unbewertet=marked(BuildReadiness.UNBEWERTET),
    )


def _board(
    conn: sqlite3.Connection,
    *,
    cutoff: db.MailCutoffs,
    query: str,
    state: MailState | None,
    readiness: BuildReadiness | None,
    oversized: bool | None,
    offset: int,
    limit: int,
) -> MailBoard:
    """Die ganze Ansicht. Einzige Stelle, die `MailBoard` erzeugt."""
    rows, matched, total = db.mail_page(
        conn,
        cutoff=cutoff,
        query=query,
        state=state.value if state else None,
        readiness=readiness.value if readiness else None,
        oversized=oversized,
        limit=limit,
        offset=offset,
    )

    return MailBoard(
        revision=db.revision(conn),
        # Die Zähler kennen die Filter der Ansicht: jede Größe zeigt ihre
        # Zahlen innerhalb der Auswahl der anderen.
        counters=_counters(
            conn, cutoff, state=state, readiness=readiness, oversized=oversized
        ),
        entries=[_entry(row) for row in rows],
        total=total,
        matched=matched,
        offset=offset,
        limit=limit,
        actions=list(MAIL_ACTIONS),
        readiness_options=list(READINESS_OPTIONS),
        scope_marker=SCOPE_MARKER,
    )


def _limits(offset: int, limit: int) -> tuple[int, int]:
    """Grenzen klemmen statt ablehnen — das ist eine URL, keine Eingabe."""
    return max(0, offset), max(1, min(limit, MAX_MAIL_PAGE_SIZE))


def get_board(
    *,
    query: str = "",
    state: MailState | None = None,
    readiness: BuildReadiness | None = None,
    oversized: bool | None = None,
    offset: int = 0,
    limit: int = MAIL_PAGE_SIZE,
) -> MailBoard:
    offset, limit = _limits(offset, limit)

    with db.connect() as conn:
        return _board(
            conn,
            cutoff=_cutoff(),
            query=query,
            state=state,
            readiness=readiness,
            oversized=oversized,
            offset=offset,
            limit=limit,
        )


def _times(
    row: sqlite3.Row, target: MailState
) -> tuple[str | None, str | None, str | None]:
    """Versand-, Antwort- und Nachfassdatum nach diesem Übergang.

    * `versendet` setzt das Versanddatum **neu** — auch beim Nachfassen per
      Mail, denn genau dann soll die Frist von vorn laufen. Ein Anruf zur
      *alten* Mail gehört dann nicht mehr dazu, also fällt er weg.
    * `nachgefasst` schreibt das Datum des Anrufs und lässt das Versanddatum
      stehen: die lange Frist läuft weiter ab dem Versand, sonst ließe sich
      „keine Antwort" durch Anrufe beliebig hinausschieben.
    * eine Antwort lässt das Versanddatum stehen: „am 3. geschrieben, am 9.
      geantwortet" ist die Auskunft, für die die Liste da ist.
    * `keine_antwort` ist keine Antwort und bekommt deshalb kein Antwortdatum.
    * `offen` verwirft alles — es ist der Rückweg aus dem Fehlklick, und ein
      Versanddatum ohne Versand wäre schlimmer als keines.
    """
    now = db.now()

    if target is MailState.VERSENDET:
        return now, None, None
    if target is MailState.NACHGEFASST:
        return row["sent_at"], None, now
    if target in (MailState.POSITIV, MailState.ABGELEHNT):
        return row["sent_at"], now, row["followed_up_at"]
    if target is MailState.KEINE_ANTWORT:
        return row["sent_at"], None, row["followed_up_at"]

    return None, None, None


def set_state(
    contact_id: str,
    request: MailUpdateRequest,
    *,
    username: str,
    query: str = "",
    state: MailState | None = None,
    readiness: BuildReadiness | None = None,
    oversized: bool | None = None,
    offset: int = 0,
    limit: int = MAIL_PAGE_SIZE,
) -> MailBoard:
    """Den Versandzustand einer Zusage setzen — oder Anmerkung, oder Marker.

    Alle Felder des Anfragekörpers sind einzeln setzbar, und jedes
    Weglassen heißt „unverändert". Ohne `state` bleibt der Zustand samt
    Versand- und Antwortdatum, wie er ist. Das ist kein Sonderfall aus
    Bequemlichkeit: notiert und eingeschätzt wird meistens *während* eine
    Zeile wartet, und für „wartet weiter" gibt es keinen Knopf.

    `readiness` als Schlüsselwort ist der *Filter* der Ansicht, `request.
    readiness` der zu setzende Marker — dieselbe Doppelung wie bei `state`.

    Antwortet mit der ganzen Ansicht für *dieselbe* Sicht, aus der der Klick
    kam (Suche, Filter, Seite reisen mit) — sonst spränge die Liste nach jedem
    Klick auf die erste Seite zurück. Dasselbe Verfahren wie beim Freigeben
    einer gesperrten Nummer.
    """
    offset, limit = _limits(offset, limit)
    cutoff = _cutoff()

    with db.connect() as conn:
        with db.transaction(conn):
            row = db.find_mail_entry(conn, contact_id, cutoff)

            if row is None:
                raise MailFollowupNotFoundError(
                    "Zu diesem Betrieb steht keine Zusage (mehr) in der Liste. "
                    "Bitte die Seite neu laden."
                )

            current = MailState(row["mail_state"])
            target = request.state

            if target is None:
                # Reine Anmerkung: der *gespeicherte* Zustand bleibt stehen,
                # nicht der angezeigte — sonst schriebe ein Notizzettel die
                # abgelaufene Frist als Entscheidung fest.
                stored = MailState(row["stored_state"] or MailState.OFFEN.value)
                target, sent_at, answered_at, followed_up_at = (
                    stored,
                    row["sent_at"],
                    row["answered_at"],
                    row["followed_up_at"],
                )
            elif target not in _actions(row, current):
                raise MailFollowupError(
                    f"„{row['betrieb']}“ steht auf "
                    f"„{MAIL_STATE_LABELS[current]}“ – daraus lässt sich "
                    f"„{MAIL_STATE_LABELS[target]}“ nicht machen. Bitte die "
                    "Seite neu laden."
                )
            else:
                sent_at, answered_at, followed_up_at = _times(row, target)

            if request.readiness is not None and target is not MailState.OFFEN:
                # Die Einschätzung gehört zum Weg bis zur Mail. Danach ist sie
                # keine Auskunft mehr, sondern ein Widerspruch — und ein still
                # weggeschriebener Wert wäre einer, den niemand mehr sieht.
                raise MailFollowupError(
                    f"Die Mail an „{row['betrieb']}“ ist heraus – eine "
                    "Bau-Einschätzung gibt es dafür nicht mehr. Sie kommt "
                    "zurück, sobald der Versand zurückgesetzt wird."
                )

            db.set_mail_status(
                conn,
                contact_id,
                state=target.value,
                sent_at=sent_at,
                answered_at=answered_at,
                followed_up_at=followed_up_at,
                # Fehlt der Marker, bleibt der gesetzte stehen: ein Klick auf
                # „Mail versendet" darf eine Einschätzung nicht verwerfen.
                # Entfernt wird sie mit `unbewertet`, nicht durch Weglassen.
                # Der *gespeicherte* Wert, nicht der angezeigte: sobald die
                # Mail heraus ist, liefert `readiness` NULL, und eine
                # Anmerkung an einer verschickten Zeile hätte die Einschätzung
                # damit gelöscht statt sie nur nicht mehr zu zeigen.
                readiness=(
                    row["stored_readiness"]
                    if request.readiness is None
                    else request.readiness.value
                ),
                # Derselbe Grund wie beim Marker darüber: geschrieben wird
                # immer die ganze Zeile, also muss „unverändert" hier
                # aufgelöst werden.
                oversized=(
                    bool(row["oversized_flag"])
                    if request.oversized is None
                    else request.oversized
                ),
                # Fehlt das Feld, bleibt die Anmerkung stehen: wer nur einen
                # Knopf drückt, soll nicht löschen, was jemand notiert hat.
                note=(
                    row["mail_note"] or ""
                    if request.note is None
                    else request.note.strip()
                ),
                updated_by=username,
            )

            # Eine Datenbank, ein Zähler: `revision` zählt jede Änderung an
            # `calls.db`, damit ein Poll auf beiden Seiten dieselbe Frage
            # beantworten kann.
            db.bump_revision(conn)

        return _board(
            conn,
            cutoff=cutoff,
            query=query,
            state=state,
            readiness=readiness,
            oversized=oversized,
            offset=offset,
            limit=limit,
        )


# --------------------------------------------------------------------------
# Von Hand erfasste Betriebe
# --------------------------------------------------------------------------
#
# Der Mailversand hat keine eigenen Kontakte — auch diese nicht. Was hier
# entsteht, ist ein Kontakt der Telefonakquise im Zustand `zugesagt`, in einer
# eigenen Liste, mit einer Protokollzeile als Nachweis. Alles andere wäre eine
# zweite Art Zeile, die überall mitgedacht werden müsste: in der Suche, in den
# Ausgaben, in der Doppelprüfung.
#
# Damit gelten für sie dieselben Regeln wie für importierte Zeilen, und das
# ist der Punkt: eine Zusage ist eine Zusage, gleich woher der Betrieb kam.


def _manual_list_id(conn: sqlite3.Connection, username: str) -> str:
    """Die Sammelliste der erfassten Betriebe — angelegt beim ersten Eintrag.

    Beim ersten und nicht beim Start der Anwendung: eine leere Liste in der
    Listenverwaltung, die nie jemand benutzt, wäre eine Frage ohne Antwort.
    """
    row = db.find_manual_list(conn)

    if row is not None:
        return str(row["id"])

    list_id = db.new_id()
    db.insert_list(
        conn,
        list_id=list_id,
        name=MANUAL_LIST_NAME,
        source_filename="",
        columns="[]",
        created_by=username,
        manual=True,
    )

    return list_id


def _manual_fields(request: ManualEntryRequest) -> dict[str, str]:
    """Das Formular als Kontaktspalten, alles ohne Randleerzeichen.

    Die Adresse geht durch dieselbe Prüfung wie die aus dem Telefonat — eine
    getippte Adresse ist nicht vertrauenswürdiger als eine erfragte. Deren
    Meldung ist allerdings die der Telefonakquise, und für den Aufrufer hier
    muss es eine des Mailversands sein: dieselbe Übersetzung an der
    Außenkante, die auch die CSV-Bausteine machen.
    """
    try:
        email = call_list_service.validated_email(request.email)
    except CallListError as exc:
        raise MailFollowupError(str(exc)) from exc

    betrieb = request.betrieb.strip()

    if not betrieb:
        raise MailFollowupError(
            "Ohne Betrieb geht es nicht — bitte den Namen eintragen."
        )

    if not email:
        raise MailFollowupError(
            "Ohne E-Mail-Adresse geht es nicht: die Zeile ist dazu da, dass eine "
            "Mail hinausgeht."
        )

    return {
        "betrieb": betrieb,
        "email": email,
        "telefon": request.telefon.strip(),
        "ort": request.ort.strip(),
        "plz": request.plz.strip(),
        "website": request.website.strip(),
        "gewerk": request.gewerk.strip(),
        "note": request.note.strip(),
    }


def _check_number(
    conn: sqlite3.Connection, fields: dict[str, str], *, force: bool
) -> str:
    """Prüfen, ob diese Nummer schon bekannt ist. Liefert ihren Schlüssel.

    Dieselbe Prüfung wie beim Import und mit denselben Meldungen
    (`call_list_service.blocked_reason`) — ein Betrieb, den wir schon anrufen,
    soll nicht daneben noch eine Zusage bekommen. Ohne Nummer gibt es nichts
    zu prüfen; das ist der Preis dafür, dass die Nummer freiwillig ist.

    `force` übergeht den Befund, nachdem die Meldung ihn benannt hat — der
    Weg, den auch das Löschen einer Liste nimmt: erst 409 mit dem Grund, dann
    die ausdrückliche Bestätigung.
    """
    key = db.phone_key(fields["telefon"])

    if not key or force:
        return key

    reason = call_list_service.blocked_reason(
        fields["betrieb"],
        key,
        db.phone_key_owners(conn),
        db.blacklist_lookup(conn, [key]),
    )

    if reason is not None:
        raise MailFollowupConflictError(reason)

    return key


def _block_number(
    conn: sqlite3.Connection, key: str, fields: dict[str, str], *, username: str
) -> None:
    """Die Nummer sperren, damit kein Import denselben Betrieb noch einmal holt.

    Dieselbe Rolle wie beim Import, nur mit eigener Herkunft: „von Hand
    erfasst" statt „importiert". Ohne diesen Eintrag wäre der Betrieb nur
    geschützt, solange die Sammelliste aktiv ist — und die Regel dieser
    Anwendung ist, dass eine Nummer, die einmal im Bestand war, nicht noch
    einmal hereinkommt.
    """
    if not key:
        return

    row = db.find_manual_list(conn)

    db.add_to_blacklist(
        conn,
        [
            [
                key,
                fields["telefon"],
                fields["betrieb"],
                BlacklistSource.ERFASST.value,
                str(row["id"]) if row else "",
                str(row["name"]) if row else "",
                "",
                db.now(),
                username,
            ]
        ],
    )


def create_entry(
    request: ManualEntryRequest,
    *,
    user_id: str,
    username: str,
    query: str = "",
    state: MailState | None = None,
    readiness: BuildReadiness | None = None,
    oversized: bool | None = None,
    offset: int = 0,
    limit: int = MAIL_PAGE_SIZE,
) -> MailBoard:
    """Einen Betrieb von Hand anlegen — Kontakt, Zusage und Nachweis in einem.

    Drei Schreibvorgänge in einer Transaktion, weil sie zusammen erst eine
    Zusage ergeben: der Kontakt (Zustand `zugesagt`, ohne Anrufversuch — es
    hat ja niemand angerufen), die Protokollzeile (wer wann für welche
    Adresse), und die Sperre der Nummer.

    Die Protokollzeile ist nicht Beiwerk: sie ist derselbe Nachweis, den ein
    Anruf hinterlässt, und der einzige Grund, warum in der Zeile später
    „Zusage am … von …" steht.
    """
    offset, limit = _limits(offset, limit)
    cutoff = _cutoff()
    fields = _manual_fields(request)

    with db.connect() as conn:
        with db.transaction(conn):
            key = _check_number(conn, fields, force=request.force)
            list_id = _manual_list_id(conn, username)
            contact_id = db.new_id()

            db.insert_contact(
                conn,
                contact_id=contact_id,
                list_id=list_id,
                state=ContactState.ZUGESAGT.value,
                fields=fields,
            )
            db.insert_event(
                conn,
                contact_id=contact_id,
                list_id=list_id,
                betrieb=fields["betrieb"],
                telefon=fields["telefon"],
                user_id=user_id,
                username=username,
                outcome=CallOutcome.ZUGESAGT.value,
                note=fields["note"],
                email=fields["email"],
                due_at=None,
                appointment_at=None,
            )
            _block_number(conn, key, fields, username=username)
            db.bump_revision(conn)

        return _board(
            conn,
            cutoff=cutoff,
            query=query,
            state=state,
            readiness=readiness,
            oversized=oversized,
            offset=offset,
            limit=limit,
        )


def update_entry(
    contact_id: str,
    request: ManualEntryRequest,
    *,
    user_id: str,
    username: str,
    query: str = "",
    state: MailState | None = None,
    readiness: BuildReadiness | None = None,
    oversized: bool | None = None,
    offset: int = 0,
    limit: int = MAIL_PAGE_SIZE,
) -> MailBoard:
    """Die Stammdaten eines von Hand erfassten Betriebs ändern.

    **Nur** dieser: was aus einer Anrufliste kam, gehört der Telefonakquise.
    Zwei Oberflächen auf denselben Kontakt wären zwei Wahrheiten, und die
    Zeile drüben trägt Zustand, Wiedervorlage und Anrufzähler, von denen hier
    nichts zu sehen ist.

    Eine geänderte **Adresse** hängt eine Protokollzeile an, die auf die
    bisherige zeigt (`corrects_event_id`) — dieselbe Mechanik wie die
    Richtigstellung im Anrufprotokoll, und aus demselben Grund: der Nachweis
    muss die Adresse nennen, für die die Zusage jetzt gilt. Ein Tippfehler im
    Namen tut das nicht, es ist derselbe Betrieb; deshalb bleibt es bei der
    Adresse als Auslöser.
    """
    offset, limit = _limits(offset, limit)
    cutoff = _cutoff()
    fields = _manual_fields(request)

    with db.connect() as conn:
        with db.transaction(conn):
            row = db.find_mail_entry(conn, contact_id, cutoff)

            if row is None:
                raise MailFollowupNotFoundError(
                    "Zu diesem Betrieb steht keine Zusage (mehr) in der Liste. "
                    "Bitte die Seite neu laden."
                )

            if not row["list_manual"]:
                raise MailFollowupError(
                    f"„{row['betrieb']}“ kommt aus der Liste "
                    f"„{row['list_name']}“ und wird dort gepflegt. Ändern "
                    "lassen sich hier nur von Hand erfasste Betriebe."
                )

            # Aus der Nummer gerechnet statt aus einer weiteren Spalte der
            # Mailzeile: der Schlüssel ist abgeleitet, und die Versandliste
            # hat mit ihm sonst nichts zu tun.
            old_key = db.phone_key(str(row["telefon"] or ""))
            key = db.phone_key(fields["telefon"])

            if key != old_key:
                # Nur die *geänderte* Nummer wird geprüft: die eigene steht in
                # der Sperrliste, seit dieser Betrieb angelegt wurde, und ein
                # Formular, das an seinen eigenen Daten scheitert, ließe sich
                # überhaupt nicht mehr absenden.
                _check_number(conn, fields, force=request.force)

            db.update_contact_fields(conn, contact_id, fields)

            if fields["email"] != row["email"]:
                # Die Zusage gilt ab jetzt für eine andere Adresse. Angehängt
                # statt überschrieben: das Protokoll kennt kein UPDATE.
                db.insert_event(
                    conn,
                    contact_id=contact_id,
                    list_id=str(row["list_id"]),
                    betrieb=fields["betrieb"],
                    telefon=fields["telefon"],
                    user_id=user_id,
                    username=username,
                    outcome=CallOutcome.ZUGESAGT.value,
                    note=fields["note"],
                    email=fields["email"],
                    due_at=None,
                    appointment_at=None,
                    corrects_event_id=db.latest_event_id(conn, contact_id),
                )

            if key != old_key:
                # Die alte Nummer freigeben und die neue sperren: sonst
                # blockierte ein Zahlendreher für immer eine Nummer, die
                # einem ganz anderen Betrieb gehört.
                if old_key:
                    db.remove_from_blacklist(conn, old_key)
                _block_number(conn, key, fields, username=username)

            db.bump_revision(conn)

        return _board(
            conn,
            cutoff=cutoff,
            query=query,
            state=state,
            readiness=readiness,
            oversized=oversized,
            offset=offset,
            limit=limit,
        )


def export_board() -> CallListExport:
    """Die Versandliste als CSV.

    Für den Bericht und für die Arbeit außerhalb dieses Werkzeugs: die Datei
    enthält jede Zusage mit dem, was daraus geworden ist — einschließlich der
    Zeilen, die die Frist als unbeantwortet ausweist.
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
        "Zusage am (UTC)",
        "Zusage aufgenommen von",
        "Versandstatus",
        "automatisch",
        "Bau-Einschätzung",
        "Umfang",
        "Mail versendet am (UTC)",
        "Tage seit Versand",
        "Nachgefasst am (UTC)",
        "Antwort am (UTC)",
        "Zuletzt geändert von",
        "Anmerkung (Telefonat)",
        "Anmerkung (Versand)",
    ]

    with db.connect() as conn:
        entries = [_entry(row) for row in db.all_mail_entries(conn, _cutoff())]

    rows = [
        [
            entry.betrieb,
            entry.email,
            entry.telefon,
            entry.ort,
            entry.plz,
            entry.website,
            entry.gewerk,
            entry.list_name,
            entry.promised_at or "",
            entry.promised_by,
            MAIL_STATE_LABELS[entry.state],
            "ja" if entry.automatic else "",
            # Leer statt „noch nicht eingeschätzt": in einer Tabelle mit 400
            # Zeilen ist die leere Zelle die Auskunft, die man filtern kann.
            (
                ""
                if entry.readiness is BuildReadiness.UNBEWERTET
                else READINESS_LABELS[entry.readiness]
            ),
            # Wie oben leer, wenn nichts gesagt wurde: die leere Zelle ist
            # die filterbare Auskunft.
            SCOPE_MARKER.label if entry.oversized else "",
            entry.sent_at or "",
            "" if entry.days_since_sent is None else str(entry.days_since_sent),
            entry.followed_up_at or "",
            entry.answered_at or "",
            entry.updated_by,
            entry.note,
            entry.mail_note,
        ]
        for entry in entries
    ]

    stamp = db.now()[:10].replace("-", "")

    return CallListExport(
        buffer=BytesIO(csv_rows_to_str([header, *rows]).encode(_EXPORT_ENCODING)),
        filename=f"mailversand_{stamp}.csv",
    )


__all__ = [
    "MailFollowupConflictError",
    "MailFollowupError",
    "MailFollowupNotFoundError",
    "create_entry",
    "export_board",
    "get_board",
    "set_state",
    "update_entry",
]
