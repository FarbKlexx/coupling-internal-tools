"""DTOs der Telefonakquise.

Das zweite Werkzeug mit Zustand (nach dem Kanban-Board) und das erste, dessen
Zustand ein **Nachweis** ist: Kaltakquise per Telefon darf nur mit
ausdrücklicher Zustimmung in eine E-Mail münden, und wer diese Zustimmung
behauptet, muss sie belegen können (Art. 7 Abs. 1 DSGVO). Deshalb ist das
Protokoll hier kein Nebenprodukt, sondern der Zweck: jede Auswahl des Anrufers
wird als eigene Zeile festgeschrieben, mit Zeitpunkt und Konto.

Zwei Dinge fahren bewusst als *Daten* an das Frontend mit, nicht als Code:

* `OUTCOMES` — die Knöpfe, die der Anrufer sieht, samt Beschriftung, Tonlage
  und der Frage, ob ein Zeitpunkt dazugehört. Ein weiteres Ergebnis ist damit
  eine Änderung an dieser Datei, nicht an der Oberfläche.
* die Zusatzspalten eines Kontakts (`extras`) — die Liste bringt mit, was in
  der CSV stand, in der Reihenfolge der Datei. Eine andere Liste braucht keinen
  neuen Code, solange „Betrieb" und „Telefon" darin vorkommen.
"""

from enum import Enum

from pydantic import BaseModel, Field

MAX_LIST_NAME = 120
MAX_NOTE = 2000
MAX_EMAIL = 254

# Vorlauf, mit dem ein vereinbarter Rückruf wieder auftaucht. Ein Termin um
# 14:00 erscheint um 13:45 — wer erst um 14:00 daran erinnert wird, ruft um
# 14:03 an.
CALLBACK_LEAD_MINUTES = 15

# Grenzen der Wiedervorlage. Unten 5 Minuten (alles darunter ist ein
# Fehlklick), oben 90 Tage (darüber ist es kein „später heute" mehr, sondern
# eine neue Liste).
MIN_SNOOZE_MINUTES = 5
MAX_SNOOZE_MINUTES = 90 * 24 * 60

#: Seitengröße der Entscheidungsliste unter dem Arbeitsplatz. Absichtlich
#: klein: darin wird der eigene Fehlklick von eben gesucht, nicht der Anruf von
#: vorletzter Woche — dafür gibt es den Protokoll-Export.
DECISION_PAGE_SIZE = 20
MAX_DECISION_PAGE_SIZE = 100

#: Seitengröße, mit der die *Suche* in dieser Liste arbeitet. Größer als die
#: Liste selbst, weil im Suchbetrieb kein „weitere anzeigen" mehr steht: eine
#: Seite muss halten, was ein sinnvoller Begriff trifft (ein Betrieb hat
#: selten mehr als eine Handvoll Eintragungen). Wer mehr trifft, hat einen zu
#: weiten Begriff — die Seite sagt es ihm dann.
DECISION_SEARCH_PAGE_SIZE = MAX_DECISION_PAGE_SIZE

#: Seitengröße der Kontaktsuche. Wie bei den Entscheidungen klein gehalten:
#: gesucht wird ein bestimmter Betrieb, nicht geblättert.
SEARCH_PAGE_SIZE = 10
MAX_SEARCH_PAGE_SIZE = 50
MAX_SEARCH_TERM = 200

# Seitengröße der Blacklist-Ansicht. Sie kann zehntausende Nummern enthalten,
# also wird geblättert statt alles zu schicken.
BLACKLIST_PAGE_SIZE = 50
MAX_BLACKLIST_PAGE_SIZE = 200
MAX_BLACKLIST_NOTE = 200
#: Wie viele Nummern in einem Rutsch von Hand eingetragen werden dürfen. Für
#: mehr gibt es den CSV-Weg.
MAX_PASTED_NUMBERS = 1000
#: Wert, unter dem Zeilen ohne Prio in der Auswahl geführt werden. Ein leerer
#: String ist als Auswahlwert unsichtbar; dieser hier steht in keiner echten
#: Datei und lässt sich als „Prio ist leer" lesen.
NO_PRIO_VALUE = "__ohne__"


class ContactState(str, Enum):
    """Wo ein Kontakt steht. Gespeichert wird der Slug.

    `offen` und die beiden Wiedervorlage-Zustände sind der Vorrat, aus dem der
    nächste Anruf kommt; die übrigen sind endgültig — nicht technisch
    (ein Administrator kann eine Liste neu einlesen), sondern fachlich: bei
    `abgelehnt` darf niemand mehr anrufen oder schreiben.

    `kein_bedarf` steht bewusst neben `abgelehnt` und nicht darin: es ist
    unsere eigene Einschätzung (Blick auf die Webseite, Bestandskunde), kein
    Widerspruch des Betriebs. Wer die beiden zusammenwirft, liest später einen
    Widerspruch aus einer Zeile, in der niemand widersprochen hat — und genau
    das soll das Protokoll nicht können.
    """

    OFFEN = "offen"
    WIEDERVORLAGE = "wiedervorlage"
    RUECKRUF = "rueckruf"
    ZUGESAGT = "zugesagt"
    KEIN_BEDARF = "kein_bedarf"
    ABGELEHNT = "abgelehnt"
    UNGUELTIG = "ungueltig"


