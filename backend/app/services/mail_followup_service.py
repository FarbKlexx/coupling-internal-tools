"""Fachregeln des Mailversands.

Was nach der Zusage passiert. Die Telefonakquise beantwortet „dürfen wir
schreiben?" und legt den Nachweis dafür an; hier steht die andere Hälfte:
*haben* wir geschrieben, und was kam zurück.

Drei Entscheidungen prägen dieses Modul:

* **Keine eigenen Kontakte.** Die Zeilen sind die Kontakte der
  Telefonakquise im Zustand `zugesagt`. Ein Betrieb, dessen Zusage
  richtiggestellt wird, verschwindet damit von selbst aus der Liste — und
  nicht erst, wenn jemand daran denkt.
* **Die Frist wird gerechnet, nicht geschrieben.** „Keine Antwort nach 30
  Tagen" folgt aus dem Versanddatum (siehe `MailState` und `_MAIL_STATE` im
  Datenmodul). Es gibt in dieser Anwendung keinen Hintergrundjob, und ein
  Feld, das erst beim nächsten Klick nachgezogen würde, wäre bis dahin
  falsch.
* **Die Übergänge stehen in einer Tabelle**, und dieselbe Tabelle bestückt die
  Knöpfe der Zeile (`MAIL_TRANSITIONS`). Die Oberfläche kann deshalb keinen
  Übergang anbieten, den das Schreiben ablehnt — das Muster von
  `CallDecision.correctable`.

Wie überall in dieser Anwendung antwortet jeder schreibende Aufruf mit der
*ganzen* Ansicht. Anders als beim Kanban-Board und beim Arbeitsstand ist die
hier geblättert: Zusagen sammeln sich an und werden nie weniger.
"""

import sqlite3
from datetime import datetime, timedelta, timezone
from io import BytesIO

from app.core import call_list_db as db
from app.core.csv_utils import csv_rows_to_str
from app.schemas.mail_followup import (
    MAIL_ACTIONS,
    MAIL_PAGE_SIZE,
    MAIL_STATE_LABELS,
    MAIL_TIMEOUT_DAYS,
    MAIL_TRANSITIONS,
    MAX_MAIL_PAGE_SIZE,
    MailBoard,
    MailCounters,
    MailEntry,
    MailState,
    MailUpdateRequest,
)
from app.services.call_list_service import CallListExport

#: Kodierung der Ausgabe. Mit BOM, weil diese Datei in Excel geöffnet wird —
#: ohne sie steht dort „Zaunbau MÃ¼ller". Dieselbe Begründung wie bei den
#: Ausgaben der Telefonakquise.
_EXPORT_ENCODING = "utf-8-sig"


class MailFollowupError(Exception):
    """Alles, was der Anwender selbst beheben kann → 400."""


class MailFollowupNotFoundError(MailFollowupError):
    """Diese Zusage gibt es nicht (mehr) → 404."""


def _cutoff() -> str:
    """Der Zeitpunkt, vor dem ein Versand als unbeantwortet gilt.

    Einmal pro Anfrage gerechnet und dann durchgereicht: Liste, Zähler und
    Schreibpfad sollen denselben Stichtag benutzen, sonst wechselt eine Zeile
    zwischen zwei Abfragen derselben Antwort die Gruppe.
    """
    moment = datetime.now(timezone.utc) - timedelta(days=MAIL_TIMEOUT_DAYS)
    return moment.strftime("%Y-%m-%dT%H:%M:%SZ")


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


def _entry(row: sqlite3.Row) -> MailEntry:
    state = MailState(row["mail_state"])
    stored = MailState(row["stored_state"] or MailState.OFFEN.value)

    return MailEntry(
        contact_id=row["contact_id"],
        betrieb=row["betrieb"],
        telefon=row["telefon"],
        email=row["email"],
        ort=row["ort"],
        plz=row["plz"],
        website=row["website"],
        gewerk=row["gewerk"],
        list_id=row["list_id"],
        list_name=row["list_name"] or "",
        list_archived=bool(row["list_archived"]),
        promised_at=row["promised_at"],
        promised_by=row["promised_by"] or "",
        note=row["note"] or "",
        state=state,
        state_label=MAIL_STATE_LABELS[state],
        # Der einzige Fall, in dem sich der angezeigte vom gespeicherten
        # Zustand unterscheidet: die abgelaufene Frist. Ohne diesen Hinweis
        # sähe die Zeile aus, als hätte jemand sie abgeschlossen.
        automatic=state is not stored,
        sent_at=row["sent_at"],
        answered_at=row["answered_at"],
        days_since_sent=_days_since(row["sent_at"]),
        mail_note=row["mail_note"] or "",
        updated_at=row["mail_updated_at"],
        updated_by=row["mail_updated_by"] or "",
        actions=_actions(row, state),
    )


