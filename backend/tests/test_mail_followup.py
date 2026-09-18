"""Der Mailversand — was aus einer Zusage geworden ist.

Zwei Dinge sind hier interessant genug für Tests, und beide betreffen den
Übergang zwischen den zwei Werkzeugen:

* Die Liste hat **keine eigenen Kontakte**. Sie zeigt genau die Zusagen der
  Telefonakquise, und sie muss sich mitbewegen, wenn dort eine Zusage
  zurückgenommen wird.
* Die Zustände „nachfassen" und „keine Antwort" werden **gerechnet**. Es gibt
  keinen Hintergrundjob, der sie setzt — sie folgen aus dem Versanddatum, und
  genau das lässt sich nur prüfen, indem ein Versanddatum von
  gestern-vor-40-Tagen in die Datenbank geschrieben wird.

Die Zusagen entstehen hier über die echte HTTP-Oberfläche (Import → Anruf →
Zusage), nicht durch direktes INSERT: sonst prüft der Test eine Datenlage,
die die Anwendung so nie erzeugt.
"""

import sqlite3
from datetime import datetime, timedelta, timezone

import pytest

from app.core import call_list_db as db
from app.schemas.access import Page
from app.schemas.mail_followup import (
    MAIL_FOLLOWUP_DAYS,
    MAIL_TIMEOUT_DAYS,
    MAIL_TRANSITIONS,
    READINESS_OPTIONS,
    BuildReadiness,
    MailState,
)

CSV = (
    "Betrieb;Telefon;Ort;E-Mail\r\n"
    "Erster Betrieb;05221 111;Herford;eins@example.de\r\n"
    "Zweiter Betrieb;05221 222;Enger;zwei@example.de\r\n"
    "Dritter Betrieb;05221 333;Bünde;\r\n"
).encode("utf-8")

#: Eine zweite Liste mit einem unberührten Kontakt — für die Rangfolge im
#: Anrufvorrat braucht es etwas, das *hinter* dem Nachfassen stehen kann.
NEUE_LISTE = (
    "Betrieb;Telefon;Ort;E-Mail\r\n"
    "Vierter Betrieb;05221 444;Kirchlengern;vier@example.de\r\n"
).encode("utf-8")


@pytest.fixture
def zusagen(client, call_db):
    """Drei Betriebe importiert, zwei davon mit Zusage.

    Liefert `(client, ids)` mit den Kontakt-IDs der beiden Zusagen, in der
    Reihenfolge, in der sie zugesagt haben.
    """
    upload = client.post(
        "/telefonakquise/lists",
        files={"file": ("handwerker.csv", CSV, "text/csv")},
        data={"name": "Handwerker Herford"},
    )
    assert upload.status_code == 200, upload.text

    ids = []
    # Der Arbeitsplatz liefert immer genau einen Kontakt; „Erster" und
    # „Dritter" sagen zu, „Zweiter" lehnt ab.
    for outcome in ("zugesagt", "abgelehnt", "zugesagt"):
        contact = client.get("/telefonakquise/state").json()["contact"]
        assert contact is not None
        answer = client.post(
            f"/telefonakquise/contacts/{contact['id']}/outcome",
            json={"outcome": outcome},
        )
        assert answer.status_code == 200, answer.text
        if outcome == "zugesagt":
            ids.append(contact["id"])

    return client, ids


def _board(client, **params):
    response = client.get("/mailversand/board", params=params)
    assert response.status_code == 200, response.text
    return response.json()


def _click(client, contact_id, state, expected=200, **params):
    response = client.post(
        f"/mailversand/contacts/{contact_id}",
        json={"state": state},
        params=params,
    )
    assert response.status_code == expected, response.text
    return response.json()


def _mark(client, contact_id, readiness, expected=200, **params):
    """Einen Marker setzen — ohne Zustand im Körper, wie die Oberfläche."""
    response = client.post(
        f"/mailversand/contacts/{contact_id}",
        json={"readiness": readiness},
        params=params,
    )
    assert response.status_code == expected, response.text
    return response.json()


def _scope(client, contact_id, oversized, expected=200, **params):
    """Den Umfangs-Marker setzen — allein im Körper, wie die Oberfläche."""
    response = client.post(
        f"/mailversand/contacts/{contact_id}",
        json={"oversized": oversized},
        params=params,
    )
    assert response.status_code == expected, response.text
    return response.json()


def _entry(board, contact_id):
    return next(e for e in board["entries"] if e["contact_id"] == contact_id)


def _backdate(call_db, contact_id, days):
    """Das Versanddatum einer Zeile in die Vergangenheit schieben.

    Der einzige Weg, die Frist zu prüfen, ohne die Uhr zu stellen: der
    Zustand „keine Antwort" hängt allein an diesem Feld.
    """
    moment = datetime.now(timezone.utc) - timedelta(days=days)
    conn = sqlite3.connect(call_db)
    conn.execute(
        "UPDATE mail_status SET sent_at = ? WHERE contact_id = ?",
        (moment.strftime("%Y-%m-%dT%H:%M:%SZ"), contact_id),
    )
    conn.commit()
    conn.close()


# ------------------------------
# Zugang
# ------------------------------


def test_without_a_session_there_is_no_board(anon_client):
    assert anon_client.get("/mailversand/board").status_code == 401


def test_the_page_permission_is_its_own(make_user):
    """Wer telefonieren darf, darf deshalb noch nicht versenden.

    Die beiden Werkzeuge teilen sich die Daten, nicht die Berechtigung — sonst
    wäre die neue Seite für jeden Anrufer sichtbar, was der Punkt der
    Aufteilung gewesen wäre.
    """
    caller, _ = make_user("anruferin", pages=[Page.TELEFONAKQUISE])
    sender, _ = make_user("versenderin", pages=[Page.MAILVERSAND])

    assert caller.get("/mailversand/board").status_code == 403
    assert sender.get("/mailversand/board").status_code == 200
    # Und umgekehrt: die Versandseite öffnet die Anrufliste nicht.
    assert sender.get("/telefonakquise/state").status_code == 403


# ------------------------------
# Die Liste
# ------------------------------


def test_the_board_shows_the_promises_and_nothing_else(zusagen):
    client, ids = zusagen

    board = _board(client)

    assert [entry["contact_id"] for entry in board["entries"]] == ids
    assert board["total"] == 2
    assert board["counters"]["gesamt"] == 2
    assert board["counters"]["offen"] == 2
    # Der abgelehnte Betrieb taucht nirgends auf.
    assert "Zweiter Betrieb" not in {entry["betrieb"] for entry in board["entries"]}


def test_a_promise_without_an_address_stays_visible_but_cannot_be_sent(zusagen):
    """Die Nacharbeit, die sonst niemand sieht.

    Sie aus der Liste zu nehmen wäre die bequeme Variante — und genau die,
    bei der die Zusage stillschweigend verfällt.
    """
    client, _ = zusagen

    board = _board(client)
    without = next(e for e in board["entries"] if e["betrieb"] == "Dritter Betrieb")

    assert without["email"] == ""
    assert board["counters"]["ohne_email"] == 1
    assert "versendet" not in without["actions"]


def test_the_promise_carries_who_took_it_and_when(zusagen):
    """Der Nachweis, auf den sich der Versand stützt, steht in der Zeile."""
    client, _ = zusagen

    entry = _board(client)["entries"][0]

    assert entry["promised_by"] == "chefin"
    assert entry["promised_at"]


def test_a_corrected_promise_leaves_the_board(zusagen):
    """Die Liste hat keine eigenen Kontakte — sie folgt der Telefonakquise.

    Wird eine Zusage richtiggestellt, verschwindet die Zeile von selbst. Eine
    eigene Kopie müsste jemand nachpflegen, und niemand würde daran denken.
    """
    client, ids = zusagen
    _click(client, ids[0], "versendet")

    latest = client.get("/telefonakquise/decisions").json()["entries"]
    correction = next(e for e in latest if e["contact_id"] == ids[0])
    fixed = client.post(
        f"/telefonakquise/decisions/{correction['event_id']}/correct",
        json={"outcome": "kein_bedarf"},
    )
    assert fixed.status_code == 200, fixed.text

    board = _board(client)

    assert [entry["contact_id"] for entry in board["entries"]] == ids[1:]


# ------------------------------
# Die Knöpfe
# ------------------------------


def test_sending_records_the_moment_and_the_account(zusagen):
    client, ids = zusagen

    board = _click(client, ids[0], "versendet")
    entry = next(e for e in board["entries"] if e["contact_id"] == ids[0])

    assert entry["state"] == "versendet"
    assert entry["sent_at"]
    assert entry["answered_at"] is None
    assert entry["updated_by"] == "chefin"
    assert entry["days_since_sent"] == 0
    assert board["counters"] == {
        **board["counters"],
        "offen": 1,
        "versendet": 1,
    }


def test_an_answer_keeps_the_send_date(zusagen):
    """„Am 3. geschrieben, am 9. geantwortet" ist die Auskunft, die zählt."""
    client, ids = zusagen
    sent = _click(client, ids[0], "versendet")["entries"]
    sent_at = next(e for e in sent if e["contact_id"] == ids[0])["sent_at"]

    board = _click(client, ids[0], "positiv")
    entry = next(e for e in board["entries"] if e["contact_id"] == ids[0])

    assert entry["state"] == "positiv"
    assert entry["sent_at"] == sent_at
    assert entry["answered_at"]
    assert board["counters"]["positiv"] == 1


def test_a_reset_drops_the_dates_but_keeps_the_author(zusagen):
    client, ids = zusagen
    _click(client, ids[0], "versendet")

    board = _click(client, ids[0], "offen")
    entry = next(e for e in board["entries"] if e["contact_id"] == ids[0])

    assert entry["state"] == "offen"
    assert entry["sent_at"] is None
    assert entry["answered_at"] is None
    # Die Zeile bleibt stehen: der Unterschied zwischen „noch nichts
    # passiert" und „zurückgesetzt von chefin" ist genau das, wonach morgen
    # jemand fragt.
    assert entry["updated_by"] == "chefin"


def test_a_transition_the_row_does_not_offer_is_refused(zusagen):
    """Die Knöpfe der Zeile und die Prüfung beim Schreiben sind dieselbe Tabelle.

    Ohne diese Prüfung stünde eine Zeile auf „Antwort positiv", ohne dass je
    eine Mail heraus war — etwa nach einem zweiten Browserfenster.
    """
    client, ids = zusagen

    body = _click(client, ids[0], "positiv", expected=400)

    assert "nicht machen" in body["detail"]