#: Zustände, aus denen der nächste Anruf gezogen wird.
POOL_STATES: tuple[ContactState, ...] = (
    ContactState.RUECKRUF,
    ContactState.OFFEN,
    ContactState.WIEDERVORLAGE,
)

STATE_LABELS: dict[ContactState, str] = {
    ContactState.OFFEN: "offen",
    ContactState.WIEDERVORLAGE: "Wiedervorlage",
    ContactState.RUECKRUF: "Rückruf vereinbart",
    ContactState.ZUGESAGT: "Zusage",
    ContactState.KEIN_BEDARF: "kein Bedarf (eingeschätzt)",
    ContactState.ABGELEHNT: "abgelehnt",
    ContactState.UNGUELTIG: "Nummer unbrauchbar",
}


class CallOutcome(str, Enum):
    """Was der Anrufer nach dem Gespräch anklickt."""

    ZUGESAGT = "zugesagt"
    NICHT_ERREICHBAR = "nicht_erreichbar"
    #: Jemand war am Apparat, aber nicht der, mit dem zu reden ist — und ein
    #: Termin kam auch nicht heraus. Bewusst nicht `nicht_erreichbar`: dort
    #: hat niemand abgenommen, hier ist der Betrieb erreicht und nur der
    #: Ansprechpartner nicht da. Für den nächsten Anruf ist das ein
    #: Unterschied („Frau Meier ist ab Montag wieder da"), und das Protokoll
    #: ist die Stelle, an der er nachlesbar bleibt.
    AP_NICHT_DA = "ap_nicht_da"
    RUECKRUF = "rueckruf"
    KEIN_BEDARF = "kein_bedarf"
    ABGELEHNT = "abgelehnt"
    NUMMER_FALSCH = "nummer_falsch"

    # Ergebnisse eines **Nachfass-Anrufs**: die Mail liegt seit der Frist
    # unbeantwortet beim Betrieb, und der Anrufer hakt nach. Sie sind eigene
    # Werte und nicht die von oben, weil sie den Zustand des Kontakts
    # **nicht** verändern dürfen: er steht auf `zugesagt`, und genau daran
    # hängt seine Zeile im Mailversand. Ein „nicht erreichbar" aus der oberen
    # Gruppe machte daraus eine Wiedervorlage — und die Zusage samt
    # Versanddatum wäre aus dem Mailversand verschwunden.
    #
    # Was sie stattdessen ändern, ist der *Versandstand* (siehe
    # `FOLLOWUP_MAIL_STATES` in `schemas/mail_followup.py`).

    #: Erreicht, die Mail ist bekannt, der Betrieb meldet sich.
    NACHGEFASST = "nachgefasst"
    #: Niemand am Apparat. Kommt nach der gewählten Zeit wieder nach oben.
    NACHFASSEN_NICHT_ERREICHT = "nachfassen_nicht_erreicht"
    #: Am Telefon bestätigtes Interesse — Versandstand „Antwort positiv".
    NACHFASSEN_POSITIV = "nachfassen_positiv"
    #: Kein Interesse am Angebot. Ausdrücklich *kein* Werbewiderspruch —
    #: dafür gibt es `ABGELEHNT`, und nur das nimmt den Betrieb aus dem
    #: Verteiler.
    NACHFASSEN_ABGELEHNT = "nachfassen_abgelehnt"


#: Welchen Zustand ein Ergebnis setzt. Die Tabelle ist die einzige Stelle, an
#: der aus einem Klick ein Zustand wird.
OUTCOME_STATES: dict[CallOutcome, ContactState] = {
    CallOutcome.ZUGESAGT: ContactState.ZUGESAGT,
    CallOutcome.NICHT_ERREICHBAR: ContactState.WIEDERVORLAGE,
    CallOutcome.AP_NICHT_DA: ContactState.WIEDERVORLAGE,
    CallOutcome.RUECKRUF: ContactState.RUECKRUF,
    CallOutcome.KEIN_BEDARF: ContactState.KEIN_BEDARF,
    CallOutcome.ABGELEHNT: ContactState.ABGELEHNT,
    CallOutcome.NUMMER_FALSCH: ContactState.UNGUELTIG,
    # Die vier Nachfass-Ergebnisse lassen den Zustand, wie er ist: die Zusage
    # gilt weiter, und nur so bleibt die Zeile im Mailversand stehen. Was sie
    # bewegen, ist der Versandstand.
    CallOutcome.NACHGEFASST: ContactState.ZUGESAGT,
    CallOutcome.NACHFASSEN_NICHT_ERREICHT: ContactState.ZUGESAGT,
    CallOutcome.NACHFASSEN_POSITIV: ContactState.ZUGESAGT,
    CallOutcome.NACHFASSEN_ABGELEHNT: ContactState.ZUGESAGT,
}


