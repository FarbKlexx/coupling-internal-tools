"""DTOs des Mailversands — was aus einer Zusage geworden ist.

Die Telefonakquise endet mit einer Zusage: der Betrieb hat am Telefon
zugestimmt, Informationen per E-Mail zu bekommen. Damit ist die Zusage
belegt — was danach passiert, stand bisher nirgends. Wer heute wissen will,
ob die Mail überhaupt heraus ist und was zurückkam, exportiert die Zusagen
als CSV und pflegt daneben eine Tabelle. Genau diese Tabelle ist dieses
Werkzeug.

Es hat **keine eigene Datenhaltung für Kontakte**: die Zeilen sind die
Kontakte der Telefonakquise im Zustand `zugesagt`, aus `calls.db`. Dazu kommt
pro Kontakt ein Versandzustand — und nur der ist neu.

Zwei Dinge fahren wie bei den Anruf-Ergebnissen als *Daten* mit, nicht als
Code:

* `MAIL_ACTIONS` — die Knöpfe samt Beschriftung und Tonlage. Ein weiterer
  Zustand ist eine Änderung an dieser Datei, nicht an der Oberfläche.
* `MailEntry.actions` — welche dieser Knöpfe *an dieser Zeile* etwas
  Sinnvolles tun. Dieselbe Übergangstabelle entscheidet beim Schreiben, also
  kann die Oberfläche keinen Knopf zeigen, der mit 400 antwortet.

Der Zustand `keine_antwort` wird **nicht geschrieben, sondern gerechnet**:
eine versendete Mail, auf die seit `MAIL_TIMEOUT_DAYS` Tagen nichts kam,
erscheint als „keine Antwort". Es gibt in dieser Anwendung keinen
Hintergrundjob, und ein Feld, das erst beim nächsten Aufruf nachgezogen wird,
wäre in der Zwischenzeit falsch. Abgeleitet ist es immer aktuell — und eine
Antwort, die am 31. Tag doch noch kommt, lässt sich weiter eintragen.
"""

from enum import Enum

from pydantic import BaseModel, Field

from app.schemas.call_list import OutcomeTone

#: Nach wie vielen Tagen ohne Antwort eine versendete Mail als unbeantwortet
#: gilt. Kein technischer Wert, sondern eine fachliche Frist: danach lohnt
#: Nachfassen mehr als Warten.
MAIL_TIMEOUT_DAYS = 30

#: Seitengröße der Liste. Sie hat keine Obergrenze — jede Zusage bleibt darin
#: stehen, auch nach Jahren —, also wird geblättert.
MAIL_PAGE_SIZE = 50
MAX_MAIL_PAGE_SIZE = 200

MAX_MAIL_NOTE = 500


class MailState(str, Enum):
    """Wo eine Zusage im Mailversand steht. Gespeichert wird der Slug.

    `keine_antwort` ist der eine Zustand, der auch *ohne* Eintragung
    entstehen kann: er ergibt sich aus dem Versanddatum, sobald die Frist
    abgelaufen ist (siehe Modulkommentar). Von Hand angeklickt werden darf er
    trotzdem — wer weiß, dass nichts mehr kommt, muss nicht 30 Tage warten.
    """

    #: Zusage steht, Mail ist noch nicht heraus. Der Ausgangszustand jeder
    #: Zusage, und der einzige, für den es keine Zeile in der Datenbank gibt.
    OFFEN = "offen"
    VERSENDET = "versendet"
    POSITIV = "positiv"
    ABGELEHNT = "abgelehnt"
    KEINE_ANTWORT = "keine_antwort"


MAIL_STATE_LABELS: dict[MailState, str] = {
    MailState.OFFEN: "Mail noch nicht versendet",
    MailState.VERSENDET: "Mail versendet – wartet auf Antwort",
    MailState.POSITIV: "Antwort positiv",
    MailState.ABGELEHNT: "Angebot abgelehnt",
    MailState.KEINE_ANTWORT: "keine Antwort",
}