def test_a_promise_without_an_address_cannot_be_marked_as_sent(zusagen):
    client, _ = zusagen
    without = next(
        e for e in _board(client)["entries"] if e["betrieb"] == "Dritter Betrieb"
    )

    body = _click(client, without["contact_id"], "versendet", expected=400)

    assert "Dritter Betrieb" in body["detail"]


def test_a_note_survives_a_click_that_does_not_mention_it(zusagen):
    client, ids = zusagen
    client.post(
        f"/mailversand/contacts/{ids[0]}",
        json={"state": "versendet", "note": "Angebot mit Preisliste"},
    )

    board = _click(client, ids[0], "positiv")
    entry = next(e for e in board["entries"] if e["contact_id"] == ids[0])

    assert entry["mail_note"] == "Angebot mit Preisliste"


def test_a_contact_that_is_gone_answers_404(zusagen):
    client, _ = zusagen

    assert (
        client.post(
            "/mailversand/contacts/gibtsnicht", json={"state": "versendet"}
        ).status_code
        == 404
    )


# ------------------------------
# Die Frist
# ------------------------------


def test_a_send_without_an_answer_becomes_unanswered_after_the_deadline(
    zusagen, call_db
):
    client, ids = zusagen
    _click(client, ids[0], "versendet")

    _backdate(call_db, ids[0], MAIL_TIMEOUT_DAYS + 1)
    board = _board(client)
    entry = next(e for e in board["entries"] if e["contact_id"] == ids[0])

    assert entry["state"] == "keine_antwort"
    # Angezeigt, nicht angeklickt — sonst sieht es aus, als hätte jemand die
    # Zeile abgeschlossen.
    assert entry["automatic"] is True
    assert entry["days_since_sent"] == MAIL_TIMEOUT_DAYS + 1
    assert board["counters"]["keine_antwort"] == 1
    assert board["counters"]["versendet"] == 0


def test_one_day_short_of_the_deadline_is_not_yet_unanswered(zusagen, call_db):
    """Am 29. Tag ist die Zeile fällig zum Anruf, aber nicht abgeschrieben."""
    client, ids = zusagen
    _click(client, ids[0], "versendet")

    _backdate(call_db, ids[0], MAIL_TIMEOUT_DAYS - 1)
    entry = next(e for e in _board(client)["entries"] if e["contact_id"] == ids[0])

    assert entry["state"] == "nachfassen"


def test_a_late_answer_can_still_be_recorded(zusagen, call_db):
    """Gerechnet statt geschrieben heißt: nichts ist zugemauert.

    Am 31. Tag kommt die Antwort doch — und wird eingetragen wie jede andere.
    """
    client, ids = zusagen
    _click(client, ids[0], "versendet")
    _backdate(call_db, ids[0], MAIL_TIMEOUT_DAYS + 1)

    board = _click(client, ids[0], "positiv")
    entry = next(e for e in board["entries"] if e["contact_id"] == ids[0])

    assert entry["state"] == "positiv"
    assert entry["automatic"] is False


def test_following_up_restarts_the_deadline(zusagen, call_db):
    client, ids = zusagen
    _click(client, ids[0], "versendet")
    _backdate(call_db, ids[0], MAIL_TIMEOUT_DAYS + 5)

    board = _click(client, ids[0], "versendet")
    entry = next(e for e in board["entries"] if e["contact_id"] == ids[0])

    assert entry["state"] == "versendet"
    assert entry["days_since_sent"] == 0


def test_marking_it_by_hand_needs_no_deadline(zusagen):
    client, ids = zusagen
    _click(client, ids[0], "versendet")

    board = _click(client, ids[0], "keine_antwort")
    entry = next(e for e in board["entries"] if e["contact_id"] == ids[0])

    assert entry["state"] == "keine_antwort"
    assert entry["automatic"] is False
    assert entry["answered_at"] is None


# ------------------------------
# Die kürzere Frist: nachfassen
# ------------------------------


def test_a_send_becomes_due_for_a_call_after_the_shorter_deadline(zusagen, call_db):
    """Der Zwischenstand zwischen „wartet" und „abgeschrieben".

    Nach zehn Tagen ist die Mail gelesen oder liegengeblieben — beides
    beantwortet nur ein Anruf. Wie „keine Antwort" folgt das aus dem
    Versanddatum und gilt damit rückwirkend für jede Zeile, die schon vorher
    verschickt war.
    """
    client, ids = zusagen
    _click(client, ids[0], "versendet")

    _backdate(call_db, ids[0], MAIL_FOLLOWUP_DAYS + 1)
    board = _board(client)
    entry = _entry(board, ids[0])

    assert entry["state"] == "nachfassen"
    # Angezeigt, nicht angeklickt: niemand stellt eine Fälligkeit von Hand.
    assert entry["automatic"] is True
    assert entry["days_since_sent"] == MAIL_FOLLOWUP_DAYS + 1
    assert board["counters"]["nachfassen"] == 1
    assert board["counters"]["versendet"] == 0
    assert board["counters"]["keine_antwort"] == 0


def test_one_day_short_of_the_call_deadline_is_still_waiting(zusagen, call_db):
    client, ids = zusagen
    _click(client, ids[0], "versendet")

    _backdate(call_db, ids[0], MAIL_FOLLOWUP_DAYS - 1)
    entry = _entry(_board(client), ids[0])

    assert entry["state"] == "versendet"
    assert entry["automatic"] is False


def test_the_tab_finds_the_rows_that_are_due(zusagen, call_db):
    """Der Reiter filtert über den *gerechneten* Zustand.

    In der Spalte steht „versendet" — gäbe es den Filter nur darauf, wäre der
    Reiter, für den das Ganze gebaut ist, immer leer.
    """
    client, ids = zusagen
    _click(client, ids[0], "versendet")
    _backdate(call_db, ids[0], MAIL_FOLLOWUP_DAYS + 2)

    board = _board(client, state="nachfassen")

    assert [entry["contact_id"] for entry in board["entries"]] == [ids[0]]
    assert board["matched"] == 1


def test_the_call_is_recorded_and_takes_the_row_out_of_the_tab(zusagen, call_db):
    """„Nachgefasst" hält fest, dass angerufen wurde — mehr nicht.

    Das Versanddatum bleibt stehen, damit die lange Frist weiterläuft; sonst
    ließe sich „keine Antwort" durch Anrufe beliebig hinausschieben.
    """
    client, ids = zusagen
    _click(client, ids[0], "versendet")
    _backdate(call_db, ids[0], MAIL_FOLLOWUP_DAYS + 3)
    sent_at = _entry(_board(client), ids[0])["sent_at"]

    board = _click(client, ids[0], "nachgefasst")
    entry = _entry(board, ids[0])

    assert entry["state"] == "nachgefasst"
    assert entry["automatic"] is False
    assert entry["followed_up_at"]
    assert entry["sent_at"] == sent_at
    assert entry["answered_at"] is None
    assert board["counters"]["nachfassen"] == 0
    assert board["counters"]["nachgefasst"] == 1


def test_the_button_exists_only_where_something_is_due(zusagen):
    """Wo nichts fällig ist, gibt es nichts zu quittieren."""
    client, ids = zusagen
    board = _click(client, ids[0], "versendet")

    assert "nachgefasst" not in _entry(board, ids[0])["actions"]

    body = _click(client, ids[0], "nachgefasst", expected=400)

    assert "Erster Betrieb" in body["detail"]


def test_a_followed_up_row_still_runs_out_after_the_long_deadline(zusagen, call_db):
    """Ein Anruf hält die Zeile nicht ewig offen.

    Nach 30 Tagen ist auch eine nachtelefonierte Zusage unbeantwortet — sonst
    bliebe sie für immer unter „wartet weiter" stehen.
    """
    client, ids = zusagen
    _click(client, ids[0], "versendet")
    _backdate(call_db, ids[0], MAIL_FOLLOWUP_DAYS + 1)
    _click(client, ids[0], "nachgefasst")

    _backdate(call_db, ids[0], MAIL_TIMEOUT_DAYS + 1)
    entry = _entry(_board(client), ids[0])

    assert entry["state"] == "keine_antwort"
    assert entry["automatic"] is True
    # Der Anruf bleibt trotzdem verzeichnet — er hat stattgefunden.
    assert entry["followed_up_at"]


def test_sending_again_starts_over(zusagen, call_db):
    """Eine neue Mail macht den Anruf zur alten gegenstandslos."""
    client, ids = zusagen
    _click(client, ids[0], "versendet")
    _backdate(call_db, ids[0], MAIL_FOLLOWUP_DAYS + 1)
    _click(client, ids[0], "nachgefasst")

    entry = _entry(_click(client, ids[0], "versendet"), ids[0])

    assert entry["state"] == "versendet"
    assert entry["days_since_sent"] == 0
    assert entry["followed_up_at"] is None


def test_a_note_on_a_due_row_does_not_freeze_the_deadline(zusagen, call_db):
    """Dieselbe Regel wie bei der langen Frist, eine Stufe früher.

    Gespeichert steht dort weiter „versendet"; schriebe die Notiz den
    angezeigten Zustand fest, wäre die Zeile ab dem 30. Tag nicht mehr
    „keine Antwort", sondern für immer „nachfassen".
    """
    client, ids = zusagen
    _click(client, ids[0], "versendet")
    _backdate(call_db, ids[0], MAIL_FOLLOWUP_DAYS + 1)

    response = client.post(
        f"/mailversand/contacts/{ids[0]}",
        json={"note": "Mailbox, nochmal versuchen"},
    )
    assert response.status_code == 200, response.text
    entry = _entry(response.json(), ids[0])

    assert entry["mail_note"] == "Mailbox, nochmal versuchen"
    assert entry["state"] == "nachfassen"
    assert entry["followed_up_at"] is None

    _backdate(call_db, ids[0], MAIL_TIMEOUT_DAYS + 1)

    assert _entry(_board(client), ids[0])["state"] == "keine_antwort"