#: Ergebnisse, die den Anrufzähler des Kontakts *nicht* erhöhen. „Nummer
#: falsch" ist ein Fund über die Liste, „kein Bedarf" eine Einschätzung, die
#: meistens ohne Gespräch getroffen wird (Webseite, Bestandskunde) — beides
#: sind keine Anrufversuche beim Betrieb, und `attempts` soll die Frage „wie
#: oft habe ich es dort schon versucht?" beantworten.
ATTEMPT_FREE_OUTCOMES: frozenset[CallOutcome] = frozenset(
    {CallOutcome.NUMMER_FALSCH, CallOutcome.KEIN_BEDARF}
)


class OutcomeTone(str, Enum):
    """Farbe des Knopfes — Anzeige, keine Logik."""

    POSITIVE = "positive"
    NEUTRAL = "neutral"
    NEGATIVE = "negative"


class TimeInput(str, Enum):
    """Welchen Zeitpunkt ein Ergebnis zusätzlich braucht.

    `snooze` = eine Dauer („in 2 Stunden"), `appointment` = ein Termin
    („morgen 9:30"), `none` = keiner. Das Frontend baut daraus, was es nach dem
    Klick fragt, statt die Fälle selbst zu kennen.
    """

    NONE = "none"
    SNOOZE = "snooze"
    APPOINTMENT = "appointment"


class OutcomeInfo(BaseModel):
    """Ein Knopf, wie ihn das Frontend rendert."""

    id: CallOutcome
    label: str
    description: str
    tone: OutcomeTone
    time_input: TimeInput
    #: Zustand, in dem der Kontakt danach steht — für die Anzeige „danach:
    #: Zusage" und damit das Frontend nichts nachschlagen muss.
    resulting_state: ContactState


# Reihenfolge = Reihenfolge der Knöpfe. Die Zusage steht vorn, weil sie das
# Ziel des Anrufs ist; „keine Mails" steht hinten, weil ein Fehlklick dort am
# meisten kostet.
OUTCOMES: tuple[OutcomeInfo, ...] = (
    OutcomeInfo(
        id=CallOutcome.ZUGESAGT,
        label="Zusage – E-Mail erlaubt",
        description="Der Betrieb hat am Telefon zugestimmt, Informationen per E-Mail zu bekommen.",
        tone=OutcomeTone.POSITIVE,
        time_input=TimeInput.NONE,
        resulting_state=ContactState.ZUGESAGT,
    ),
    OutcomeInfo(
        id=CallOutcome.NICHT_ERREICHBAR,
        label="Nicht erreichbar",
        description="Niemand am Apparat. Der Kontakt kommt nach der gewählten Zeit zurück.",
        tone=OutcomeTone.NEUTRAL,
        time_input=TimeInput.SNOOZE,
        resulting_state=ContactState.WIEDERVORLAGE,
    ),
    OutcomeInfo(
        id=CallOutcome.AP_NICHT_DA,
        label="Ansprechpartner nicht da",
        description=(
            "Der Betrieb war erreichbar, der Ansprechpartner nicht – und ein "
            "Termin kam nicht dabei heraus. Der Kontakt kommt nach der "
            "gewählten Zeit zurück."
        ),
        tone=OutcomeTone.NEUTRAL,
        time_input=TimeInput.SNOOZE,
        resulting_state=ContactState.WIEDERVORLAGE,
    ),
    OutcomeInfo(
        id=CallOutcome.RUECKRUF,
        label="Rückruf vereinbart",
        description=(
            "Ein Termin wurde abgesprochen. Der Kontakt erscheint "
            f"{CALLBACK_LEAD_MINUTES} Minuten vorher wieder."
        ),
        tone=OutcomeTone.NEUTRAL,
        time_input=TimeInput.APPOINTMENT,
        resulting_state=ContactState.RUECKRUF,
    ),
    OutcomeInfo(
        id=CallOutcome.NUMMER_FALSCH,
        label="Nummer falsch / Betrieb weg",
        description="Kein Datenfehler des Betriebs, sondern der Liste – wird nicht erneut angerufen.",
        tone=OutcomeTone.NEUTRAL,
        time_input=TimeInput.NONE,
        resulting_state=ContactState.UNGUELTIG,
    ),
    OutcomeInfo(
        id=CallOutcome.KEIN_BEDARF,
        label="Kein Bedarf – eigene Einschätzung",
        description=(
            "Eigene Einschätzung des Anrufers, ohne Aussage des Betriebs – "
            "etwa nach einem Blick auf die Webseite oder weil der Betrieb "
            "schon Kunde ist. Der Grund gehört in die Anmerkung."
        ),
        tone=OutcomeTone.NEUTRAL,
        time_input=TimeInput.NONE,
        resulting_state=ContactState.KEIN_BEDARF,
    ),
    OutcomeInfo(
        id=CallOutcome.ABGELEHNT,
        label="Nein – ausdrücklich keine Mails",
        description="Ausdrücklicher Widerspruch. Der Kontakt wird nie wieder angerufen oder angeschrieben.",
        tone=OutcomeTone.NEGATIVE,
        time_input=TimeInput.NONE,
        resulting_state=ContactState.ABGELEHNT,
    ),
)