def _counters(conn: sqlite3.Connection, cutoff: str) -> MailCounters:
    totals = db.mail_totals(conn, cutoff)

    def count(state: MailState) -> int:
        return totals.get(state.value, (0, 0))[0]

    return MailCounters(
        gesamt=sum(total for total, _ in totals.values()),
        offen=count(MailState.OFFEN),
        versendet=count(MailState.VERSENDET),
        positiv=count(MailState.POSITIV),
        abgelehnt=count(MailState.ABGELEHNT),
        keine_antwort=count(MailState.KEINE_ANTWORT),
        ohne_email=sum(without for _, without in totals.values()),
    )


def _board(
    conn: sqlite3.Connection,
    *,
    cutoff: str,
    query: str,
    state: MailState | None,
    offset: int,
    limit: int,
) -> MailBoard:
    """Die ganze Ansicht. Einzige Stelle, die `MailBoard` erzeugt."""
    rows, matched, total = db.mail_page(
        conn,
        cutoff=cutoff,
        query=query,
        state=state.value if state else None,
        limit=limit,
        offset=offset,
    )

    return MailBoard(
        revision=db.revision(conn),
        counters=_counters(conn, cutoff),
        entries=[_entry(row) for row in rows],
        total=total,
        matched=matched,
        offset=offset,
        limit=limit,
        actions=list(MAIL_ACTIONS),
    )


def _limits(offset: int, limit: int) -> tuple[int, int]:
    """Grenzen klemmen statt ablehnen — das ist eine URL, keine Eingabe."""
    return max(0, offset), max(1, min(limit, MAX_MAIL_PAGE_SIZE))


def get_board(
    *,
    query: str = "",
    state: MailState | None = None,
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
            offset=offset,
            limit=limit,
        )


def _times(row: sqlite3.Row, target: MailState) -> tuple[str | None, str | None]:
    """Versand- und Antwortdatum nach diesem Übergang.

    * `versendet` setzt das Versanddatum **neu** — auch beim Nachfassen, denn
      genau dann soll die Frist von vorn laufen.
    * eine Antwort lässt das Versanddatum stehen: „am 3. geschrieben, am 9.
      geantwortet" ist die Auskunft, für die die Liste da ist.
    * `keine_antwort` ist keine Antwort und bekommt deshalb kein Antwortdatum.
    * `offen` verwirft beides — es ist der Rückweg aus dem Fehlklick, und ein
      Versanddatum ohne Versand wäre schlimmer als keines.
    """
    now = db.now()

    if target is MailState.VERSENDET:
        return now, None
    if target in (MailState.POSITIV, MailState.ABGELEHNT):
        return row["sent_at"], now
    if target is MailState.KEINE_ANTWORT:
        return row["sent_at"], None

    return None, None


def set_state(
    contact_id: str,
    request: MailUpdateRequest,
    *,
    username: str,
    query: str = "",
    state: MailState | None = None,
    offset: int = 0,
    limit: int = MAIL_PAGE_SIZE,
) -> MailBoard:
    """Den Versandzustand einer Zusage setzen — oder nur ihre Anmerkung.

    Ohne `state` im Anfragekörper bleibt der Zustand samt Versand- und
    Antwortdatum, wie er ist, und nur die Anmerkung wird geschrieben. Das ist
    kein Sonderfall aus Bequemlichkeit: notiert wird meistens *während* eine
    Zeile wartet, und für „wartet weiter" gibt es keinen Knopf.

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
                target, sent_at, answered_at = (
                    stored,
                    row["sent_at"],
                    row["answered_at"],
                )
            elif target not in _actions(row, current):
                raise MailFollowupError(
                    f"„{row['betrieb']}“ steht auf "
                    f"„{MAIL_STATE_LABELS[current]}“ – daraus lässt sich "
                    f"„{MAIL_STATE_LABELS[target]}“ nicht machen. Bitte die "
                    "Seite neu laden."
                )
            else:
                sent_at, answered_at = _times(row, target)

            db.set_mail_status(
                conn,
                contact_id,
                state=target.value,
                sent_at=sent_at,
                answered_at=answered_at,
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
        "Mail versendet am (UTC)",
        "Tage seit Versand",
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
            entry.sent_at or "",
            "" if entry.days_since_sent is None else str(entry.days_since_sent),
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
    "MailFollowupError",
    "MailFollowupNotFoundError",
    "export_board",
    "get_board",
    "set_state",
]