def test_a_database_from_before_the_call_deadline_gets_the_new_column(zusagen, call_db):
    """`CREATE TABLE IF NOT EXISTS` fasst eine vorhandene Tabelle nicht an.

    In Produktion liegt `calls.db` auf einem Volume und überlebt jeden Build:
    dort steht eine `mail_status` ohne `followed_up_at`, mit Zeilen, auf die
    längst geklickt wurde. Genau die sollen die neue Frist rückwirkend
    bekommen.
    """
    client, ids = zusagen
    _click(client, ids[0], "versendet")
    _backdate(call_db, ids[0], MAIL_FOLLOWUP_DAYS + 4)

    conn = sqlite3.connect(call_db)
    # Die Spalte wieder entfernen — der Zustand einer Datenbank von vor
    # diesem Update, mitsamt ihrer Zeile.
    conn.execute("ALTER TABLE mail_status DROP COLUMN followed_up_at")
    conn.commit()
    conn.close()

    db.init_schema()

    entry = _entry(_board(client), ids[0])

    assert entry["state"] == "nachfassen"
    assert entry["followed_up_at"] is None
    assert "nachgefasst" in entry["actions"]


# ------------------------------
# Suche, Filter, Ausgabe
# ------------------------------


def test_the_filter_counts_the_derived_state_too(zusagen, call_db):
    """Sonst zeigte „keine Antwort" nur die von Hand abgeschlossenen Zeilen."""
    client, ids = zusagen
    _click(client, ids[0], "versendet")
    _backdate(call_db, ids[0], MAIL_TIMEOUT_DAYS + 1)

    board = _board(client, state="keine_antwort")

    assert [entry["contact_id"] for entry in board["entries"]] == [ids[0]]
    assert board["matched"] == 1
    # Die Zahlen über der Liste zählen weiter alles — sie beantworten die
    # Frage „wo stehe ich insgesamt", nicht „was ist gerade gefiltert".
    assert board["total"] == 2
    assert board["counters"]["gesamt"] == 2


def test_the_search_finds_by_business_address_and_number(zusagen):
    client, _ = zusagen

    assert _board(client, q="Dritter")["matched"] == 1
    assert _board(client, q="eins@example.de")["matched"] == 1
    assert _board(client, q="+49 5221 111")["matched"] == 1
    assert _board(client, q="Nirgendwo")["matched"] == 0


def test_a_click_answers_with_the_same_view_it_came_from(zusagen):
    """Sonst spränge die Liste nach jedem Klick auf die erste Seite zurück."""
    client, ids = zusagen

    board = _click(client, ids[0], "versendet", q="Erster")

    assert [entry["betrieb"] for entry in board["entries"]] == ["Erster Betrieb"]
    assert board["matched"] == 1


def test_the_export_names_the_state_and_why_it_is_set(zusagen, call_db):
    client, ids = zusagen
    _click(client, ids[0], "versendet")
    _backdate(call_db, ids[0], MAIL_TIMEOUT_DAYS + 2)

    response = client.get("/mailversand/export")
    assert response.status_code == 200
    text = response.content.decode("utf-8-sig")

    assert 'filename="mailversand_' in response.headers["content-disposition"]
    # Mit BOM, weil diese Datei in Excel geöffnet wird.
    assert response.content.startswith(b"\xef\xbb\xbf")
    assert "keine Antwort" in text
    assert "Nachgefasst am (UTC)" in text
    assert "Erster Betrieb" in text
    assert "Dritter Betrieb" in text


def test_every_state_can_be_reached_from_somewhere(zusagen):
    """Ein Zustand, in den kein Übergang führt, wäre toter Code.

    Billig zu prüfen und genau die Sorte Lücke, die beim Nachtragen eines
    weiteren Zustands entsteht.

    Bis auf `nachfassen`: der wird nie gesetzt, sondern *entsteht* aus dem
    Versanddatum. Ein Knopf dorthin wäre eine Fälligkeit von Hand, und die
    gibt es nicht — dass er trotzdem gebraucht wird, prüfen die Tests der
    kürzeren Frist.
    """
    reachable = {target for targets in MAIL_TRANSITIONS.values() for target in targets}

    assert reachable == set(MailState) - {MailState.NACHFASSEN}
    # Als *Zeile* muss er dagegen dastehen, sonst hätte die fällige Zusage
    # keine Knöpfe.
    assert MailState.NACHFASSEN in MAIL_TRANSITIONS


def test_a_note_can_be_written_without_touching_the_state(zusagen, call_db):
    """Notiert wird, *während* eine Zeile wartet.

    Für „wartet weiter" gibt es keinen Knopf — und die abgelaufene Frist darf
    ein Notizzettel nicht als Entscheidung festschreiben.
    """
    client, ids = zusagen
    _click(client, ids[0], "versendet")
    _backdate(call_db, ids[0], MAIL_TIMEOUT_DAYS + 3)

    response = client.post(
        f"/mailversand/contacts/{ids[0]}",
        json={"note": "zweimal nachgefasst, nichts"},
    )
    assert response.status_code == 200, response.text
    entry = next(e for e in response.json()["entries"] if e["contact_id"] == ids[0])

    assert entry["mail_note"] == "zweimal nachgefasst, nichts"
    # Gespeichert steht dort weiter „versendet", angezeigt „keine Antwort":
    # die Frist bleibt gerechnet, statt durch die Notiz zementiert zu werden.
    assert entry["state"] == "keine_antwort"
    assert entry["automatic"] is True


# ------------------------------
# Nachfassen am Arbeitsplatz
# ------------------------------


def _state(client):
    response = client.get("/telefonakquise/state")
    assert response.status_code == 200, response.text
    return response.json()


def _outcome(client, contact_id, outcome, expected=200, **body):
    response = client.post(
        f"/telefonakquise/contacts/{contact_id}/outcome",
        json={"outcome": outcome, **body},
    )
    assert response.status_code == expected, response.text
    return response.json()


def _due_followup(zusagen, call_db, days=MAIL_FOLLOWUP_DAYS + 1):
    """Eine Zusage, deren Mail seit `days` Tagen unbeantwortet liegt."""
    client, ids = zusagen
    _click(client, ids[0], "versendet")
    _backdate(call_db, ids[0], days)
    return client, ids[0]


def test_a_due_followup_goes_back_to_the_workbench(zusagen, call_db):
    """Der Kern: eine Zusage kommt wieder ins Telefon — als Nachfassen.

    Sie steht auf „zugesagt" und wäre nach der alten Regel nie wieder
    vorgelegt worden. Dass sie es wird, ist der ganze Zweck des Reiters.
    """
    client, contact_id = _due_followup(zusagen, call_db)
    state = _state(client)
    contact = state["contact"]

    assert contact["id"] == contact_id
    # Der Zustand bleibt — sonst verschwände die Zeile aus dem Mailversand.
    assert contact["state"] == "zugesagt"
    # Und der Anrufer sieht, dass es kein Erstanruf ist.
    assert contact["followup"]["due"] is True
    assert contact["followup"]["days_since_sent"] == MAIL_FOLLOWUP_DAYS + 1
    assert contact["followup"]["sent_at"]
    assert state["counters"]["nachfassen"] == 1
    # Die Knöpfe sind die des Nachfassens, nicht die des Erstanrufs.
    assert contact["outcomes"] == [
        "nachgefasst",
        "nachfassen_nicht_erreicht",
        "nachfassen_positiv",
        "nachfassen_abgelehnt",
        "abgelehnt",
    ]


def test_an_initial_call_knows_nothing_of_a_mail(zusagen):
    """Umgekehrt: wo keine Mail heraus ist, ist auch nichts nachzufassen."""
    client, _ = zusagen
    upload = client.post(
        "/telefonakquise/lists",
        files={"file": ("zweite.csv", NEUE_LISTE, "text/csv")},
        data={"name": "Nachschub"},
    )
    assert upload.status_code == 200, upload.text

    contact = _state(client)["contact"]

    assert contact["betrieb"] == "Vierter Betrieb"
    assert contact["followup"] is None
    assert "zugesagt" in contact["outcomes"]
    assert "nachgefasst" not in contact["outcomes"]


def test_the_followup_waits_behind_a_due_callback(zusagen, call_db):
    """Ein zugesagter Rückruf ist eine Verabredung mit einem Menschen.

    Er bleibt Rang 1; das Nachfassen kommt direkt danach — also vor jedem
    Erstanruf.
    """
    client, contact_id = _due_followup(zusagen, call_db)
    client.post(
        "/telefonakquise/lists",
        files={"file": ("zweite.csv", NEUE_LISTE, "text/csv")},
        data={"name": "Nachschub"},
    )

    # Ohne Rückruf steht das Nachfassen vor dem unberührten Erstanruf.
    assert _state(client)["contact"]["id"] == contact_id

    # Denselben Erstanruf auf einen fälligen Rückruf setzen …
    vierter = next(
        entry
        for entry in client.get(
            "/telefonakquise/contacts", params={"q": "Vierter"}
        ).json()["entries"]
    )
    moment = datetime.now(timezone.utc) - timedelta(minutes=5)
    _outcome(
        client,
        vierter["id"],
        "rueckruf",
        appointment_at=moment.isoformat(),
    )

    # … und er zieht am Nachfassen vorbei.
    assert _state(client)["contact"]["id"] == vierter["id"]


def test_a_mail_that_ran_out_of_time_is_not_called_again(zusagen, call_db):
    """Was abgeschrieben ist, gehört nicht an die Spitze der Warteschlange.

    Dieselbe Regel wie im Mailversand: nach der langen Frist steht dort
    „keine Antwort", und dieselbe Rechnung entscheidet hier.
    """
    client, _ = _due_followup(zusagen, call_db, days=MAIL_TIMEOUT_DAYS + 1)

    assert _state(client)["contact"] is None
    assert _state(client)["counters"]["nachfassen"] == 0


def test_the_followup_call_is_recorded_without_losing_the_promise(zusagen, call_db):
    """Der Anruf setzt den Versandstand — und lässt die Zusage stehen."""
    client, contact_id = _due_followup(zusagen, call_db)
    sent_at = _entry(_board(client), contact_id)["sent_at"]

    state = _outcome(client, contact_id, "nachgefasst")

    # Der Kontakt ist aus der Warteschlange und immer noch eine Zusage.
    assert state["contact"] is None
    assert state["counters"]["nachfassen"] == 0
    assert state["counters"]["zugesagt"] == 2

    entry = _entry(_board(client), contact_id)

    assert entry["state"] == "nachgefasst"
    assert entry["followed_up_at"]
    # Das Versanddatum bleibt: die lange Frist läuft weiter ab dem Versand,
    # sonst ließe sie sich durch Anrufe beliebig hinausschieben.
    assert entry["sent_at"] == sent_at

    # Und im Protokoll steht, dass angerufen wurde.
    latest = client.get("/telefonakquise/decisions").json()["entries"][0]

    assert latest["outcome"] == "nachgefasst"
    assert latest["contact_id"] == contact_id