#: Ein Knopf zu seiner ID. Damit der Service den Zeitbedarf eines Ergebnisses
#: *nachschlägt*, statt die Fälle ein zweites Mal aufzuzählen — sonst hätte ein
#: weiteres Ergebnis mit Wiedervorlage zwei Stellen, und die zweite fällt erst
#: auf, wenn sie fehlt.
#: Die Ergebnisse eines **Nachfass-Anrufs** — eigener Katalog, eigene Knöpfe.
#:
#: Getrennt von `OUTCOMES`, weil sie einander ausschließen: am Erstanruf wäre
#: „Nachgefasst" sinnlos, und am Nachfass-Kontakt richtete „Zusage" nichts aus
#: (die steht schon) und „nicht erreichbar" richtete Schaden an (die Zusage
#: verschwände aus dem Mailversand). Welcher Katalog gilt, entscheidet
#: `allowed_outcomes` — und dieselbe Funktion prüft beim Schreiben.
#:
#: Reihenfolge = Reihenfolge der Knöpfe: erst das, was in den meisten Fällen
#: passiert.
FOLLOWUP_OUTCOMES: tuple[OutcomeInfo, ...] = (
    OutcomeInfo(
        id=CallOutcome.NACHGEFASST,
        label="Nachgefasst – schaut es sich an",
        description=(
            "Erreicht: die Mail ist angekommen, der Betrieb meldet sich. Die "
            "Zeile verlässt den Reiter „Nachfassen“; die Frist bis „keine "
            "Antwort“ läuft unverändert ab dem Versand weiter."
        ),
        tone=OutcomeTone.POSITIVE,
        time_input=TimeInput.NONE,
        resulting_state=ContactState.ZUGESAGT,
    ),
    OutcomeInfo(
        id=CallOutcome.NACHFASSEN_NICHT_ERREICHT,
        label="Niemanden erreicht",
        description=(
            "Niemand am Apparat. Der Betrieb kommt nach der gewählten Zeit "
            "wieder nach oben; am Versandstand ändert sich nichts."
        ),
        tone=OutcomeTone.NEUTRAL,
        time_input=TimeInput.SNOOZE,
        resulting_state=ContactState.ZUGESAGT,
    ),
    OutcomeInfo(
        id=CallOutcome.NACHFASSEN_POSITIV,
        label="Interesse bestätigt",
        description=(
            "Am Telefon bestätigt: der Betrieb will weitermachen. Im "
            "Mailversand steht die Zeile danach auf „Antwort positiv“."
        ),
        tone=OutcomeTone.POSITIVE,
        time_input=TimeInput.NONE,
        resulting_state=ContactState.ZUGESAGT,
    ),
    OutcomeInfo(
        id=CallOutcome.NACHFASSEN_ABGELEHNT,
        label="Kein Interesse",
        description=(
            "Das Angebot ist vom Tisch – die Einwilligung bleibt bestehen. "
            "Wer ausdrücklich keine Werbung mehr will, gehört auf "
            "„Ablehnung – keine Mails“ darunter."
        ),
        tone=OutcomeTone.NEGATIVE,
        time_input=TimeInput.NONE,
        resulting_state=ContactState.ZUGESAGT,
    ),
)


#: Alle Ergebnisse beider Kataloge, nachschlagbar über ihre ID.
OUTCOME_BY_ID: dict[CallOutcome, OutcomeInfo] = {
    info.id: info for info in (*OUTCOMES, *FOLLOWUP_OUTCOMES)
}

#: Die Ergebnisse, die es nur am Nachfass-Anruf gibt — in der Reihenfolge
#: ihrer Knöpfe, weil die Oberfläche sie so rendert.
FOLLOWUP_OUTCOME_IDS: tuple[CallOutcome, ...] = tuple(
    info.id for info in FOLLOWUP_OUTCOMES
)


