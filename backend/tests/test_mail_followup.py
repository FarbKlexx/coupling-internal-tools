"""Der Mailversand — was aus einer Zusage geworden ist.

Zwei Dinge sind hier interessant genug für Tests, und beide betreffen den
Übergang zwischen den zwei Werkzeugen:

* Die Liste hat **keine eigenen Kontakte**. Sie zeigt genau die Zusagen der
  Telefonakquise, und sie muss sich mitbewegen, wenn dort eine Zusage
  zurückgenommen wird.
* Der Zustand „keine Antwort" wird **gerechnet**. Es gibt keinen
  Hintergrundjob, der ihn setzt — er folgt aus dem Versanddatum, und genau
  das lässt sich nur prüfen, indem ein Versanddatum von gestern-vor-40-Tagen
  in die Datenbank geschrieben wird.

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


def test_one_day_short_of_the_deadline_is_still_waiting(zusagen, call_db):
    client, ids = zusagen
    _click(client, ids[0], "versendet")

    _backdate(call_db, ids[0], MAIL_TIMEOUT_DAYS - 1)
    entry = next(e for e in _board(client)["entries"] if e["contact_id"] == ids[0])

    assert entry["state"] == "versendet"
    assert entry["automatic"] is False


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
    assert "Erster Betrieb" in text
    assert "Dritter Betrieb" in text


def test_every_state_can_be_reached_from_somewhere(zusagen):
    """Ein Zustand, in den kein Übergang führt, wäre toter Code.

    Billig zu prüfen und genau die Sorte Lücke, die beim Nachtragen eines
    sechsten Zustands entsteht.
    """
    reachable = {target for targets in MAIL_TRANSITIONS.values() for target in targets}

    assert reachable == set(MailState)


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
    """Eingeschätzt wird, *während* eine Zeile irgendwo steht.

    Die Einschätzung ist keine Stufe im Versand, sondern eine Beobachtung
    über eine Website — sie darf den Versandstand nicht anfassen.
    """
    client, ids = zusagen
    _click(client, ids[0], "versendet")

    board = _mark(client, ids[0], "ready_to_build")
    entry = _entry(board, ids[0])

    assert entry["readiness"] == "ready_to_build"
    assert entry["readiness_label"] == "Ready to Build"
    assert entry["state"] == "versendet"
    assert entry["sent_at"]
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

    # Und er überlebt den Versand — wie jeder andere Marker auch.
    board = _click(client, ids[0], "versendet")
    assert _entry(board, ids[0])["readiness"] == "ready_to_mail"
    assert _board(client, readiness="ready_to_mail")["matched"] == 1


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


def test_a_send_click_keeps_the_marker(zusagen):
    """Sonst verwirft der Weg durch den Versand die Einschätzung still.

    Beide Größen liegen in derselben Zeile, und geschrieben wird sie immer
    ganz — das „unverändert" muss der Service auflösen.
    """
    client, ids = zusagen
    _mark(client, ids[0], "ready_to_build")

    board = _click(client, ids[0], "versendet")
    assert _entry(board, ids[0])["readiness"] == "ready_to_build"

    board = _click(client, ids[0], "positiv")
    assert _entry(board, ids[0])["readiness"] == "ready_to_build"

    # Auch das Zurücksetzen des Versands ist keine Aussage über die Website.
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


def test_a_marker_survives_the_expired_deadline(zusagen, call_db):
    """Ein Marker darf die gerechnete Frist nicht festschreiben.

    Dieselbe Falle wie beim Notizzettel: geschrieben wird der *gespeicherte*
    Zustand, nicht der angezeigte.
    """
    client, ids = zusagen
    _click(client, ids[0], "versendet")
    _backdate(call_db, ids[0], MAIL_TIMEOUT_DAYS + 4)

    board = _mark(client, ids[0], "ready_to_build")
    entry = _entry(board, ids[0])

    assert entry["readiness"] == "ready_to_build"
    assert entry["state"] == "keine_antwort"
    assert entry["automatic"] is True


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

    „Verschickt und Ready to Build" ist die Liste, mit der jemand anfängt zu
    bauen; sie entsteht nur, wenn beide Filter gleichzeitig gelten.
    """
    client, ids = zusagen
    _mark(client, ids[0], "ready_to_build")
    _click(client, ids[0], "versendet")
    _mark(client, ids[1], "ready_to_build")

    both = _board(client, state="versendet", readiness="ready_to_build")
    assert [e["contact_id"] for e in both["entries"]] == [ids[0]]
    assert both["matched"] == 1

    marker_only = _board(client, readiness="ready_to_build")
    assert marker_only["matched"] == 2

    assert _board(client, readiness="missing_content")["matched"] == 0
    assert _board(client, readiness="unbewertet")["matched"] == 0

    # `total` zählt weiter jede Zusage: es ist die Auskunft „gibt es hier
    # überhaupt etwas", an der die leere Liste hängt.
    assert both["total"] == 2
    # Die Zähler dagegen kennen die Auswahl — jede Reihe die der *anderen*:
    # die Reiter zählen innerhalb des Markers (zwei sind Ready to Build), die
    # Marker innerhalb des Reiters (einer davon ist verschickt).
    assert both["counters"]["gesamt"] == 2
    assert both["counters"]["ready_to_build"] == 1


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
    """
    client, ids = zusagen
    # „Erster" ist verschickt und Ready to Build, „Dritter" (ohne Adresse)
    # steht offen und ist Missing Content.
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

    ready = _board(client, readiness="ready_to_build")["counters"]
    assert ready["gesamt"] == 1
    assert (ready["offen"], ready["versendet"]) == (0, 1)
    # Auch die Nacharbeit zählt in der Auswahl: die Zusage ohne Adresse ist
    # Missing Content und steht hier nicht mit in der Liste.
    assert ready["ohne_email"] == 0
    # Der eigene Filter der Markerreihe bleibt draußen.
    assert (ready["missing_content"], ready["unbewertet"]) == (1, 0)
    assert (ready["in_development"], ready["ready_to_mail"]) == (0, 0)


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

    _click(client, ids[0], "versendet")
    hit = _board(
        client, q="+49 5221 111", state="versendet", readiness="ready_to_build"
    )
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

    assert "build_readiness" in columns
    # Der alte Stand bleibt: NULL heißt „noch nicht eingeschätzt", und genau
    # das ist die Wahrheit über eine Zeile von vor der Spalte.
    assert stored["note"] == "alter Eintrag"
    assert stored["build_readiness"] is None

    # Und die Liste antwortet weiter — das ist der Punkt der Übung.
    entry = _entry(_board(client), ids[0])
    assert entry["state"] == "versendet"
    assert entry["readiness"] == "unbewertet"
    assert _board(client)["counters"]["unbewertet"] == 2
