"""DTOs der Telefonakquise.

Das zweite Werkzeug mit Zustand (nach dem Kanban-Board) und das erste, dessen
Zustand ein **Nachweis** ist: Kaltakquise per Telefon darf nur mit
ausdrücklicher Zustimmung in eine E-Mail münden, und wer diese Zustimmung
behauptet, muss sie belegen können (Art. 7 Abs. 1 DSGVO). Deshalb ist das
Protokoll hier kein Nebenprodukt, sondern der Zweck: jede Auswahl des Anrufers
wird als eigene Zeile festgeschrieben, mit Zeitpunkt und Konto.

Zwei Dinge fahren bewusst als *Daten* an das Frontend mit, nicht als Code:

* `OUTCOMES` — die Knöpfe, die der Anrufer sieht, samt Beschriftung, Tonlage
  und der Frage, ob ein Zeitpunkt dazugehört. Ein sechstes Ergebnis ist damit
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


class ContactState(str, Enum):
    """Wo ein Kontakt steht. Gespeichert wird der Slug.

    `offen` und die beiden Wiedervorlage-Zustände sind der Vorrat, aus dem der
    nächste Anruf kommt; die drei anderen sind endgültig — nicht technisch
    (ein Administrator kann eine Liste neu einlesen), sondern fachlich: bei
    `abgelehnt` darf niemand mehr anrufen oder schreiben.
    """

    OFFEN = "offen"
    WIEDERVORLAGE = "wiedervorlage"
    RUECKRUF = "rueckruf"
    ZUGESAGT = "zugesagt"
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
    ContactState.ABGELEHNT: "abgelehnt",
    ContactState.UNGUELTIG: "Nummer unbrauchbar",
}


class CallOutcome(str, Enum):
    """Was der Anrufer nach dem Gespräch anklickt."""

    ZUGESAGT = "zugesagt"
    NICHT_ERREICHBAR = "nicht_erreichbar"
    RUECKRUF = "rueckruf"
    ABGELEHNT = "abgelehnt"
    NUMMER_FALSCH = "nummer_falsch"


#: Welchen Zustand ein Ergebnis setzt. Die Tabelle ist die einzige Stelle, an
#: der aus einem Klick ein Zustand wird.
OUTCOME_STATES: dict[CallOutcome, ContactState] = {
    CallOutcome.ZUGESAGT: ContactState.ZUGESAGT,
    CallOutcome.NICHT_ERREICHBAR: ContactState.WIEDERVORLAGE,
    CallOutcome.RUECKRUF: ContactState.RUECKRUF,
    CallOutcome.ABGELEHNT: ContactState.ABGELEHNT,
    CallOutcome.NUMMER_FALSCH: ContactState.UNGUELTIG,
}


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
        id=CallOutcome.ABGELEHNT,
        label="Nein – ausdrücklich keine Mails",
        description="Ausdrücklicher Widerspruch. Der Kontakt wird nie wieder angerufen oder angeschrieben.",
        tone=OutcomeTone.NEGATIVE,
        time_input=TimeInput.NONE,
        resulting_state=ContactState.ABGELEHNT,
    ),
)


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


class CallContact(BaseModel):
    """Der Kontakt, den der Anrufer vor sich hat — immer nur einer.

    Die erkannten Felder stehen einzeln, alles Übrige in `extras`. Wer sich
    fragt, warum `betrieb` und `telefon` keine Optionale sind: ohne die beiden
    wird eine Zeile beim Import nicht zum Kontakt.
    """

    id: str
    list_id: str
    list_name: str
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


class ListImportResponse(BaseModel):
    """Ergebnis des Imports plus der neue Arbeitsstand."""

    list_id: str
    imported: int
    skipped_rows: list[SkippedRowInfo]
    duplicates: list[SkippedRowInfo]
    warnings: list[str]
    state: CallState