def correctable_outcomes(outcome: CallOutcome) -> list[CallOutcome]:
    """Welche Ergebnisse beim Richtigstellen *dieser* Eintragung zur Wahl stehen.

    Nicht dieselbe Frage wie `allowed_outcomes`, und darum eine eigene
    Funktion: dort geht es um den Kontakt, der gerade vorliegt, hier um eine
    Entscheidung, die schon getroffen wurde. Eine Zusage, die ein Fehlklick
    war, muss sich in „kein Bedarf" ändern lassen — nach dem Zustand des
    Kontakts gefragt käme der Nachfass-Katalog heraus, und der Fehlklick
    bliebe für immer stehen.

    Maßstab ist deshalb die Eintragung selbst: ein Nachfass-Anruf wird zu
    einem anderen Nachfass-Ergebnis richtiggestellt, ein gewöhnlicher Anruf
    zu einem gewöhnlichen. Zwischen den Katalogen zu wechseln wäre keine
    Richtigstellung mehr, sondern eine andere Geschichte.
    """
    if outcome in FOLLOWUP_OUTCOME_IDS:
        return [*FOLLOWUP_OUTCOME_IDS, CallOutcome.ABGELEHNT]

    return [info.id for info in OUTCOMES]


def allowed_outcomes(state: ContactState) -> list[CallOutcome]:
    """Welche Ergebnisse an einem Kontakt in diesem Zustand etwas tun.

    Die einzige Stelle, die das entscheidet — gelesen an drei Orten: der
    Arbeitsplatz bestückt seine Knöpfe damit, das Entscheidungs-Protokoll
    seine Richtigstellung, und `_write_outcome` prüft dagegen. Dasselbe
    Muster wie `MAIL_TRANSITIONS` im Mailversand: die Oberfläche kann keinen
    Knopf zeigen, den das Schreiben ablehnt.

    Eine **Zusage** bekommt den Nachfass-Katalog — sie ist der einzige
    Zustand, in dem der Arbeitsplatz einen Kontakt vorlegt, ohne dass es um
    einen Erstanruf geht. Dazu kommt `abgelehnt` aus dem großen Katalog: der
    Werbewiderspruch muss in jedem Gespräch eintragbar sein, und er ist das
    einzige Ergebnis, das die Zusage beenden darf.

    Alle anderen Zustände bekommen den gewöhnlichen Katalog.
    """
    if state is ContactState.ZUGESAGT:
        return [*FOLLOWUP_OUTCOME_IDS, CallOutcome.ABGELEHNT]

    return [info.id for info in OUTCOMES]


class ContactField(BaseModel):
    """Eine Zusatzspalte der CSV, wie sie unter „Details" erscheint."""

    label: str
    value: str


class CallEventInfo(BaseModel):
    """Eine Protokollzeile. Wird nie geändert, nur angehängt."""

    occurred_at: str
    username: str
    outcome: CallOutcome
    outcome_label: str
    note: str
    email: str
    appointment_at: str | None
    due_at: str | None


class ContactFollowup(BaseModel):
    """Der Versandstand am Kontakt — nur für Zusagen, deren Mail heraus ist.

    Der Grund, warum dieser Betrieb überhaupt wieder vorgelegt wird: es ist
    kein Erstanruf, sondern ein Nachfassen zu einer Mail, die seit Tagen
    unbeantwortet liegt. Ohne diese Angaben meldete sich der Anrufer, als
    wäre es das erste Gespräch — und der Betrieb hat schon zugesagt und eine
    Mail bekommen.

    `due` kommt gerechnet aus der Datenbank (derselbe Ausdruck, der im
    Mailversand den Reiter „Nachfassen" füllt) und nicht aus einer Rechnung
    in der Oberfläche: dieselbe Frist, eine Stelle.
    """

    #: Wann die Mail hinausgegangen ist (UTC).
    sent_at: str
    #: Volle Tage seit dem Versand — die Zahl, die im Gespräch zählt.
    days_since_sent: int
    #: Ob gerade nachzufassen ist. Falsch heißt: die Mail ist noch nicht lange
    #: genug draußen (oder die lange Frist ist schon abgelaufen).
    due: bool
    #: Die Anmerkung aus dem Mailversand — was beim letzten Mal notiert wurde.
    mail_note: str