def test_reaching_nobody_defers_the_followup_and_keeps_the_mail_where_it_is(
    zusagen, call_db
):
    """Niemanden erreicht zu haben sagt nichts über die Mail."""
    client, contact_id = _due_followup(zusagen, call_db)

    state = _outcome(
        client, contact_id, "nachfassen_nicht_erreicht", snooze_minutes=120
    )

    assert state["contact"] is None
    assert state["next_due_at"]
    # Aufgeschoben heißt: zählt gerade nicht mit, ist aber nicht erledigt.
    assert state["counters"]["nachfassen"] == 0

    entry = _entry(_board(client), contact_id)

    assert entry["state"] == "nachfassen"
    assert entry["followed_up_at"] is None


def test_confirmed_interest_is_an_answer_even_by_telephone(zusagen, call_db):
    client, contact_id = _due_followup(zusagen, call_db)

    _outcome(client, contact_id, "nachfassen_positiv")
    entry = _entry(_board(client), contact_id)

    assert entry["state"] == "positiv"
    assert entry["answered_at"]


def test_no_interest_ends_the_offer_but_not_the_consent(zusagen, call_db):
    """Der Unterschied, auf dem die ganze Telefonakquise steht."""
    client, contact_id = _due_followup(zusagen, call_db)

    _outcome(client, contact_id, "nachfassen_abgelehnt")
    entry = _entry(_board(client), contact_id)

    assert entry["state"] == "abgelehnt"
    # Die Zusage gilt weiter — die Zeile steht noch in der Versandliste.
    assert entry["contact_id"] == contact_id


def test_a_refusal_on_the_followup_call_ends_the_promise(zusagen, call_db):
    """Der Werbewiderspruch ist in jedem Gespräch eintragbar.

    Er ist das einzige Ergebnis des großen Katalogs, das am Nachfass-Kontakt
    angeboten wird — und das einzige, das die Zusage beendet.
    """
    client, contact_id = _due_followup(zusagen, call_db)

    _outcome(client, contact_id, "abgelehnt")
    board = _board(client)

    assert [entry["contact_id"] for entry in board["entries"]] != [contact_id]
    assert board["total"] == 1


def test_the_two_catalogues_do_not_mix(zusagen, call_db):
    """Die Oberfläche kann keinen Knopf zeigen, den das Schreiben ablehnt.

    Geprüft wird hier die andere Hälfte: dass das Schreiben ihn ablehnt.
    """
    client, contact_id = _due_followup(zusagen, call_db)

    # „Nicht erreichbar" aus dem großen Katalog machte aus der Zusage eine
    # Wiedervorlage — und die Zeile wäre aus dem Mailversand verschwunden.
    body = _outcome(client, contact_id, "nicht_erreichbar", expected=400)
    assert "Erster Betrieb" in body["detail"]

    client.post(
        "/telefonakquise/lists",
        files={"file": ("zweite.csv", NEUE_LISTE, "text/csv")},
        data={"name": "Nachschub"},
    )
    # Solange das Nachfassen fällig ist, steht es vorn — erst abräumen.
    _outcome(client, contact_id, "nachgefasst")
    vierter = _state(client)["contact"]

    # Und andersherum: „Nachgefasst" an einem Betrieb, dem nie jemand
    # geschrieben hat, wäre eine Aussage über eine Mail, die es nicht gibt.
    body = _outcome(client, vierter["id"], "nachgefasst", expected=400)
    assert "Vierter Betrieb" in body["detail"]


def test_a_followup_entry_is_corrected_within_its_own_catalogue(zusagen, call_db):
    """Eine Richtigstellung bewegt auch den Versandstand mit.

    Sie geht durch dieselbe Stelle wie der Anruf (`_write_outcome`) — sonst
    liefen Protokoll und Versandliste auseinander.
    """
    client, contact_id = _due_followup(zusagen, call_db)
    _outcome(client, contact_id, "nachgefasst")

    decision = client.get("/telefonakquise/decisions").json()["entries"][0]

    assert decision["correctable"] is True
    assert "nachfassen_abgelehnt" in decision["outcomes"]
    assert "zugesagt" not in decision["outcomes"]

    fixed = client.post(
        f"/telefonakquise/decisions/{decision['event_id']}/correct",
        json={"outcome": "nachfassen_abgelehnt"},
    )
    assert fixed.status_code == 200, fixed.text

    assert _entry(_board(client), contact_id)["state"] == "abgelehnt"


# ------------------------------
# Von Hand erfasste Betriebe
# ------------------------------


def _create(client, expected=201, **fields):
    """Einen Betrieb von Hand anlegen, wie es das Formular tut."""
    body = {"betrieb": "Dachdecker Wolff", "email": "info@wolff-dach.de"}
    body.update(fields)
    response = client.post("/mailversand/contacts", json=body)
    assert response.status_code == expected, response.text
    return response.json()


def _edit(client, contact_id, expected=200, **fields):
    body = {"betrieb": "Dachdecker Wolff", "email": "info@wolff-dach.de"}
    body.update(fields)
    response = client.patch(f"/mailversand/contacts/{contact_id}", json=body)
    assert response.status_code == expected, response.text
    return response.json()


def _row(board, betrieb):
    return next(e for e in board["entries"] if e["betrieb"] == betrieb)


def test_a_manual_entry_is_a_promise_like_any_other(zusagen):
    """Der Mailversand hat keine eigenen Kontakte — auch hier nicht.

    Was entsteht, ist ein Kontakt der Telefonakquise im Zustand `zugesagt`,
    in einer eigenen Liste, mit einer Protokollzeile als Nachweis.
    """
    client, _ = zusagen
    board = _create(client, telefon="05221 999", ort="Bünde", note="Messe Hannover")
    entry = _row(board, "Dachdecker Wolff")

    assert entry["state"] == "offen"
    assert entry["manual"] is True
    assert entry["list_name"] == "Manuell erfasst"
    assert entry["email"] == "info@wolff-dach.de"
    assert entry["note"] == "Messe Hannover"
    # Der Nachweis: wer wann. Ohne die Protokollzeile stünde hier nichts.
    assert entry["promised_at"]
    assert entry["promised_by"] == "chefin"
    # Und sie ist eine ganz normale Zeile: der Versand-Knopf ist da.
    assert "versendet" in entry["actions"]
    assert board["counters"]["gesamt"] == 3


def test_the_manual_entry_stands_in_the_call_protocol(zusagen):
    """Eine Zusage ist eine Zusage, gleich woher der Betrieb kam."""
    client, _ = zusagen
    _create(client, telefon="05221 999")

    decisions = client.get("/telefonakquise/decisions").json()
    latest = decisions["entries"][0]

    assert latest["betrieb"] == "Dachdecker Wolff"
    assert latest["outcome"] == "zugesagt"
    assert latest["username"] == "chefin"


def test_a_manual_entry_is_never_called_by_the_workbench(zusagen):
    """Sie steht schon auf „zugesagt" — der Arbeitsplatz holt sie nicht.

    Sonst bekäme jemand einen Betrieb vorgelegt, dem er gerade eine Mail
    schreiben wollte.
    """
    client, _ = zusagen
    _create(client, telefon="05221 999")

    state = client.get("/telefonakquise/state").json()

    assert state["contact"] is None
    assert state["counters"]["zugesagt"] == 3


def test_a_number_we_already_work_on_is_refused_and_can_be_forced(zusagen):
    """Dieselbe Prüfung wie beim Import, mit derselben Meldung.

    Und derselbe Rückweg wie beim Löschen einer Liste: erst der Befund, dann
    die ausdrückliche Bestätigung.
    """
    client, _ = zusagen
    body = _create(client, telefon="05221 111", expected=409)

    assert "Handwerker Herford" in body["detail"]

    board = _create(client, telefon="05221 111", force=True)

    assert _row(board, "Dachdecker Wolff")["manual"] is True


def test_the_manual_number_blocks_the_next_import(zusagen, call_db):
    """Sonst holte die nächste Analyse denselben Betrieb in die Anrufliste."""
    client, _ = zusagen
    _create(client, telefon="05224 4711")

    again = ("Betrieb;Telefon\r\n" "Dachdecker Wolff;05224 4711\r\n").encode("utf-8")
    analyse = client.post(
        "/telefonakquise/lists/analyse",
        files={"file": ("zweite.csv", again, "text/csv")},
    )
    assert analyse.status_code == 200, analyse.text
    result = analyse.json()

    assert result["contacts"] == 0
    # Solange die Sammelliste aktiv ist, nennt die Meldung sie: das ist der
    # Ort, an dem der Betrieb gerade bearbeitet wird.
    assert "Manuell erfasst" in result["duplicates"][0]["reason"]

    # Und danach greift die Sperre. Sie ist der Grund, dass Archivieren die
    # Nummern gesperrt hält — mit der Herkunft in der Meldung, denn „schon
    # einmal importiert" wäre für eine Nummer, die nie in einer Datei stand,
    # schlicht falsch.
    lists = client.get("/telefonakquise/state").json()["lists"]
    manual = next(entry for entry in lists if entry["name"] == "Manuell erfasst")
    archived = client.patch(
        f"/telefonakquise/lists/{manual['id']}", json={"archived": True}
    )
    assert archived.status_code == 200, archived.text

    result = client.post(
        "/telefonakquise/lists/analyse",
        files={"file": ("dritte.csv", again, "text/csv")},
    ).json()

    assert result["contacts"] == 0
    assert "von Hand erfasst" in result["duplicates"][0]["reason"]


def test_only_a_manual_row_can_be_edited_here(zusagen):
    """Was aus einer Anrufliste kam, gehört der Telefonakquise.

    Zwei Oberflächen auf denselben Kontakt wären zwei Wahrheiten — die Zeile
    drüben trägt Zustand, Wiedervorlage und Anrufzähler.
    """
    client, ids = zusagen
    body = _edit(client, ids[0], expected=400)

    assert "Handwerker Herford" in body["detail"]