#: Welcher Knopf an welcher Zeile etwas Sinnvolles tut.
#:
#: Die Reihenfolge innerhalb einer Zeile ist die der Knöpfe. Gelesen wird die
#: Tabelle an zwei Stellen — die Liste hängt sie an jede Zeile, und das
#: Schreiben prüft dagegen. Deshalb kann die Oberfläche keinen Übergang
#: anbieten, den das Backend ablehnt.
#:
#: Begründungen zu den weniger offensichtlichen Einträgen:
#:
#: * `offen` erlaubt nur „versendet" — „keine Antwort" auf eine Mail, die nie
#:   heraus ist, wäre eine Behauptung über niemanden.
#: * `positiv`/`abgelehnt` erlauben einander: ein Betrieb, der zunächst
#:   interessiert war und dann absagt, ist der Normalfall, nicht der Fehler.
#: * `keine_antwort` erlaubt „versendet" — das ist das Nachfassen, und es setzt
#:   die Frist neu.
#: * `offen` steht überall als Rückweg: der Fehlklick gehört zum Werkzeug.
MAIL_TRANSITIONS: dict[MailState, tuple[MailState, ...]] = {
    MailState.OFFEN: (MailState.VERSENDET,),
    MailState.VERSENDET: (
        MailState.POSITIV,
        MailState.ABGELEHNT,
        MailState.KEINE_ANTWORT,
        MailState.OFFEN,
    ),
    MailState.POSITIV: (MailState.ABGELEHNT, MailState.OFFEN),
    MailState.ABGELEHNT: (MailState.POSITIV, MailState.OFFEN),
    MailState.KEINE_ANTWORT: (
        MailState.VERSENDET,
        MailState.POSITIV,
        MailState.ABGELEHNT,
        MailState.OFFEN,
    ),
}


class MailActionInfo(BaseModel):
    """Ein Knopf, wie ihn das Frontend rendert.

    `id` ist der Zustand, in dem die Zeile danach steht — die Aktion *ist* ihr
    Ziel. Das erspart eine zweite Aufzählung, die mit der ersten übereinstimmen
    müsste.
    """

    id: MailState
    label: str
    description: str
    tone: OutcomeTone


#: Reihenfolge = Reihenfolge der Knöpfe, soweit eine Zeile sie zeigt.
#: Die Tonlage ist Anzeige, keine Logik — dieselbe Aufzählung wie bei den
#: Anruf-Ergebnissen, damit die Oberfläche eine Sprache spricht.
MAIL_ACTIONS: tuple[MailActionInfo, ...] = (
    MailActionInfo(
        id=MailState.VERSENDET,
        label="Mail versendet",
        description=(
            "Die E-Mail ist heraus. Ab jetzt läuft die Frist von "
            f"{MAIL_TIMEOUT_DAYS} Tagen, nach der die Zeile ohne Antwort als "
            "„keine Antwort“ erscheint."
        ),
        tone=OutcomeTone.NEUTRAL,
    ),
    MailActionInfo(
        id=MailState.POSITIV,
        label="Antwort positiv",
        description="Der Betrieb hat geantwortet und will weitermachen.",
        tone=OutcomeTone.POSITIVE,
    ),
    MailActionInfo(
        id=MailState.ABGELEHNT,
        label="Angebot abgelehnt",
        description=(
            "Der Betrieb hat geantwortet und abgelehnt. Das betrifft das "
            "Angebot, nicht die Einwilligung – der Widerspruch gegen Werbung "
            "gehört in die Telefonakquise."
        ),
        tone=OutcomeTone.NEGATIVE,
    ),
    MailActionInfo(
        id=MailState.KEINE_ANTWORT,
        label="keine Antwort",
        description=(
            "Von Hand abgeschlossen, ohne auf die Frist zu warten. Nach "
            f"{MAIL_TIMEOUT_DAYS} Tagen passiert dasselbe von selbst."
        ),
        tone=OutcomeTone.NEUTRAL,
    ),
    MailActionInfo(
        id=MailState.OFFEN,
        label="zurücksetzen",
        description=(
            "Zurück auf „noch nicht versendet“ – für den Fehlklick. "
            "Versand- und Antwortdatum werden dabei verworfen."
        ),
        tone=OutcomeTone.NEUTRAL,
    ),
)