class CallContact(BaseModel):
    """Der Kontakt, den der Anrufer vor sich hat — immer nur einer.

    Die erkannten Felder stehen einzeln, alles Übrige in `extras`. Wer sich
    fragt, warum `betrieb` und `telefon` keine Optionale sind: ohne die beiden
    wird eine Zeile beim Import nicht zum Kontakt.
    """

    id: str
    list_id: str
    list_name: str
    #: Ob diese Liste beendet ist. Im Anrufvorrat immer `False` (archivierte
    #: Listen kommen dort nicht vor) und deshalb mit Standardwert — gebraucht
    #: wird es von der Kontaktsuche, die absichtlich auch in beendeten Listen
    #: nachsieht.
    list_archived: bool = False
    betrieb: str
    telefon: str
    email: str
    ort: str
    plz: str
    website: str
    gewerk: str
    prio: str
    befunde: str
    extras: list[ContactField]
    state: ContactState
    state_label: str
    attempts: int
    due_at: str | None
    appointment_at: str | None
    note: str
    #: Alle bisherigen Versuche, jüngster zuerst. Erspart einen zweiten Aufruf
    #: und ist die Antwort auf „habe ich hier schon mal angerufen?".
    history: list[CallEventInfo]
    #: Gesetzt, sobald zu diesem Betrieb eine Mail heraus ist — der
    #: Unterschied zwischen Erstanruf und Nachfassen. `null` beim Erstanruf.
    followup: ContactFollowup | None = None
    #: Welche Ergebnisse an *diesem* Kontakt etwas Sinnvolles tun, in der
    #: Reihenfolge der Knöpfe. Kommt aus `allowed_outcomes`, gegen die auch
    #: das Schreiben prüft — die Oberfläche kann deshalb keinen Knopf zeigen,
    #: der mit 400 antwortet. Dasselbe Muster wie `MailEntry.actions`.
    outcomes: list[CallOutcome] = Field(default_factory=list)


class CallContactPage(BaseModel):
    """Treffer der Kontaktsuche.

    Trägt ganze `CallContact`-Objekte samt Protokoll und nicht eine eigene,
    kürzere Zeile: die Frage hinter der Suche ist „was war bei diesem Betrieb
    schon?", und die Antwort darauf ist genau das, was auch am Arbeitsplatz
    steht. Ein zweites, abgespecktes DTO wäre eine zweite Stelle, an der ein
    neues Kontaktfeld nachgetragen werden müsste.
    """

    entries: list[CallContact]
    #: Treffer insgesamt — `entries` ist nur die aktuelle Seite.
    matched: int
    offset: int
    limit: int
    #: Der Begriff, zu dem diese Seite gehört. Das Frontend verwirft damit die
    #: Antwort auf eine Suche, die der Anwender schon weitergetippt hat.
    query: str


class CallCounters(BaseModel):
    """Die Zahlen über dem Kontakt.

    `offen` ist die Zahl, die auf null laufen soll: noch nicht angerufen plus
    alles, dessen Wiedervorlage fällig ist. Aufgeschobenes zählt bewusst
    *nicht* mit — sonst stünde dort eine Zahl, an der gerade niemand arbeiten
    kann.
    """

    gesamt: int
    offen: int
    wiedervorlage: int
    zugesagt: int
    #: Zusagen, deren Mail zum Nachfassen fällig ist — die stehen im
    #: Anrufvorrat ganz vorne. Kein eigener Kontaktzustand: in `state` steht
    #: bei ihnen weiter `zugesagt`, und dort zählen sie auch mit.
    nachfassen: int = 0
    #: Von uns selbst als „kein Bedarf" eingeschätzt — bewusst getrennt von
    #: `abgelehnt`, das ein Widerspruch des Betriebs ist.
    kein_bedarf: int
    abgelehnt: int
    ungueltig: int
    #: Zusagen, zu denen keine Adresse bekannt ist. Genau die Zusagen, aus
    #: denen ohne Nacharbeit keine E-Mail wird.
    zugesagt_ohne_email: int


class CallListInfo(BaseModel):
    """Eine importierte Liste in der Verwaltung."""

    id: str
    name: str
    source_filename: str
    created_at: str
    created_by: str
    archived: bool
    counters: CallCounters


class CallState(BaseModel):
    """Der ganze Arbeitsstand in einer Antwort.

    Wie beim Kanban-Board antwortet jeder schreibende Aufruf damit: der Client
    hält keinen eigenen Stand, der auseinanderlaufen könnte.
    """

    revision: int
    counters: CallCounters
    #: Der nächste anzurufende Kontakt, oder `null`, wenn nichts fällig ist.
    contact: CallContact | None
    #: Wann der nächste aufgeschobene Kontakt zurückkommt — die Antwort auf
    #: „nichts zu tun, und jetzt?".
    next_due_at: str | None
    outcomes: list[OutcomeInfo]
    lists: list[CallListInfo]
    #: Wie viele Nummern gesperrt sind. Steht in der Verwaltung über dem
    #: Abschnitt, damit sichtbar ist, dass es die Sperre gibt, bevor sie eine
    #: Zeile beim Import verschluckt.
    blacklist_count: int = 0


class OutcomeRequest(BaseModel):
    """Was der Anrufer nach dem Gespräch abschickt.

    `email` und `note` reisen mit dem Ergebnis, nicht als eigener Aufruf: was
    im Gespräch erfahren wurde („schreiben Sie an info@…"), gehört in dieselbe
    Protokollzeile wie die Zusage selbst.

    Zeitpunkte kommen als vollständige ISO-8601-Zeitstempel *mit* Zeitzone vom
    Browser. Absicht: „morgen früh" hängt von der Zeitzone des Anrufers ab, und
    die kennt der Browser, während das Backend dafür eine Zeitzonendatenbank im
    Container bräuchte.
    """

    outcome: CallOutcome
    note: str = Field(default="", max_length=MAX_NOTE)
    #: `None` = unverändert, `""` = löschen.
    email: str | None = Field(default=None, max_length=MAX_EMAIL)
    #: Für „nicht erreichbar": Dauer in Minuten …
    snooze_minutes: int | None = None
    #: … oder ein konkreter Zeitpunkt (etwa „morgen 8:00").
    due_at: str | None = None
    #: Für „Rückruf vereinbart": der abgesprochene Termin.
    appointment_at: str | None = None