def test_a_corrected_address_appends_to_the_record(zusagen):
    """Die Zusage gilt ab jetzt für eine andere Adresse — das muss dastehen.

    Angehängt statt überschrieben: dasselbe Verfahren wie die
    Richtigstellung im Anrufprotokoll, weil `events` kein UPDATE kennt.
    """
    client, _ = zusagen
    created = _create(client, telefon="05221 999")
    contact_id = _row(created, "Dachdecker Wolff")["contact_id"]

    board = _edit(client, contact_id, email="buero@wolff-dach.de", telefon="05221 999")
    entry = _row(board, "Dachdecker Wolff")

    assert entry["email"] == "buero@wolff-dach.de"

    decisions = client.get("/telefonakquise/decisions").json()["entries"]

    assert decisions[0]["email"] == "buero@wolff-dach.de"
    assert decisions[0]["corrects_event_id"] is not None
    # Die alte Zeile bleibt lesbar — das ist der Unterschied zwischen
    # „berichtigt" und „nie passiert".
    assert decisions[1]["email"] == "info@wolff-dach.de"


def test_a_typo_in_the_name_is_no_correction(zusagen):
    """Ein anders geschriebener Betrieb ist derselbe Betrieb.

    Das Protokoll hält fest, für welche *Adresse* die Zusage gilt; einen
    Namen zu berichtigen ist keine neue Einwilligung.
    """
    client, _ = zusagen
    created = _create(client, betrieb="Dachdecker Wolf", telefon="05221 999")
    contact_id = _row(created, "Dachdecker Wolf")["contact_id"]

    before = len(client.get("/telefonakquise/decisions").json()["entries"])
    board = _edit(client, contact_id, betrieb="Dachdecker Wolff", telefon="05221 999")

    assert _row(board, "Dachdecker Wolff")["contact_id"] == contact_id
    assert len(client.get("/telefonakquise/decisions").json()["entries"]) == before


def test_a_corrected_number_releases_the_wrong_one(zusagen):
    """Sonst sperrte ein Zahlendreher für immer eine fremde Nummer."""
    client, _ = zusagen
    created = _create(client, telefon="05221 99")
    contact_id = _row(created, "Dachdecker Wolff")["contact_id"]

    _edit(client, contact_id, telefon="05221 999")

    blocked = {
        entry["telefon_key"]
        for entry in client.get("/telefonakquise/blacklist").json()["entries"]
    }

    assert "0522199" not in blocked
    assert "05221999" in blocked


def test_an_entry_without_a_business_or_an_address_is_refused(zusagen):
    """Beide sind Pflicht — und Leerzeichen sind keine Eingabe."""
    client, _ = zusagen

    _create(client, betrieb="   ", expected=400)
    _create(client, email="   ", expected=400)
    _create(client, email="keine-adresse", expected=400)
    # Ganz fehlend faengt Pydantic ab, bevor der Service es sieht.
    assert (
        client.post("/mailversand/contacts", json={"betrieb": "X"}).status_code == 422
    )


def test_the_manual_list_is_created_once_and_then_reused(zusagen):
    client, _ = zusagen
    _create(client, telefon="05221 999")
    _create(client, betrieb="Fliesen Kamp", email="kamp@example.de")

    lists = client.get("/telefonakquise/state").json()["lists"]
    manual = [entry for entry in lists if entry["name"] == "Manuell erfasst"]

    assert len(manual) == 1
    assert manual[0]["counters"]["gesamt"] == 2
    assert manual[0]["counters"]["zugesagt"] == 2


# ------------------------------
# Die Bau-Einschätzung
# ------------------------------


def test_a_promise_starts_without_an_assessment(zusagen):
    """Der Ausgangswert braucht keinen Eintrag — wie „noch nicht versendet".

    Eine Zusage, deren Website niemand angesehen hat, steht auf
    `unbewertet`; das ist kein fehlender Wert, sondern eine Auskunft.
    """
    client, ids = zusagen

    board = _board(client)

    assert _entry(board, ids[0])["readiness"] == "unbewertet"
    assert _entry(board, ids[0])["readiness_label"] == "noch nicht eingeschätzt"
    assert board["counters"]["unbewertet"] == 2
    assert board["counters"]["ready_to_build"] == 0
    assert board["counters"]["in_development"] == 0
    assert board["counters"]["ready_to_mail"] == 0
    assert board["counters"]["missing_content"] == 0
    # Die Marker fahren als Daten mit, wie die Knöpfe.
    assert [option["id"] for option in board["readiness_options"]] == [
        option.id.value for option in READINESS_OPTIONS
    ]


def test_a_marker_is_set_without_touching_the_state(zusagen):
    """Die Einschätzung ist keine Stufe im Versand.

    Sie ist eine Beobachtung über eine Website und darf den Versandstand
    nicht anfassen — auch nicht das Versanddatum, an dem die Frist hängt.
    """
    client, ids = zusagen

    board = _mark(client, ids[0], "ready_to_build")
    entry = _entry(board, ids[0])

    assert entry["readiness"] == "ready_to_build"
    assert entry["readiness_label"] == "Ready to Build"
    assert entry["state"] == "offen"
    assert entry["sent_at"] is None
    assert board["counters"]["ready_to_build"] == 1
    assert board["counters"]["unbewertet"] == 1


def test_the_markers_replace_each_other(zusagen):
    """Entweder die alte Seite hat Inhalt, oder sie hat keinen.

    Unabhängige Häkchen wären ein Zustand, den niemand lesen kann („Ready to
    Build *und* Missing Content"), deshalb ist es ein Wert.
    """
    client, ids = zusagen
    _mark(client, ids[0], "ready_to_build")

    board = _mark(client, ids[0], "missing_content")

    assert _entry(board, ids[0])["readiness"] == "missing_content"
    assert board["counters"]["ready_to_build"] == 0
    assert board["counters"]["missing_content"] == 1


def test_the_build_runs_through_the_marker_track(zusagen):
    """Der Bau selbst ist ein Wert dieser Spur, kein zweites Häkchen.

    „lässt sich bauen" → „wird gebaut" → „ist gebaut" schließen einander
    aus: wer angefangen hat, braucht die Einschätzung von vorher nicht mehr.
    Der Versandstand bleibt bei jedem Schritt, wo er ist — gebaut wird,
    bevor die Mail heraus ist.
    """
    client, ids = zusagen
    _mark(client, ids[0], "ready_to_build")

    board = _mark(client, ids[0], "in_development")
    entry = _entry(board, ids[0])

    assert entry["readiness"] == "in_development"
    assert entry["readiness_label"] == "In Development"
    assert entry["state"] == "offen"
    assert board["counters"]["in_development"] == 1
    assert board["counters"]["ready_to_build"] == 0

    board = _mark(client, ids[0], "ready_to_mail")

    assert _entry(board, ids[0])["readiness"] == "ready_to_mail"
    assert board["counters"]["in_development"] == 0
    assert _board(client, readiness="in_development")["matched"] == 0


def test_a_built_website_is_a_marker_and_not_a_mail_state(zusagen):
    """„Ready to Mail": die Seite ist gebaut, die Mail ist damit nicht heraus.

    Der Marker gehört in die Bau-Spur und nicht in den Versandstand — sonst
    stünde in der Zeile, es sei etwas verschickt worden, was noch beim uns
    liegt. Und er ersetzt „Ready to Build": wer gebaut hat, braucht die
    Einschätzung von vorher nicht mehr.
    """
    client, ids = zusagen
    _mark(client, ids[0], "ready_to_build")

    board = _mark(client, ids[0], "ready_to_mail")
    entry = _entry(board, ids[0])

    assert entry["readiness"] == "ready_to_mail"
    assert entry["readiness_label"] == "Ready to Mail"
    # Der Versandstand ist unberührt: die Mail ist weiterhin nicht heraus.
    assert entry["state"] == "offen"
    assert entry["sent_at"] is None
    assert board["counters"]["ready_to_mail"] == 1
    assert board["counters"]["ready_to_build"] == 0

    # Und er tritt mit dem Versand ab: „gebaut, muss noch zum Betrieb" neben
    # einem „verschickt" wäre eine Zeile, die sich selbst widerspricht.
    board = _click(client, ids[0], "versendet")
    assert _entry(board, ids[0])["readiness"] == "unbewertet"
    assert _board(client, readiness="ready_to_mail")["matched"] == 0


def test_a_marker_can_be_removed_again(zusagen):
    """Der Fehlklick gehört zum Werkzeug — auch hier.

    Entfernt wird durch `unbewertet` und nicht durch ein weggelassenes Feld:
    „nicht mitgeschickt" heißt überall in diesem Anfragekörper
    „unverändert".
    """
    client, ids = zusagen
    _mark(client, ids[0], "missing_content")

    board = _mark(client, ids[0], "unbewertet")

    assert _entry(board, ids[0])["readiness"] == "unbewertet"
    assert board["counters"]["missing_content"] == 0
    assert board["counters"]["unbewertet"] == 2


def test_the_assessment_steps_back_once_the_mail_is_out(zusagen):
    """„Ready to Mail" und „verschickt" schließen sich aus.

    Die Bau-Einschätzung beschreibt den Weg *bis* zur Mail: von „lässt sich
    bauen" über „wird gebaut" bis „ist gebaut, muss noch zum Betrieb". Ist
    die Mail heraus, ist dieser Weg zu Ende — und „muss noch zum Betrieb"
    neben einem „verschickt" ist keine Auskunft, sondern ein Widerspruch.

    Deshalb tritt die ganze Reihe ab, und zwar auch aus „nicht
    eingeschätzt": eine verschickte Zusage ist nicht unangesehen, sie ist
    fertig. Wiedergefunden wird sie über den Reiter, der dieselbe Frage
    besser beantwortet.
    """
    client, ids = zusagen
    _mark(client, ids[0], "ready_to_mail")

    board = _click(client, ids[0], "versendet")
    entry = _entry(board, ids[0])

    assert entry["state"] == "versendet"
    assert entry["readiness"] == "unbewertet"
    # Keine Marke zählt sie mehr — die eigene nicht und „nicht eingeschätzt"
    # auch nicht.
    assert board["counters"]["ready_to_mail"] == 0
    assert board["counters"]["unbewertet"] == 1
    # Und kein Filter findet sie mehr über die Bau-Spur.
    assert _board(client, readiness="ready_to_mail")["matched"] == 0
    assert _board(client, readiness="unbewertet")["matched"] == 1

    # Die Zeile bietet die Marker-Knöpfe nicht mehr an — dieselbe Regel wie
    # bei den Zustandsknöpfen: die Oberfläche zeigt, was das Backend ihr
    # mitgibt.
    assert entry["readiness_actions"] == []
    assert _entry(board, ids[1])["readiness_actions"] == [
        "ready_to_build",
        "in_development",
        "ready_to_mail",
        "missing_content",
    ]


