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

Neben dem Versandstand trägt jede Zeile eine zweite, davon unabhängige
Größe: `BuildReadiness` — wo die *Website* steht, von „lässt sich aus der
bestehenden eine neue bauen?" bis „ist gebaut und wartet auf den Versand".
Sie beantwortet eine andere Frage als der Versandstand („was ist mit der
Seite?") und hat deshalb eigene Marker statt weiterer Zustände.

Und eine dritte: `oversized` („Bigger than expected"). Anders als die beiden
anderen ist sie *kombinierbar* — eine Seite kann gleichzeitig „In
Development" und größer als ein Onepager sein, und genau das ist der Fall,
für den es sie gibt. Sie ist deshalb ein eigenes Feld und kein weiterer Wert
von `BuildReadiness`: als Wert dieser Spur wäre der Umfang beim nächsten
Bauschritt wieder verschwunden, und er ist die Auskunft, die über den ganzen
Bau stehen bleiben soll.

Zwei Zustände werden **nicht geschrieben, sondern gerechnet**, beide aus dem
Versanddatum: nach `MAIL_FOLLOWUP_DAYS` Tagen ohne Antwort erscheint eine
versendete Mail als `nachfassen` („jetzt hinterhertelefonieren"), nach
`MAIL_TIMEOUT_DAYS` Tagen als `keine_antwort`. Es gibt in dieser Anwendung
keinen Hintergrundjob, und ein Feld, das erst beim nächsten Aufruf nachgezogen
wird, wäre in der Zwischenzeit falsch. Abgeleitet ist es immer aktuell — es
gilt rückwirkend für jede Zeile, die schon vor dieser Frist verschickt wurde,
und eine Antwort, die am 31. Tag doch noch kommt, lässt sich weiter eintragen.
"""

from enum import Enum

from pydantic import BaseModel, Field

from app.schemas.call_list import MAX_EMAIL, CallOutcome, ContactField, OutcomeTone

#: Nach wie vielen Tagen ohne Antwort eine versendete Mail als unbeantwortet
#: gilt. Kein technischer Wert, sondern eine fachliche Frist: danach lohnt
#: Nachfassen mehr als Warten.
MAIL_TIMEOUT_DAYS = 30

#: Nach wie vielen Tagen ohne Antwort zum Telefon gegriffen werden soll. Wie
#: die Frist darüber eine fachliche Größe: eine Mail, die zehn Tage
#: unbeantwortet liegt, ist gelesen oder liegengeblieben — beides beantwortet
#: nur ein Anruf. Kleiner als `MAIL_TIMEOUT_DAYS`, sonst gäbe es den
#: Zwischenstand nie (`_MAIL_STATE` prüft die längere Frist zuerst).
MAIL_FOLLOWUP_DAYS = 10

#: Seitengröße der Liste. Sie hat keine Obergrenze — jede Zusage bleibt darin
#: stehen, auch nach Jahren —, also wird geblättert.
MAIL_PAGE_SIZE = 50
MAX_MAIL_PAGE_SIZE = 200

MAX_MAIL_NOTE = 500

#: Längengrenzen des von Hand angelegten Betriebs. Dieselben Werte, die der
#: CSV-Import für dieselben Felder zulässt (`call_list_csv`) — ein Eintrag von
#: Hand darf nicht mehr können als eine Zeile aus der Datei.
MAX_MANUAL_NAME = 200
MAX_MANUAL_NOTE = 2000


class MailState(str, Enum):
    """Wo eine Zusage im Mailversand steht. Gespeichert wird der Slug.

    `nachfassen` und `keine_antwort` sind die beiden Zustände, die auch *ohne*
    Eintragung entstehen: sie ergeben sich aus dem Versanddatum, sobald die
    jeweilige Frist abgelaufen ist (siehe Modulkommentar). `keine_antwort`
    darf trotzdem von Hand angeklickt werden — wer weiß, dass nichts mehr
    kommt, muss nicht 30 Tage warten. `nachfassen` nicht: es ist keine
    Entscheidung, sondern eine Fälligkeit, und die stellt niemand von Hand.
    """

    #: Zusage steht, Mail ist noch nicht heraus. Der Ausgangszustand jeder
    #: Zusage, und der einzige, für den es keine Zeile in der Datenbank gibt.
    OFFEN = "offen"
    VERSENDET = "versendet"
    #: Fällig zum Hinterhertelefonieren: die Mail ist seit
    #: `MAIL_FOLLOWUP_DAYS` Tagen heraus und nichts kam zurück. Wird nie
    #: gespeichert — gespeichert steht dort weiter `versendet`.
    NACHFASSEN = "nachfassen"
    #: Es wurde telefonisch nachgefasst. Die Zeile wartet weiter, taucht aber
    #: nicht mehr unter „Nachfassen" auf; die Frist bis `keine_antwort` läuft
    #: unverändert ab dem Versand weiter.
    NACHGEFASST = "nachgefasst"
    POSITIV = "positiv"
    ABGELEHNT = "abgelehnt"
    KEINE_ANTWORT = "keine_antwort"
    #: Kein Bedarf — **unsere eigene** Einschätzung, ohne Aussage des
    #: Betriebs: die bestehende Website ist gut genug, der Betrieb ist schon
    #: Kunde, die Zusage führt zu nichts. Bewusst neben `abgelehnt` und nicht
    #: darin, dieselbe Trennung wie bei den Anruf-Ergebnissen
    #: (`CallOutcome.KEIN_BEDARF`): `abgelehnt` ist ein Widerspruch des
    #: Betriebs, das hier ein Urteil von uns. Beides in einen Topf zu werfen
    #: hieße, aus der Liste einen Widerspruch herauszulesen, in der keiner
    #: steht — und die Liste ist dazu da, gelesen zu werden.
    #:
    #: Praktisch ist es der Ausgang aus der Arbeit: die Zeile verlässt „Offen"
    #: und steht in ihrem eigenen Reiter. Die Nummer bleibt dabei gesperrt
    #: (siehe `mail_followup_service._block_number_again`), damit kein Import
    #: den Betrieb ein zweites Mal in den Vorrat holt.
    KEIN_BEDARF = "kein_bedarf"


MAIL_STATE_LABELS: dict[MailState, str] = {
    MailState.OFFEN: "Mail noch nicht versendet",
    MailState.VERSENDET: "Mail versendet – wartet auf Antwort",
    MailState.NACHFASSEN: "nachfassen – jetzt anrufen",
    MailState.NACHGEFASST: "nachgefasst – wartet weiter",
    MailState.POSITIV: "Antwort positiv",
    MailState.ABGELEHNT: "Angebot abgelehnt",
    MailState.KEINE_ANTWORT: "keine Antwort",
    MailState.KEIN_BEDARF: "kein Bedarf (eingeschätzt)",
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
#: * `keine_antwort` erlaubt „versendet" — das ist das Nachfassen per Mail, und
#:   es setzt die Frist neu.
#: * `nachfassen` führt als einziger Zustand auf `nachgefasst`: der Knopf ist
#:   die Quittung des Anrufs, und wo nichts fällig ist, gibt es nichts zu
#:   quittieren. Er steht dort an erster Stelle, weil er die Handlung ist, für
#:   die der Reiter da ist.
#: * `nachgefasst` ist kein Ziel und `nachfassen` keines: der eine wird nur aus
#:   der Fälligkeit heraus gesetzt, der andere überhaupt nie — er *entsteht*
#:   aus dem Versanddatum. Deshalb taucht `nachfassen` nur als Zeile auf, nie
#:   in einer.
#: * `kein_bedarf` steht überall dort, wo noch nichts entschieden ist — also
#:   auch an `offen`, und dort ist es der eigentliche Fall: die Website ist
#:   angesehen und schon gut genug, die Mail erübrigt sich. Bis dahin war
#:   „versendet" der einzige Weg aus `offen` heraus, und eine Zusage, aus der
#:   nichts wird, blieb für immer in der Arbeitsliste stehen. **Nicht** an
#:   `positiv`/`abgelehnt`: dort hat der Betrieb selbst geantwortet, und eine
#:   eigene Einschätzung überschreibt keine Aussage.
#: * `offen` steht überall als Rückweg: der Fehlklick gehört zum Werkzeug.
MAIL_TRANSITIONS: dict[MailState, tuple[MailState, ...]] = {
    MailState.OFFEN: (MailState.VERSENDET, MailState.KEIN_BEDARF),
    MailState.VERSENDET: (
        MailState.POSITIV,
        MailState.ABGELEHNT,
        MailState.KEINE_ANTWORT,
        MailState.KEIN_BEDARF,
        MailState.OFFEN,
    ),
    MailState.NACHFASSEN: (
        MailState.NACHGEFASST,
        MailState.POSITIV,
        MailState.ABGELEHNT,
        MailState.VERSENDET,
        MailState.KEINE_ANTWORT,
        MailState.KEIN_BEDARF,
        MailState.OFFEN,
    ),
    MailState.NACHGEFASST: (
        MailState.POSITIV,
        MailState.ABGELEHNT,
        MailState.VERSENDET,
        MailState.KEINE_ANTWORT,
        MailState.KEIN_BEDARF,
        MailState.OFFEN,
    ),
    MailState.POSITIV: (MailState.ABGELEHNT, MailState.OFFEN),
    MailState.ABGELEHNT: (MailState.POSITIV, MailState.OFFEN),
    MailState.KEINE_ANTWORT: (
        MailState.VERSENDET,
        MailState.POSITIV,
        MailState.ABGELEHNT,
        MailState.KEIN_BEDARF,
        MailState.OFFEN,
    ),
    #: Nur der Rückweg. „Kein Bedarf" ist das Ende der Bearbeitung, und wer
    #: den Betrieb doch wieder aufnimmt, fängt bei „noch nicht versendet" an
    #: — mit einem Versanddatum, das dann auch stimmt.
    MailState.KEIN_BEDARF: (MailState.OFFEN,),
}


#: Was ein **Nachfass-Anruf** am Versandstand ändert.
#:
#: Die Brücke zwischen den beiden Werkzeugen: der Anrufer trägt in der
#: Telefonakquise ein Anruf-Ergebnis ein, und dieselbe Handlung setzt hier den
#: Versandstand. Sie steht in dieser Datei und nicht bei den Anruf-Ergebnissen,
#: weil dieses Modul jenes kennen darf und nicht umgekehrt.
#:
#: `nachfassen_nicht_erreicht` fehlt bewusst: niemanden erreicht zu haben
#: sagt nichts über die Mail. Der Kontakt wird aufgeschoben und kommt wieder,
#: der Versandstand bleibt „versendet" — und damit bleibt die Zeile im Reiter
#: „Nachfassen".
FOLLOWUP_MAIL_STATES: dict[CallOutcome, "MailState"] = {
    CallOutcome.NACHGEFASST: MailState.NACHGEFASST,
    CallOutcome.NACHFASSEN_POSITIV: MailState.POSITIV,
    CallOutcome.NACHFASSEN_ABGELEHNT: MailState.ABGELEHNT,
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
        id=MailState.NACHGEFASST,
        label="Nachgefasst",
        description=(
            "Telefonisch nachgefasst – die Zeile verlässt den Reiter und "
            "wartet weiter. Die Frist bis „keine Antwort“ läuft unverändert ab "
            "dem Versand: dieser Knopf hält fest, dass angerufen wurde, nicht, "
            "was dabei herauskam."
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
        id=MailState.KEIN_BEDARF,
        label="Kein Bedarf",
        description=(
            "Eigene Einschätzung, ohne Aussage des Betriebs – etwa weil die "
            "bestehende Website schon gut ist oder der Betrieb bereits Kunde "
            "ist. Die Zeile verlässt die Arbeitsliste und steht unter „Kein "
            "Bedarf“; die Telefonnummer bleibt gesperrt, damit kein Import "
            "den Betrieb noch einmal hereinholt. Der Grund gehört in die "
            "Anmerkung."
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


class BuildReadiness(str, Enum):
    """Wo die Website eines Betriebs steht. Gespeichert wird der Slug.

    Zweite, von `MailState` **unabhängige** Dimension: der Versandstand sagt,
    wo die Mail steht, diese Spur sagt, was mit der Seite ist. Ein Betrieb
    kann „Antwort positiv" und „Missing Content" gleichzeitig sein — das ist
    sogar der Fall, für den die Marker gemacht werden.

    Die ersten beiden Werte sind eine Einschätzung der *bestehenden* Seite.
    Der Unterschied ist nicht „hat eine Domain": aufrufbar sind fast alle.
    Gemeint ist, ob dort Inhalt steht, den die neue Seite übernehmen kann.
    Fehlt er, ist es kein Redesign mehr — dann müssen Texte neu entstehen,
    und darüber muss vorher jemand mit dem Kunden sprechen.

    `in_development` und `ready_to_mail` sind die Schritte danach und die
    einzigen Werte, die nicht von der alten Seite reden, sondern von der
    neuen: sie wird gebaut, und sie ist gebaut, aber noch nicht beim
    Betrieb. Trotzdem hier und nicht als Versandzustände — es ist die
    Website, die vorangeht, nicht die Mail, die heraus ist, und beides steht
    in derselben Liste nebeneinander. Werte derselben Spur sind es, weil
    „lässt sich bauen", „wird gebaut" und „ist gebaut" einander
    ausschließen: hat jemand angefangen, ist die Einschätzung von vorher
    erledigt.

    `unbewertet` ist wie `MailState.OFFEN` der Ausgangszustand und braucht
    keinen Eintrag: eine Zusage, die noch niemand angesehen hat, steht darauf.
    """

    #: Noch nicht angesehen. Der Ausgangszustand jeder Zusage.
    UNBEWERTET = "unbewertet"
    #: Inhalt ist da, die neue Seite kann ihn übernehmen — reines Redesign.
    READY_TO_BUILD = "ready_to_build"
    #: Wird gerade gebaut. Angefangen, aber noch nicht vorzeigbar.
    IN_DEVELOPMENT = "in_development"
    #: Die neue Seite steht, ist aber noch nicht beim Betrieb.
    READY_TO_MAIL = "ready_to_mail"
    #: Seite erreichbar, aber praktisch ohne Inhalt: Texte müssen neu
    #: entstehen, vorher Rücksprache mit dem Kunden.
    MISSING_CONTENT = "missing_content"


READINESS_LABELS: dict[BuildReadiness, str] = {
    BuildReadiness.UNBEWERTET: "noch nicht eingeschätzt",
    BuildReadiness.READY_TO_BUILD: "Ready to Build",
    BuildReadiness.IN_DEVELOPMENT: "In Development",
    BuildReadiness.READY_TO_MAIL: "Ready to Mail",
    BuildReadiness.MISSING_CONTENT: "Missing Content",
}


class ReadinessOptionInfo(BaseModel):
    """Ein Marker, wie ihn das Frontend rendert.

    Wie bei `MailActionInfo` ist die `id` das Ziel — nur gibt es hier keine
    Übergangstabelle: eingeschätzt wird jederzeit und in jedem Versandstand,
    und jeder Wert lässt sich in jeden anderen ändern. Eine Einschätzung ist
    eine Beobachtung über eine Website, kein Vorgang mit Reihenfolge.

    Ohne `tone`: jeder Wert hat in der Oberfläche seine eigene Farbe, denn
    „Missing Content" ist keine schlechte Nachricht (das wäre `negative`),
    sondern mehr Arbeit.
    """

    id: BuildReadiness
    label: str
    description: str


#: Reihenfolge = Reihenfolge der Marker an der Zeile. `unbewertet` steht
#: bewusst mit darin: es ist der Rückweg aus dem Fehlklick, und ohne ihn
#: bliebe eine falsch gesetzte Einschätzung für immer stehen.
READINESS_OPTIONS: tuple[ReadinessOptionInfo, ...] = (
    ReadinessOptionInfo(
        id=BuildReadiness.READY_TO_BUILD,
        label="Ready to Build",
        description=(
            "Die bestehende Website hat Inhalt, den die neue übernehmen kann – "
            "ein Redesign. Kann so in die Umsetzung."
        ),
    ),
    ReadinessOptionInfo(
        id=BuildReadiness.IN_DEVELOPMENT,
        label="In Development",
        description=(
            "Die neue Website wird gerade gebaut – angefangen, aber noch nicht "
            "vorzeigbar. Sagt nichts über den Versandstand daneben."
        ),
    ),
    ReadinessOptionInfo(
        id=BuildReadiness.READY_TO_MAIL,
        label="Ready to Mail",
        description=(
            "Die neue Website ist gebaut und muss nur noch zum Betrieb – "
            "gemeint ist die Seite, nicht die Mail: den Versandstand daneben "
            "ändert dieser Marker nicht."
        ),
    ),
    ReadinessOptionInfo(
        id=BuildReadiness.MISSING_CONTENT,
        label="Missing Content",
        description=(
            "Die Seite ist erreichbar, hat aber kaum Inhalt: Texte müssten neu "
            "entstehen. Erst Rücksprache mit dem Kunden, dann bauen."
        ),
    ),
    ReadinessOptionInfo(
        id=BuildReadiness.UNBEWERTET,
        label="Einschätzung entfernen",
        description="Zurück auf „noch nicht eingeschätzt“ – für den Fehlklick.",
    ),
)


class ScopeMarkerInfo(BaseModel):
    """Der Umfangs-Marker, wie ihn das Frontend rendert.

    Kein Katalog wie `READINESS_OPTIONS`, sondern ein einzelner Eintrag: der
    Marker ist gesetzt oder nicht, und „nicht gesetzt" braucht keine
    Beschriftung. Zwei Beschreibungen trägt er trotzdem, weil ein Umschalter
    zwei Bedeutungen hat — `undo_description` ist die des gesetzten Knopfes,
    dieselbe Rolle wie `unbewertet` im Katalog der Bau-Einschätzung.

    Ohne `tone`, wie die Bau-Marker: „größer als gedacht" ist keine schlechte
    Nachricht, sondern mehr Arbeit.
    """

    label: str
    description: str
    undo_description: str


#: Der eine Umfangs-Marker. Wie die Knöpfe und die Bau-Marker Daten und nicht
#: Code: Beschriftung und Begründung stehen hier, Farbe und Symbol in der
#: Oberfläche.
SCOPE_MARKER = ScopeMarkerInfo(
    label="Bigger than expected",
    description=(
        "Die Seite geht über einen einfachen Onepager hinaus – mehr Umfang, "
        "als bei der Zusage angenommen. Bleibt neben jedem Bauschritt stehen "
        "und ändert weder Versandstand noch Bau-Einschätzung."
    ),
    undo_description=(
        "Zurück auf „Umfang wie erwartet“ – für den Fehlklick und für den "
        "Fall, dass es am Ende doch ein Onepager wird."
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
    #: Die Prio aus der Datei — was sie bedeutet, entscheidet die Analyse, aus
    #: der die Liste kam. Angezeigt wird sie hier nicht; sie gehört zu dem,
    #: was die Zeile zum Kopieren hergibt.
    prio: str
    #: Der Gesprächsaufhänger aus der Datei.
    befunde: str
    #: Alle übrigen Spalten der Anrufliste, in der Reihenfolge der Datei —
    #: dieselbe Wortwahl wie im Kontakt der Telefonakquise. Was darin steht,
    #: weiß nur die Analyse; hier reist es unverändert mit.
    extras: list[ContactField]
    list_id: str
    list_name: str
    #: Archivierte Listen bleiben sichtbar: die Zusage gilt weiter, und die
    #: Mail muss trotzdem heraus.
    list_archived: bool
    #: Von Hand angelegt statt aus einer Datei importiert. Nur diese Zeilen
    #: lassen sich hier auch ändern — was aus einer Anrufliste kam, gehört
    #: der Telefonakquise, und zwei Oberflächen auf denselben Kontakt wären
    #: zwei Wahrheiten. Die Oberfläche hängt ihren Stift daran.
    manual: bool
    #: Wann und von wem die Zusage am Telefon aufgenommen wurde — aus dem
    #: Protokoll, also der Nachweis, auf den sich der Versand stützt.
    promised_at: str | None
    promised_by: str
    #: Anmerkung aus dem Telefonat.
    note: str

    state: MailState
    state_label: str
    #: Die Bau-Einschätzung — zweite Dimension, unabhängig von `state`.
    #: `unbewertet`, solange niemand die Website angesehen hat, **und sobald
    #: die Mail heraus ist**: die Reihe ist ein Weg bis zur Mail, danach
    #: beantwortet der Versandstand dieselbe Frage. Der gesetzte Wert bleibt
    #: dabei gespeichert und kommt zurück, wenn der Versand zurückgesetzt
    #: wird.
    readiness: BuildReadiness
    readiness_label: str
    #: Welche Marker diese Zeile setzen kann, in dieser Reihenfolge — leer,
    #: sobald die Mail heraus ist. Dieselbe Rolle wie `actions` beim
    #: Versandstand: die Oberfläche baut die Regel nicht nach, sondern zeigt,
    #: was das Backend ihr mitgibt, und kann deshalb keinen Knopf bauen, der
    #: mit 400 antwortet.
    readiness_actions: list[BuildReadiness]
    #: „Bigger than expected" — die dritte Größe, kombinierbar mit den
    #: beiden anderen. `False` heißt „niemand hat das gesagt", nicht „ist ein
    #: Onepager": es ist eine Aussage, deren Fehlen keine ist.
    oversized: bool
    #: Wahr, wenn dieser Zustand aus der Frist folgt und nicht angeklickt
    #: wurde. Die Oberfläche schreibt „automatisch" daneben — sonst sieht es
    #: aus, als hätte jemand die Zeile abgeschlossen.
    automatic: bool
    sent_at: str | None
    answered_at: str | None
    #: Wann telefonisch nachgefasst wurde, oder `null`. Steht neben
    #: `sent_at`/`answered_at`, weil es dieselbe Art Auskunft ist: ein
    #: Zeitpunkt, an dem jemand etwas getan hat. `updated_at` reicht dafür
    #: nicht — die nächste Anmerkung überschreibt es.
    followed_up_at: str | None
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
    """Die Zahlen über der Liste — zwei Aufteilungen derselben Menge.

    `offen` ist hier die Zahl, die auf null laufen soll: Zusagen, deren Mail
    noch nicht heraus ist. `versendet` ist das, was auf eine Antwort wartet.

    Die Oberfläche zeigt sie in drei Filtergrößen (Versandstand,
    Bau-Einschätzung, Umfang), und **jede zählt innerhalb der Auswahl der
    anderen**: wer auf „Offen" filtert, bekommt in den Markern die offenen
    Zusagen, deren Zahlen zusammen die Zahl auf dem Reiter ergeben.
    Ihren *eigenen* Filter lässt eine Reihe dabei außen vor — sonst stünde
    auf allen Marken außer der angeklickten eine Null und es gäbe keinen
    Rückweg, der eine Zahl nennt. Die Suche bleibt aus beiden Reihen heraus:
    die Zähler beantworten „wo stehe ich", nicht „wie viele Zeilen sehe ich".
    """

    #: Alle Zusagen der Auswahl — mit Marker-Filter also dessen Anzahl, und
    #: die Zahl hinter dem Reiter „Alle".
    gesamt: int
    offen: int
    versendet: int
    #: Fällig zum Anrufen — die zweite Zahl, die auf null laufen soll. Sie
    #: entsteht von selbst, sobald eine Mail lange genug unbeantwortet liegt.
    nachfassen: int
    #: Angerufen, wartet weiter. Steht neben `versendet`, weil es dasselbe
    #: Warten ist — nur eines, hinter dem schon ein Anruf steht.
    nachgefasst: int
    positiv: int
    abgelehnt: int
    keine_antwort: int
    #: Von uns abgeschriebene Zusagen — kein Widerspruch des Betriebs,
    #: sondern eine Einschätzung. Eigene Zahl und nicht zu `abgelehnt`
    #: geschlagen, aus demselben Grund, aus dem es der eigene Zustand ist.
    kein_bedarf: int
    #: Zusagen ohne Adresse. Sie stehen mit in der Liste, aber ohne
    #: Versand-Knopf — die Nacharbeit, die sonst niemand sieht. Zählt wie die
    #: Reiter über ihr, also innerhalb eines gesetzten Marker-Filters.
    ohne_email: int

    #: Die Bau-Einschätzung, gezählt innerhalb des Versandstand-Filters (ohne
    #: ihn: über alle Zusagen — „wie viele könnten wir sofort bauen?" ist die
    #: Frage, für die die Marker gesetzt werden, und die stellt sich vor der
    #: Antwort auf die Mail).
    ready_to_build: int
    #: Was gerade gebaut wird — die Zahl, die sagt, wie viel in Arbeit ist.
    in_development: int
    #: Gebaut, aber noch nicht beim Betrieb — die Zahl, die am Ende einer
    #: Bau-Runde auf null laufen soll.
    ready_to_mail: int
    missing_content: int
    #: Zusagen, deren Seite größer als ein Onepager ist. Eine Zahl statt
    #: einer Aufteilung: der Marker ist gesetzt oder nicht. Zählt wie die
    #: beiden Reihen mit den *anderen* Filtern und ohne den eigenen.
    oversized: int
    #: Die noch nicht angesehenen. Ausdrücklich mitgeschickt und nicht als
    #: `gesamt` minus die übrigen gerechnet: sonst müsste die Oberfläche die
    #: Regel kennen, dass die Werte einander ausschließen.
    unbewertet: int


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
    #: Die Marker der Bau-Einschätzung, samt Beschriftung — wie `actions`
    #: Daten und nicht Code. Ohne Übergangstabelle: jeder Wert ist immer
    #: erlaubt (siehe `ReadinessOptionInfo`), deshalb hängt die Liste am Board
    #: und nicht an der Zeile.
    readiness_options: list[ReadinessOptionInfo]
    #: Der Umfangs-Marker samt Beschriftung. Einer statt einer Liste: er ist
    #: gesetzt oder nicht.
    scope_marker: ScopeMarkerInfo = SCOPE_MARKER
    #: Die Frist, damit die Oberfläche sie nennen kann, ohne sie zu kennen.
    timeout_days: int = MAIL_TIMEOUT_DAYS
    #: Die kürzere Frist, nach der angerufen werden soll — aus demselben
    #: Grund mitgeschickt.
    followup_days: int = MAIL_FOLLOWUP_DAYS


#: Name der Liste, in der die von Hand angelegten Betriebe landen. Ein
#: Kontakt braucht eine Liste (`contacts.list_id` ist NOT NULL), und eine
#: eigene ist ehrlicher als die erstbeste: so steht an jeder Zeile, woher sie
#: kommt, und die Anrufliste bleibt das, was aus einer Datei kam. Angelegt
#: wird sie beim ersten Eintrag; wiedergefunden wird sie über ihr Kennzeichen
#: in der Datenbank, nicht über diesen Namen — er lässt sich umbenennen.
MANUAL_LIST_NAME = "Manuell erfasst"


class ManualEntryRequest(BaseModel):
    """Ein von Hand erfasster Betrieb — angelegt wie geändert.

    Der Mailversand hat keine eigenen Kontakte: was hier entsteht, ist ein
    Kontakt der Telefonakquise im Zustand `zugesagt`, samt Protokollzeile.
    Ohne diese Zeile stünde im Nachweis nichts — und der Nachweis ist der
    Grund, warum es das Protokoll gibt.

    `betrieb` und `email` sind Pflicht: die Zeile existiert, damit eine Mail
    hinausgeht, und eine Zusage ohne Adresse ist genau die Nacharbeit, die
    dieses Werkzeug sichtbar machen soll — sie von Hand *anzulegen* wäre
    verkehrt herum. Alles andere ist freiwillig; die Nummer ist es auch, aber
    sie ist die einzige, mit der die Doppelprüfung gegen Listen und Blacklist
    arbeiten kann.
    """

    betrieb: str = Field(min_length=1, max_length=MAX_MANUAL_NAME)
    email: str = Field(min_length=1, max_length=MAX_EMAIL)
    telefon: str = Field(default="", max_length=MAX_MANUAL_NAME)
    plz: str = Field(default="", max_length=MAX_MANUAL_NAME)
    ort: str = Field(default="", max_length=MAX_MANUAL_NAME)
    website: str = Field(default="", max_length=MAX_MANUAL_NAME)
    gewerk: str = Field(default="", max_length=MAX_MANUAL_NAME)
    #: Woher der Kontakt kommt, was besprochen wurde — landet an derselben
    #: Stelle wie die Anmerkung aus dem Telefonat und im Protokoll.
    note: str = Field(default="", max_length=MAX_MANUAL_NOTE)
    #: Nur beim Anlegen: eine schon bekannte Nummer trotzdem übernehmen.
    #: Dieselbe ausdrückliche Bestätigung wie beim Löschen einer Liste — die
    #: Meldung nennt vorher, wo die Nummer bereits steht.
    force: bool = False


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
    #: Die Bau-Einschätzung. `None` = unverändert — gelöscht wird nicht durch
    #: Weglassen, sondern durch `unbewertet`: bei mehreren Werten ist der
    #: Rückweg selbst einer, und ein Marker, den nur das *Fehlen* eines Feldes
    #: entfernt, wäre von „nicht mitgeschickt" nicht zu unterscheiden.
    readiness: BuildReadiness | None = None
    #: „Bigger than expected". `None` = unverändert, `True`/`False` setzen
    #: ihn — hier reicht das Feld selbst als Rückweg, weil es zwei Werte hat
    #: und `False` deshalb kein „unbewertet" braucht.
    oversized: bool | None = None