class MailEntry(BaseModel):
    """Eine Zusage in der Versandliste.

    Alles bis `note` kommt aus dem Kontakt der Telefonakquise und wird hier
    nur gelesen; ab `state` ist es der Versandzustand.
    """

    contact_id: str
    betrieb: str
    telefon: str
    email: str
    ort: str
    plz: str
    website: str
    gewerk: str
    list_id: str
    list_name: str
    #: Archivierte Listen bleiben sichtbar: die Zusage gilt weiter, und die
    #: Mail muss trotzdem heraus.
    list_archived: bool
    #: Wann und von wem die Zusage am Telefon aufgenommen wurde — aus dem
    #: Protokoll, also der Nachweis, auf den sich der Versand stützt.
    promised_at: str | None
    promised_by: str
    #: Anmerkung aus dem Telefonat.
    note: str

    state: MailState
    state_label: str
    #: Wahr, wenn dieser Zustand aus der Frist folgt und nicht angeklickt
    #: wurde. Die Oberfläche schreibt „automatisch" daneben — sonst sieht es
    #: aus, als hätte jemand die Zeile abgeschlossen.
    automatic: bool
    sent_at: str | None
    answered_at: str | None
    #: Volle Tage seit dem Versand, oder `null`, solange nichts heraus ist.
    #: Gerechnet, damit „seit 12 Tagen" nicht in jeder Oberfläche neu
    #: entsteht.
    days_since_sent: int | None
    #: Anmerkung zum Versand — getrennt von der aus dem Telefonat, weil beide
    #: nebeneinander gebraucht werden.
    mail_note: str
    updated_at: str | None
    updated_by: str
    #: Welche Knöpfe diese Zeile zeigt, in dieser Reihenfolge. Kommt aus
    #: `MAIL_TRANSITIONS`, gegen die auch das Schreiben prüft.
    actions: list[MailState]


class MailCounters(BaseModel):
    """Die Zahlen über der Liste.

    `offen` ist hier die Zahl, die auf null laufen soll: Zusagen, deren Mail
    noch nicht heraus ist. `versendet` ist das, was auf eine Antwort wartet.
    """

    gesamt: int
    offen: int
    versendet: int
    positiv: int
    abgelehnt: int
    keine_antwort: int
    #: Zusagen ohne Adresse. Sie stehen mit in der Liste, aber ohne
    #: Versand-Knopf — die Nacharbeit, die sonst niemand sieht.
    ohne_email: int


class MailBoard(BaseModel):
    """Die ganze Ansicht in einer Antwort.

    Wie `CallState` und das Kanban-Board: jeder schreibende Aufruf antwortet
    damit, damit der Browser keinen eigenen Stand führt, der auseinanderlaufen
    könnte. Anders als dort ist die Liste geblättert — sie wächst mit jeder
    Zusage und wird nie kürzer.
    """

    revision: int
    counters: MailCounters
    entries: list[MailEntry]
    #: Zusagen insgesamt (ohne Filter) …
    total: int
    #: … und die, die Suche und Zustandsfilter übrig lassen.
    matched: int
    offset: int
    limit: int
    actions: list[MailActionInfo]
    #: Die Frist, damit die Oberfläche sie nennen kann, ohne sie zu kennen.
    timeout_days: int = MAIL_TIMEOUT_DAYS


class MailUpdateRequest(BaseModel):
    """Was ein Klick auf einen der Knöpfe schickt.

    Beide Felder sind einzeln setzbar, weil beide einzeln gebraucht werden:
    ein Knopf ändert den Zustand und lässt die Anmerkung stehen, das
    Anmerkungsfeld ändert die Anmerkung und lässt den Zustand stehen. Ohne das
    zweite müsste man zum Notieren einen Zustand mitschicken — und der
    einzige, der immer erlaubt ist, ist „zurücksetzen".
    """

    #: `None` = Zustand unverändert (dann ist es eine reine Anmerkung).
    state: MailState | None = None
    #: `None` = unverändert, `""` = löschen. Dieselbe Regel wie bei der
    #: E-Mail-Adresse im Anruf-Ergebnis: wer das Feld nicht anfasst, darf eine
    #: vorhandene Anmerkung nicht verlieren.
    note: str | None = Field(default=None, max_length=MAX_MAIL_NOTE)