def test_a_marker_is_refused_once_the_mail_is_out(zusagen):
    """Was die Oberfläche nicht anbietet, nimmt das Backend auch nicht an.

    Dasselbe Muster wie bei den Zustandsübergängen: die Regel steht an einer
    Stelle, und ein still weggeschriebener Marker wäre einer, den niemand
    mehr zu sehen bekommt.
    """
    client, ids = zusagen
    _click(client, ids[0], "versendet")

    body = _mark(client, ids[0], "ready_to_build", expected=400)

    # Die Meldung nennt den Zustand, in dem die Zeile steht, statt „die Mail
    # ist heraus" zu behaupten: seit „kein Bedarf" endet die Bau-Spur auch an
    # Zeilen, an die nie eine Mail ging.
    assert "Mail versendet" in body["detail"]
    assert "noch nicht versendet" in body["detail"]


def test_a_send_click_hides_the_marker_but_keeps_it(zusagen):
    """Verschwunden ist nicht dasselbe wie gelöscht.

    Mit dem Versand tritt die Einschätzung ab — gespeichert bleibt sie
    trotzdem, denn der Versand ist zurücknehmbar, und dann ist die Website
    wieder genau da, wo sie vorher war. Das ist derselbe Bau, nicht ein
    zweiter: eine Zeile, die nach dem Zurücksetzen auf „nicht eingeschätzt"
    stünde, ließe jemanden die Arbeit noch einmal machen.

    Beide Größen liegen in derselben Zeile, und geschrieben wird sie immer
    ganz — das „unverändert" muss der Service über den *gespeicherten* Wert
    auflösen, nicht über den angezeigten.
    """
    client, ids = zusagen
    _mark(client, ids[0], "ready_to_build")

    board = _click(client, ids[0], "versendet")
    assert _entry(board, ids[0])["readiness"] == "unbewertet"

    board = _click(client, ids[0], "positiv")
    assert _entry(board, ids[0])["readiness"] == "unbewertet"

    # Und zurück: das Zurücksetzen des Versands ist keine Aussage über die
    # Website — die Einschätzung von vorher steht wieder da.
    board = _click(client, ids[0], "offen")
    assert _entry(board, ids[0])["readiness"] == "ready_to_build"


def test_a_note_keeps_the_marker_and_a_marker_keeps_the_note(zusagen):
    """Drei Felder, drei unabhängige Wege in dieselbe Zeile."""
    client, ids = zusagen
    response = client.post(
        f"/mailversand/contacts/{ids[0]}",
        json={"note": "Seite hat drei Sätze", "readiness": "missing_content"},
    )
    assert response.status_code == 200, response.text

    board = _mark(client, ids[0], "ready_to_build")
    entry = _entry(board, ids[0])

    assert entry["mail_note"] == "Seite hat drei Sätze"
    assert entry["readiness"] == "ready_to_build"

    board = client.post(
        f"/mailversand/contacts/{ids[0]}", json={"note": "doch genug Inhalt"}
    ).json()

    assert _entry(board, ids[0])["readiness"] == "ready_to_build"
    assert _entry(board, ids[0])["mail_note"] == "doch genug Inhalt"


def test_a_note_on_a_sent_row_does_not_erase_the_marker(zusagen, call_db):
    """Dieselbe Falle wie beim Zustand, eine Spalte weiter.

    Geschrieben wird immer die ganze Zeile, und „unverändert" muss der
    Service auflösen — über den *gespeicherten* Wert. Über den angezeigten
    wäre die Einschätzung nach dem ersten Notizzettel an einer verschickten
    Zeile weg, und das fiele erst auf, wenn jemand den Versand zurücknimmt.
    """
    client, ids = zusagen
    _mark(client, ids[0], "in_development")
    _click(client, ids[0], "versendet")
    _backdate(call_db, ids[0], MAIL_TIMEOUT_DAYS + 4)

    board = client.post(
        f"/mailversand/contacts/{ids[0]}",
        json={"note": "zweimal nachgefasst"},
    ).json()
    entry = _entry(board, ids[0])

    assert entry["state"] == "keine_antwort"
    assert entry["automatic"] is True
    assert entry["readiness"] == "unbewertet"

    # Der Beweis, dass sie nur nicht gezeigt wird: sie steht wieder da.
    board = _click(client, ids[0], "offen")
    assert _entry(board, ids[0])["readiness"] == "in_development"


def test_a_marker_needs_no_email_address(zusagen):
    """Ob eine Website Inhalt hat, ist von der Adresse unabhängig.

    Die Zusage ohne Adresse ist Nacharbeit — und ausgerechnet die will man
    einschätzen können, bevor man ihr nachtelefoniert.
    """
    client, _ = zusagen
    without = next(
        e for e in _board(client)["entries"] if e["betrieb"] == "Dritter Betrieb"
    )

    board = _mark(client, without["contact_id"], "missing_content")

    assert _entry(board, without["contact_id"])["readiness"] == "missing_content"


def test_the_marker_filter_is_independent_of_the_state_filter(zusagen):
    """Zwei Filter, zwei Fragen — und zusammen die dritte.

    „Offen und Ready to Build" ist die Liste, mit der jemand anfängt zu
    bauen; sie entsteht nur, wenn beide Filter gleichzeitig gelten. Dass die
    Marker ohnehin nur an offenen Zusagen stehen, macht den zweiten Filter
    nicht überflüssig: er teilt die offenen auf.
    """
    client, ids = zusagen
    _mark(client, ids[0], "missing_content")
    _mark(client, ids[1], "ready_to_build")

    both = _board(client, state="offen", readiness="ready_to_build")
    assert [e["contact_id"] for e in both["entries"]] == [ids[1]]
    assert both["matched"] == 1

    marker_only = _board(client, readiness="missing_content")
    assert marker_only["matched"] == 1

    # Verschickt *und* eingeschätzt gibt es nicht mehr: die Einschätzung ist
    # der Weg bis zur Mail.
    assert _board(client, state="versendet", readiness="ready_to_build")["matched"] == 0
    assert _board(client, readiness="unbewertet")["matched"] == 0

    # `total` zählt weiter jede Zusage: es ist die Auskunft „gibt es hier
    # überhaupt etwas", an der die leere Liste hängt.
    assert both["total"] == 2
    # Die Zähler dagegen kennen die Auswahl — jede Reihe die der *anderen*:
    # die Reiter zählen innerhalb des Markers (einer ist Ready to Build), die
    # Marker innerhalb des Reiters (beide stehen offen).
    assert both["counters"]["gesamt"] == 1
    assert both["counters"]["ready_to_build"] == 1
    assert both["counters"]["missing_content"] == 1


def test_each_counter_row_counts_within_the_other_filter(zusagen):
    """Zwei Filterreihen, und jede zählt in der Auswahl der anderen.

    Vorher zählten die Marker immer über alle Zusagen: wer oben auf „Offen"
    filterte, sah darunter Zahlen einer anderen Menge als die Liste — die
    Auskunft „12 Ready to Build" über einer Liste mit drei Zeilen. Die
    Marken müssen den Reiter ergeben, auf dem sie stehen, sonst beantworten
    sie eine Frage, die niemand gestellt hat.

    Der *eigene* Filter bleibt draußen, und das ist die zweite Hälfte der
    Regel: nullte er die übrigen Marken, gäbe es keinen Rückweg, der eine
    Zahl nennt.

    Seit die Einschätzung mit dem Versand abtritt, geht die Summe nur noch
    auf dem Reiter „Offen" auf — auf „Alle" fehlen darin die verschickten
    Zusagen, weil sie keine Marke mehr tragen. Das ist die Aussage und nicht
    ihr Verlust: dort beantwortet der Reiter dieselbe Frage.
    """
    client, ids = zusagen
    # „Erster" ist Ready to Build und verschickt — die Marke tritt damit ab.
    # „Dritter" (ohne Adresse) steht offen und ist Missing Content.
    _mark(client, ids[0], "ready_to_build")
    _click(client, ids[0], "versendet")
    _mark(client, ids[1], "missing_content")

    offen = _board(client, state="offen")["counters"]
    assert offen["offen"] == 1
    assert (offen["ready_to_build"], offen["missing_content"]) == (0, 1)
    assert (offen["in_development"], offen["ready_to_mail"]) == (0, 0)
    assert offen["unbewertet"] == 0
    # Die Summe der Marken ist die Zahl auf dem Reiter — genau das war vorher
    # nicht so.
    assert (
        offen["ready_to_build"]
        + offen["in_development"]
        + offen["ready_to_mail"]
        + offen["missing_content"]
        + offen["unbewertet"]
        == offen["offen"]
    )

    # Auf „Alle" sind es zwei Zusagen, aber nur eine Marke: die verschickte
    # trägt keine mehr, auch keine „nicht eingeschätzt".
    alle = _board(client)["counters"]
    assert alle["gesamt"] == 2
    assert (alle["missing_content"], alle["unbewertet"]) == (1, 0)
    assert alle["ready_to_build"] == 0

    fehlend = _board(client, readiness="missing_content")["counters"]
    assert fehlend["gesamt"] == 1
    assert (fehlend["offen"], fehlend["versendet"]) == (1, 0)
    # Auch die Nacharbeit zählt in der Auswahl: die Zusage ohne Adresse ist
    # genau die, die hier in der Liste steht.
    assert fehlend["ohne_email"] == 1
    # Der eigene Filter der Markerreihe bleibt draußen.
    assert (fehlend["ready_to_build"], fehlend["unbewertet"]) == (0, 0)
    assert (fehlend["in_development"], fehlend["ready_to_mail"]) == (0, 0)