class ListUpdateRequest(BaseModel):
    """Umbenennen oder stilllegen. Nur gesetzte Felder werden geschrieben."""

    name: str | None = Field(default=None, min_length=1, max_length=MAX_LIST_NAME)
    #: Archivierte Listen verschwinden aus dem Anrufvorrat, bleiben aber im
    #: Protokoll und in den Ausgaben — das ist der normale Weg, eine Liste zu
    #: beenden.
    archived: bool | None = None


class SkippedRowInfo(BaseModel):
    """Eine Zeile, aus der kein Kontakt wurde — mit Nummer und Grund."""

    line: int
    reason: str


class ColumnMappingInfo(BaseModel):
    """Welche Spalte der Datei auf welchem Feld landet."""

    field: str
    label: str
    column: str
    empty_count: int


class PrioOption(BaseModel):
    """Ein Prio-Wert, wie er in der hochgeladenen Datei vorkommt.

    Die Werte kommen aus der Datei und nicht aus einer Aufzählung im Code: was
    „Prio" bedeutet, entscheidet die Auswertung, aus der die Liste stammt —
    mal A/B/C, mal 1–5, mal „hoch"/„mittel". Eine feste Liste im Backend wäre
    bei der nächsten Auswertung falsch.
    """

    #: Der Wert, wie er zurückgeschickt werden muss. Für Zeilen ohne Prio
    #: steht hier `NO_PRIO_VALUE`.
    value: str
    #: Wie er angezeigt wird („A", „(ohne Prio)").
    label: str
    #: Zeilen mit diesem Wert in der Datei.
    rows: int
    #: Davon die, die tatsächlich importiert würden — nach Abzug der
    #: unbrauchbaren Zeilen und der schon bekannten Nummern. Das ist die Zahl,
    #: die das Frontend über die Auswahl aufsummiert, damit der Knopf nicht
    #: mehr verspricht, als der Import liefert.
    contacts: int


class ListAnalyseResponse(BaseModel):
    """Trockenlauf: was der Import ergäbe, ohne etwas zu speichern.

    Derselbe Weg wie beim Import selbst, damit die Vorschau nichts anderes
    behaupten kann als das Ergebnis (das Muster der Namensschilder).
    """

    name_suggestion: str
    encoding: str
    delimiter: str
    data_rows: int
    contacts: int
    mapping: list[ColumnMappingInfo]
    extra_columns: list[str]
    skipped_rows: list[SkippedRowInfo]
    duplicates: list[SkippedRowInfo]
    warnings: list[str]
    #: Überschrift der Prio-Spalte, oder `null`, wenn die Datei keine hat.
    #: Das Frontend blendet die Auswahl danach ein oder aus.
    prio_column: str | None = None
    #: Die vorkommenden Prio-Werte, in der Reihenfolge ihres ersten Auftretens
    #: in der Datei — die Reihenfolge der Auswertung ist meistens die, in der
    #: der Anwender sie erwartet.
    prio_values: list[PrioOption] = Field(default_factory=list)


class ListImportResponse(BaseModel):
    """Ergebnis des Imports plus der neue Arbeitsstand."""

    list_id: str
    imported: int
    skipped_rows: list[SkippedRowInfo]
    duplicates: list[SkippedRowInfo]
    warnings: list[str]
    state: CallState
    #: Zeilen, die wegen der Prio-Auswahl draußen blieben. Als Zahl und nicht
    #: als Liste: sie sind kein Befund, sondern das, was verlangt wurde.
    prio_skipped: int = 0
    #: Nummern, die dieser Import neu gesperrt hat.
    blacklisted: int = 0


# --------------------------------------------------------------------------
# Entscheidungen nachträglich richtigstellen
# --------------------------------------------------------------------------