def test_the_marker_filter_combines_with_the_search(zusagen):
    """Drei Bedingungen in einem WHERE, mit drei Parametern in einer Reihe.

    Die Reihenfolge der Platzhalter ist die einzige Stelle, an der ein
    zweiter Filter etwas kaputt machen kann — ein falsch eingefädelter
    Stichtag liefert kein Fehlerbild, sondern leise falsche Treffer.
    """
    client, ids = zusagen
    _mark(client, ids[0], "ready_to_build")

    assert _board(client, q="Erster", readiness="ready_to_build")["matched"] == 1
    assert _board(client, q="Dritter", readiness="ready_to_build")["matched"] == 0

    hit = _board(client, q="+49 5221 111", state="offen", readiness="ready_to_build")
    assert [e["contact_id"] for e in hit["entries"]] == [ids[0]]


def test_an_unknown_marker_is_refused(zusagen):
    """Ein Wert, den das Enum nicht kennt, kommt nicht in die Datenbank."""
    client, ids = zusagen

    response = client.post(
        f"/mailversand/contacts/{ids[0]}", json={"readiness": "vielleicht"}
    )

    assert response.status_code == 422


def test_a_marked_row_answers_with_the_view_it_came_from(zusagen):
    """Wie beim Zustand: sonst spränge die Liste auf die erste Seite zurück."""
    client, ids = zusagen

    board = _mark(client, ids[0], "ready_to_build", q="Erster")

    assert [entry["betrieb"] for entry in board["entries"]] == ["Erster Betrieb"]
    assert board["matched"] == 1


def test_the_export_names_the_assessment(zusagen):
    """Und lässt die Zelle leer, solange keine gemacht wurde."""
    client, ids = zusagen
    _mark(client, ids[0], "missing_content")

    response = client.get("/mailversand/export")
    assert response.status_code == 200
    lines = response.content.decode("utf-8-sig").splitlines()

    assert "Bau-Einschätzung" in lines[0].split(";")
    column = lines[0].split(";").index("Bau-Einschätzung")
    marked = next(line for line in lines if line.startswith("Erster Betrieb"))
    unmarked = next(line for line in lines if line.startswith("Dritter Betrieb"))

    assert marked.split(";")[column] == "Missing Content"
    assert unmarked.split(";")[column] == ""


def test_every_marker_can_be_set_and_unset(zusagen):
    """Keine Übergangstabelle heißt: jeder Wert ist von jedem aus erreichbar.

    Billig zu prüfen, und es hält die Begründung fest — die Einschätzung ist
    kein Vorgang mit Reihenfolge, sondern eine Beobachtung.
    """
    client, ids = zusagen

    for value in BuildReadiness:
        for target in BuildReadiness:
            _mark(client, ids[0], value.value)
            board = _mark(client, ids[0], target.value)
            assert _entry(board, ids[0])["readiness"] == target.value


# ------------------------------
# „Bigger than expected" — die dritte, kombinierbare Größe
# ------------------------------


def test_the_scope_marker_stands_next_to_every_other_marker(zusagen):
    """Der Umfang ist *neben* der Bau-Spur, nicht in ihr.

    Das ist der ganze Grund für die eigene Spalte: eine Seite kann „In
    Development" **und** größer als ein Onepager sein, und der Umfang soll
    über jeden Bauschritt stehen bleiben. Als sechster Wert von
    `BuildReadiness` wäre er beim nächsten Klick weg — und das ist die
    Auskunft, die beim Planen gebraucht wird.
    """
    client, ids = zusagen

    board = _scope(client, ids[0], True)
    entry = _entry(board, ids[0])

    assert entry["oversized"] is True
    # Weder Versandstand noch Bau-Einschätzung sind angefasst.
    assert entry["state"] == "offen"
    assert entry["readiness"] == "unbewertet"
    assert board["counters"]["oversized"] == 1

    # Und beides gleichzeitig, in beiden Reihenfolgen gesetzt.
    board = _mark(client, ids[0], "in_development")
    entry = _entry(board, ids[0])
    assert (entry["readiness"], entry["oversized"]) == ("in_development", True)

    board = _mark(client, ids[0], "ready_to_mail")
    assert _entry(board, ids[0])["oversized"] is True

    # Und er bleibt, wo die Bau-Einschätzung mit dem Versand abtritt: der
    # Umfang ist eine Aussage über die Seite, nicht über den Weg zur Mail.
    board = _click(client, ids[0], "versendet")
    assert _entry(board, ids[0])["oversized"] is True
    assert _entry(board, ids[0])["readiness"] == "unbewertet"

    board = client.post(
        f"/mailversand/contacts/{ids[0]}", json={"note": "drei Unterseiten"}
    ).json()
    assert _entry(board, ids[0])["oversized"] is True
    assert _board(client, oversized=True)["matched"] == 1


def test_the_scope_marker_can_be_taken_back(zusagen):
    """`False` ist der Rückweg, und hier braucht es dafür keinen dritten Wert.

    Bei zwei Werten ist das Feld selbst der Rückweg — anders als bei der
    Bau-Einschätzung, wo `unbewertet` ein eigener Wert sein muss. Ein
    fehlendes Feld heißt weiter „unverändert".
    """
    client, ids = zusagen
    _scope(client, ids[0], True)

    board = _scope(client, ids[0], False)

    assert _entry(board, ids[0])["oversized"] is False
    assert board["counters"]["oversized"] == 0


def test_the_scope_filter_is_independent_of_the_other_two(zusagen):
    """Drei Filter, drei Fragen — und zusammen die vierte."""
    client, ids = zusagen
    _scope(client, ids[0], True)
    _mark(client, ids[0], "in_development")
    _scope(client, ids[1], True)

    big = _board(client, oversized=True)
    assert big["matched"] == 2

    assert _board(client, oversized=False)["matched"] == 0

    all_three = _board(
        client, state="offen", readiness="in_development", oversized=True
    )
    assert [e["contact_id"] for e in all_three["entries"]] == [ids[0]]

    # Die Suche fädelt sich zwischen die drei ein, ohne sie zu verschieben.
    assert _board(client, q="Erster", oversized=True)["matched"] == 1
    assert _board(client, q="Erster", oversized=False)["matched"] == 0


def test_the_scope_counter_counts_within_the_other_filters(zusagen):
    """Dritte Größe, dieselbe Regel: mit den anderen, ohne sich selbst.

    Ohne den eigenen Filter, weil die eine Marke sonst entweder die
    Gesamtzahl oder die Zahl der Liste nennt — ein Rückweg ist keins von
    beidem.
    """
    client, ids = zusagen
    _scope(client, ids[0], True)
    _click(client, ids[0], "versendet")
    _scope(client, ids[1], True)

    versendet = _board(client, state="versendet")["counters"]
    assert versendet["oversized"] == 1

    offen = _board(client, state="offen")["counters"]
    assert offen["oversized"] == 1

    # Mit dem eigenen Filter bleibt die Zahl stehen: sie zählt sich nicht
    # selbst weg.
    assert _board(client, oversized=True)["counters"]["oversized"] == 2
    # … und die anderen Reihen zählen jetzt in *seiner* Auswahl.
    assert _board(client, oversized=True)["counters"]["gesamt"] == 2
    assert _board(client, oversized=False)["counters"]["gesamt"] == 0


def test_the_export_names_the_scope(zusagen):
    """Und lässt die Zelle leer, solange nichts gesagt wurde."""
    client, ids = zusagen
    _scope(client, ids[0], True)

    response = client.get("/mailversand/export")
    assert response.status_code == 200
    lines = response.content.decode("utf-8-sig").splitlines()

    column = lines[0].split(";").index("Umfang")
    marked = next(line for line in lines if line.startswith("Erster Betrieb"))
    unmarked = next(line for line in lines if line.startswith("Dritter Betrieb"))

    assert marked.split(";")[column] == "Bigger than expected"
    assert unmarked.split(";")[column] == ""


def test_a_database_from_before_the_assessment_gets_the_new_column(zusagen):
    """`CREATE TABLE IF NOT EXISTS` fasst eine vorhandene Tabelle nicht an.

    `calls.db` liegt in Produktion auf einem Volume und überlebt jeden Build.
    Ohne das Nachziehen der Spalte liefe dort *jede* Abfrage der Versandliste
    auf einen Fehler — die Einschätzung steht in der Spaltenliste von allen.
    """
    client, ids = zusagen

    with db.connect() as conn:
        # Die Tabelle von vor der Spalte, mitsamt Fremdschlüssel: dass ein
        # `ADD COLUMN` mit eingeschalteten Fremdschlüsseln durchgeht, gilt in
        # SQLite nur für NULL-vorbelegte Spalten — genau die Bedingung, unter
        # der `_ADDED_COLUMNS` steht.
        conn.executescript(
            "DROP TABLE mail_status;"
            "CREATE TABLE mail_status ("
            "  contact_id TEXT PRIMARY KEY REFERENCES contacts (id)"
            "    ON DELETE CASCADE,"
            "  state TEXT NOT NULL DEFAULT 'offen',"
            "  sent_at TEXT,"
            "  answered_at TEXT,"
            "  note TEXT NOT NULL DEFAULT '',"
            "  updated_at TEXT NOT NULL,"
            "  updated_by TEXT NOT NULL DEFAULT ''"
            ");"
        )
        conn.execute(
            "INSERT INTO mail_status (contact_id, state, note, updated_at)"
            " VALUES (?, 'versendet', 'alter Eintrag', '2026-01-01T09:00:00Z')",
            (ids[0],),
        )

    db.init_schema()

    with db.connect() as conn:
        columns = {
            row["name"] for row in conn.execute("PRAGMA table_info(mail_status)")
        }
        stored = conn.execute("SELECT * FROM mail_status").fetchone()

    assert {"build_readiness", "oversized"} <= columns
    # Der alte Stand bleibt: NULL heißt „noch nicht eingeschätzt" bzw. „hat
    # niemand gesagt", und genau das ist die Wahrheit über eine Zeile von vor
    # den Spalten.
    assert stored["note"] == "alter Eintrag"
    assert stored["build_readiness"] is None
    assert stored["oversized"] is None

    # Und die Liste antwortet weiter — das ist der Punkt der Übung.
    entry = _entry(_board(client), ids[0])
    assert entry["state"] == "versendet"
    assert entry["readiness"] == "unbewertet"
    assert entry["oversized"] is False
    # Nur die offene Zusage steht auf „nicht eingeschätzt": die verschickte
    # trägt gar keine Marke mehr.
    assert _board(client)["counters"]["unbewertet"] == 1
    assert _board(client)["counters"]["oversized"] == 0


def test_a_row_carries_the_whole_contact_of_the_call_list(client, call_db):
    """Die Zeile bringt mit, was in der Anrufliste stand — auch die freien
    Spalten.

    Die Liste zeigt davon nichts; gebraucht wird es zum Kopieren einer Zeile
    („alles über diesen Betrieb als Text"). Die Zusatzspalten sind der
    eigentliche Grund: was in ihnen steht, entscheidet die Analyse, aus der
    die Anrufliste kam, und genau darüber wird hinterher geschrieben.
    """
    csv = (
        "Betrieb;Telefon;Prio;Befunde;Ladezeit;CMS\r\n"
        "Zaunbau Müller;05221 111;A;Seite lädt langsam;4,2 s;WordPress 5.2\r\n"
    ).encode("utf-8")
    upload = client.post(
        "/telefonakquise/lists",
        files={"file": ("analyse.csv", csv, "text/csv")},
        data={"name": "Analyse Herford"},
    )
    assert upload.status_code == 200, upload.text

    contact = client.get("/telefonakquise/state").json()["contact"]
    assert (
        client.post(
            f"/telefonakquise/contacts/{contact['id']}/outcome",
            json={"outcome": "zugesagt"},
        ).status_code
        == 200
    )

    entry = _board(client)["entries"][0]

    assert entry["prio"] == "A"
    assert entry["befunde"] == "Seite lädt langsam"
    # In der Reihenfolge der Datei, wortwörtlich — dieselbe Zusage wie drüben
    # beim Kontakt.
    assert entry["extras"] == [
        {"label": "Ladezeit", "value": "4,2 s"},
        {"label": "CMS", "value": "WordPress 5.2"},
    ]


# ------------------------------
# Kein Bedarf — der Ausgang aus der Arbeitsliste
# ------------------------------
#
# Die Zusage, aus der nichts wird: die bestehende Website ist schon gut, der
# Betrieb ist längst Kunde. Bis hierher gab es dafür keinen Knopf — aus
# `offen` führte allein „versendet" heraus, und so blieb die Zeile für immer
# in der Liste stehen, die abgearbeitet werden soll.
#
# Was dabei *nicht* passiert, ist genauso wichtig wie was passiert: der
# Kontakt bleibt auf `zugesagt` und damit bleibt der Nachweis der Einwilligung
# bestehen. Verschoben wird der Versandstand, nicht die Zusage.


def _blacklist(client, query=""):
    response = client.get("/telefonakquise/blacklist", params={"q": query})
    assert response.status_code == 200, response.text
    return response.json()


def test_no_interest_takes_the_promise_out_of_the_open_list(zusagen):
    """Der Fall, für den es den Zustand gibt: angesehen, erübrigt sich.

    „Offen" ist die Zahl, die auf null laufen soll. Eine Zusage, die niemand
    mehr anschreiben will, gehört nicht hinein — und bis hierher gab es
    keinen Weg, sie dort herauszubekommen, ohne eine Mail zu behaupten.
    """
    client, ids = zusagen
    assert _board(client)["counters"]["offen"] == 2

    board = _click(client, ids[0], "kein_bedarf")

    assert _entry(board, ids[0])["state"] == "kein_bedarf"
    # Angeklickt, nicht abgelaufen: der Hinweis „automatisch" gehört den
    # beiden Fristen.
    assert _entry(board, ids[0])["automatic"] is False
    assert board["counters"]["offen"] == 1
    assert board["counters"]["kein_bedarf"] == 1
    # Aus der Liste ist sie nicht verschwunden, nur aus „Offen": die Zusage
    # gilt weiter, und was aus ihr wurde, bleibt nachlesbar.
    assert board["counters"]["gesamt"] == 2
    assert [
        e["contact_id"] for e in _board(client, state="kein_bedarf")["entries"]
    ] == [ids[0]]
    assert [e["contact_id"] for e in _board(client, state="offen")["entries"]] == [
        ids[1]
    ]


def test_no_interest_is_our_judgement_and_not_a_refusal(zusagen):
    """`kein_bedarf` ist nicht `abgelehnt` — dieselbe Trennung wie am Telefon.

    „Abgelehnt" ist ein Widerspruch des Betriebs, „kein Bedarf" ein Urteil
    von uns. Beides in einen Topf zu werfen hieße, aus der Liste einen
    Widerspruch herauszulesen, in der keiner steht.
    """
    client, ids = zusagen
    board = _click(client, ids[0], "kein_bedarf")

    assert board["counters"]["abgelehnt"] == 0
    assert board["counters"]["kein_bedarf"] == 1
    # Und die Einwilligung bleibt, wo sie war: der Kontakt steht weiter auf
    # „Zusage", das Protokoll ist unberührt.
    entry = _entry(board, ids[0])
    assert entry["promised_at"] is not None
    decisions = client.get("/telefonakquise/decisions").json()["entries"]
    assert [d["outcome"] for d in decisions if d["contact_id"] == ids[0]] == [
        "zugesagt"
    ]


def test_an_answer_of_the_business_is_not_overruled_by_our_judgement(zusagen):
    """Wo der Betrieb selbst geantwortet hat, gibt es nichts einzuschätzen.

    Die Oberfläche bietet den Knopf dort nicht an — und das Backend nimmt ihn
    aus demselben Grund nicht an: die Regel steht an einer Stelle.
    """
    client, ids = zusagen
    _click(client, ids[0], "versendet")
    board = _click(client, ids[0], "positiv")

    assert "kein_bedarf" not in _entry(board, ids[0])["actions"]
    _click(client, ids[0], "kein_bedarf", expected=400)


def test_no_interest_keeps_the_number_out_of_the_next_import(zusagen):
    """Das Versprechen des Knopfes darf nicht an der Import-Historie hängen.

    In aller Regel steht die Nummer längst in der Sperrliste — aber eine
    Sperre lässt sich in der Listenverwaltung wieder freigeben, und dann wäre
    „wird nicht mehr angeschrieben" nur noch eine Vermutung.
    """
    client, ids = zusagen
    key = db.phone_key("05221 111")

    released = client.delete(f"/telefonakquise/blacklist/{key}")
    assert released.status_code == 200, released.text
    assert key not in [e["telefon_key"] for e in _blacklist(client)["entries"]]

    _click(client, ids[0], "kein_bedarf")

    entry = next(e for e in _blacklist(client)["entries"] if e["telefon_key"] == key)
    # Herkunft „von Hand": wer die Zeile später in der Sperrliste sieht, soll
    # dort keine Einfuhr lesen, die so nicht stattgefunden hat.
    assert entry["source"] == "manuell"

    again = ("Betrieb;Telefon\r\n" "Erster Betrieb;05221 111\r\n").encode("utf-8")
    result = client.post(
        "/telefonakquise/lists/analyse",
        files={"file": ("zweite.csv", again, "text/csv")},
    ).json()

    assert result["contacts"] == 0


def test_a_promise_without_interest_is_not_called_again(zusagen, call_db):
    """Was abgeschrieben ist, gehört nicht an die Spitze der Warteschlange.

    Eine fällige Nachfass-Zusage kommt an den Arbeitsplatz zurück — das ist
    der Zweck des Reiters. „Kein Bedarf" nimmt sie dort wieder heraus, ohne
    dass jemand daran denken muss, und ohne den Zustand des Kontakts
    anzufassen.
    """
    client, ids = zusagen
    _click(client, ids[0], "versendet")
    _backdate(call_db, ids[0], MAIL_FOLLOWUP_DAYS + 1)

    assert _state(client)["contact"]["id"] == ids[0]

    _click(client, ids[0], "kein_bedarf")

    assert _state(client)["contact"] is None
    # Das Versanddatum bleibt trotzdem stehen: ob die Mail schon heraus war,
    # als wir den Betrieb abgeschrieben haben, ist die Auskunft, nach der im
    # Nachhinein gefragt wird.
    assert _entry(_board(client), ids[0])["sent_at"] is not None


def test_no_interest_can_be_taken_back(zusagen):
    """Der Fehlklick gehört zum Werkzeug — hier erst recht.

    „Zurücksetzen" ist der einzige Weg heraus: wer den Betrieb doch wieder
    aufnimmt, fängt bei „noch nicht versendet" an, mit einem Versanddatum,
    das dann auch stimmt.
    """
    client, ids = zusagen
    board = _click(client, ids[0], "kein_bedarf")

    assert _entry(board, ids[0])["actions"] == ["offen"]

    board = _click(client, ids[0], "offen")

    assert _entry(board, ids[0])["state"] == "offen"
    assert board["counters"]["offen"] == 2
    assert board["counters"]["kein_bedarf"] == 0


def test_the_build_track_ends_with_no_interest_but_keeps_its_value(zusagen):
    """Dieselbe Regel wie beim Versand: die Bau-Spur führt bis zur Mail.

    Neben „kein Bedarf" ist „Ready to Build" kein Stand mehr, sondern ein
    Widerspruch. Gespeichert bleibt der Marker trotzdem — sonst müsste jemand
    die Website ein zweites Mal ansehen, nur weil eine Zeile zurückgeholt
    wurde.
    """
    client, ids = zusagen
    _mark(client, ids[0], "ready_to_build")

    board = _click(client, ids[0], "kein_bedarf")
    entry = _entry(board, ids[0])

    assert entry["readiness"] == "unbewertet"
    assert entry["readiness_actions"] == []
    # Und ein Marker daran ist eine 400 mit ehrlicher Begründung: hier ist
    # keine Mail heraus, die Zeile ist abgeschlossen.
    body = _mark(client, ids[0], "in_development", expected=400)
    assert "kein Bedarf" in body["detail"]

    entry = _entry(_click(client, ids[0], "offen"), ids[0])
    assert entry["readiness"] == "ready_to_build"


def test_the_export_names_no_interest(zusagen):
    """Die Ausgabe ist die Tabelle, in der hinterher gesucht wird."""
    client, ids = zusagen
    _click(client, ids[0], "kein_bedarf")

    text = client.get("/mailversand/export").content.decode("utf-8-sig")

    assert "kein Bedarf (eingeschätzt)" in text