class CallDecision(BaseModel):
    """Eine getroffene Entscheidung, wie sie in der Liste unter dem
    Arbeitsplatz steht.

    Dieselbe Zeile wie im Protokoll, nur um das ergänzt, was die Oberfläche
    braucht, um zu entscheiden, ob sich daran noch etwas ändern lässt — sonst
    müsste sie pro Zeile nachfragen.
    """

    event_id: int
    contact_id: str
    occurred_at: str
    username: str
    outcome: CallOutcome
    outcome_label: str
    betrieb: str
    telefon: str
    list_name: str
    note: str
    email: str
    due_at: str | None
    appointment_at: str | None
    #: Zustand, in dem der Kontakt *jetzt* steht.
    state: ContactState
    state_label: str
    #: Diese Zeile stellt eine frühere richtig.
    corrects_event_id: int | None
    #: Diese Zeile wurde später selbst richtiggestellt — sie bleibt sichtbar,
    #: aber durchgestrichen. Ein stillschweigend verschwundener Eintrag wäre
    #: genau die Sorte Protokoll, die als Nachweis nichts taugt.
    corrected: bool
    #: Ob sich hier noch etwas ändern lässt.
    correctable: bool
    #: Welche Ergebnisse beim Richtigstellen zur Wahl stehen — dieselbe Regel
    #: wie am Arbeitsplatz (`allowed_outcomes`, gelesen am Zustand des
    #: Kontakts). Ohne sie böte das Protokoll einem Erstanruf „Nachgefasst"
    #: an, was das Schreiben mit 400 ablehnt.
    outcomes: list[CallOutcome] = Field(default_factory=list)
    #: Warum nicht — leer, solange `correctable` wahr ist.
    locked_reason: str = ""


class CallDecisionPage(BaseModel):
    """Ein Ausschnitt der Entscheidungsliste, jüngste zuerst.

    Mit `query` ist es dieselbe Liste, auf einen Betrieb eingegrenzt: die
    Suche der Seite geht durch dieses Fenster, weil an ihm auch das Ändern
    hängt. Ein Treffer ist deshalb eine *Eintragung* und kein Betrieb — die
    Frage „was war bei Klappschmidt?" beantwortet die Reihe seiner
    Eintragungen, und die jüngste davon lässt sich gleich richtigstellen.
    """

    entries: list[CallDecision]
    #: Eintragungen insgesamt — mit `query` die Zahl der Treffer. `entries`
    #: ist nur die aktuelle Seite.
    total: int
    offset: int
    limit: int
    #: Der Begriff, zu dem diese Seite gehört; leer für die letzten
    #: Eintragungen. Das Frontend verwirft damit die Antwort auf eine Suche,
    #: die der Anwender schon weitergetippt hat — wie bei `CallContactPage`.
    query: str = ""


# --------------------------------------------------------------------------
# Blacklist
# --------------------------------------------------------------------------


class BlacklistSource(str, Enum):
    """Woher eine Sperre stammt."""

    IMPORT = "import"
    MANUELL = "manuell"
    #: Über einen von Hand angelegten Eintrag im Mailversand in den Bestand
    #: gekommen. Eigener Wert und nicht `import`, weil die Meldung über eine
    #: schon bekannte Nummer die Herkunft benennt — „schon einmal importiert"
    #: wäre für eine Nummer, die nie in einer Datei stand, schlicht falsch.
    ERFASST = "erfasst"


BLACKLIST_SOURCE_LABELS: dict[BlacklistSource, str] = {
    BlacklistSource.IMPORT: "importiert",
    BlacklistSource.MANUELL: "von Hand",
    BlacklistSource.ERFASST: "von Hand erfasst",
}


class BlacklistEntry(BaseModel):
    """Eine gesperrte Nummer.

    `telefon_key` ist der Ziffernschlüssel und zugleich die Adresse des
    Eintrags — `telefon` ist die Schreibweise, in der die Nummer ankam, und
    steht nur zum Lesen da.
    """

    telefon_key: str
    telefon: str
    betrieb: str
    source: BlacklistSource
    source_label: str
    #: Name der Liste, aus der die Nummer stammt — als Text festgehalten,
    #: damit er das Löschen dieser Liste überlebt.
    list_name: str
    note: str
    created_at: str
    created_by: str


class BlacklistPage(BaseModel):
    """Ein Ausschnitt der Blacklist. Sie wird geblättert, nicht geladen."""

    entries: list[BlacklistEntry]
    total: int
    #: Treffer der aktuellen Suche; ohne Suche gleich `total`.
    matched: int
    offset: int
    limit: int


class BlacklistAddRequest(BaseModel):
    """Nummern von Hand sperren.

    `numbers` ist Freitext: eine Nummer pro Zeile, Komma und Semikolon zählen
    auch als Trenner. Absicht — die Quelle ist eine E-Mail oder ein
    Tabellenausschnitt, und wer daraus erst eine CSV bauen muss, tut es nicht.
    """

    numbers: str
    note: str = Field(default="", max_length=MAX_BLACKLIST_NOTE)


class BlacklistMutationResponse(BaseModel):
    """Ergebnis einer Änderung an der Blacklist, plus die erste Seite."""

    added: int
    #: Nummern, die schon gesperrt waren.
    already_known: int
    #: Zeilen ohne verwertbare Nummer, mit Grund.
    skipped: list[SkippedRowInfo]
    page: BlacklistPage
