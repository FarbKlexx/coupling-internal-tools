/**
 * Die Versandliste.
 *
 * Fünf Dinge sind hier eigene Logik und nicht bloß Anzeige: die Reiter (welche
 * es gibt, was sie zählen, welcher als aktiv gilt), dass eine Zeile genau die
 * Knöpfe zeigt, die das Backend ihr mitgibt (und keine, die es ablehnen
 * würde), dass eine Anmerkung *ohne* Zustand abgeschickt wird, dass eine
 * Zusage ohne Adresse als solche kenntlich ist statt still zu verschwinden,
 * und dass die Bau-Einschätzung ein Umschalter ist: derselbe Marker nochmal
 * nimmt ihn zurück, und den Versandstand fasst er dabei nicht an.
 */
import { describe, expect, it, vi, type Mock } from "vitest";
import { mount } from "@vue/test-utils";
import MailFollowupList from "./MailFollowupList.vue";
import type {
  BuildReadiness,
  MailActionInfo,
  MailBoard,
  MailEntry,
  MailState,
  ReadinessOptionInfo,
  ScopeMarkerInfo,
} from "@/api/mail_followup.api";

const actions: MailActionInfo[] = [
  {
    id: "versendet",
    label: "Mail versendet",
    description: "Die E-Mail ist heraus.",
    tone: "neutral",
  },
  { id: "positiv", label: "Antwort positiv", description: "Will weitermachen.", tone: "positive" },
  { id: "abgelehnt", label: "Angebot abgelehnt", description: "Hat abgelehnt.", tone: "negative" },
  { id: "keine_antwort", label: "keine Antwort", description: "Von Hand.", tone: "neutral" },
  { id: "offen", label: "zurücksetzen", description: "Für den Fehlklick.", tone: "neutral" },
];

/** Der Umfangs-Marker, wie das Backend ihn mitschickt. */
const scopeMarker: ScopeMarkerInfo = {
  label: "Bigger than expected",
  description: "Mehr als ein Onepager.",
  undo_description: "Zurück auf Umfang wie erwartet.",
};

/** Der Marker-Katalog, wie das Backend ihn mitschickt. */
const readinessOptions: ReadinessOptionInfo[] = [
  { id: "ready_to_build", label: "Ready to Build", description: "Inhalt ist da." },
  { id: "in_development", label: "In Development", description: "Wird gerade gebaut." },
  { id: "ready_to_mail", label: "Ready to Mail", description: "Gebaut, muss noch raus." },
  { id: "missing_content", label: "Missing Content", description: "Erst Rücksprache." },
  { id: "unbewertet", label: "Einschätzung entfernen", description: "Für den Fehlklick." },
];

const entry: MailEntry = {
  contact_id: "k1",
  betrieb: "Azmanlar Tayfun Malermeister",
  telefon: "+49 5224 79473",
  email: "info@tayfun-design.de",
  ort: "Herford",
  plz: "32052",
  website: "",
  gewerk: "Maler",
  prio: "A",
  befunde: "Seite lädt langsam",
  extras: [{ label: "Ladezeit", value: "4,2 s" }],
  list_id: "l1",
  list_name: "Handwerker Herford",
  list_archived: false,
  promised_at: "2026-09-01T09:00:00Z",
  promised_by: "anruferin",
  note: "will Preise sehen",
  state: "offen",
  state_label: "Mail noch nicht versendet",
  readiness: "unbewertet",
  readiness_label: "noch nicht eingeschätzt",
  oversized: false,
  automatic: false,
  sent_at: null,
  answered_at: null,
  days_since_sent: null,
  mail_note: "",
  updated_at: null,
  updated_by: "",
  actions: ["versendet"],
};

function board(...entries: MailEntry[]): MailBoard {
  const rows = entries.length ? entries : [entry];

  return {
    revision: 1,
    counters: {
      gesamt: rows.length,
      offen: rows.length,
      versendet: 0,
      positiv: 0,
      abgelehnt: 0,
      keine_antwort: 0,
      ohne_email: rows.filter((row) => !row.email).length,
      ready_to_build: rows.filter((row) => row.readiness === "ready_to_build").length,
      in_development: rows.filter((row) => row.readiness === "in_development").length,
      ready_to_mail: rows.filter((row) => row.readiness === "ready_to_mail").length,
      missing_content: rows.filter((row) => row.readiness === "missing_content").length,
      unbewertet: rows.filter((row) => row.readiness === "unbewertet").length,
      oversized: rows.filter((row) => row.oversized).length,
    },
    entries: rows,
    total: rows.length,
    matched: rows.length,
    offset: 0,
    limit: 50,
    actions,
    readiness_options: readinessOptions,
    scope_marker: scopeMarker,
    timeout_days: 30,
  };
}

/** Die Filter-Aufrufe, typisiert – sonst passt `vi.fn()` nicht auf die Prop. */
type FilterMock = Mock<(state: MailState | null) => void>;
type ReadinessFilterMock = Mock<(readiness: BuildReadiness | null) => void>;

function mountList(
  entries: MailEntry[] = [],
  save = vi.fn().mockResolvedValue(true),
  extra: {
    filterBy?: FilterMock;
    stateFilter?: MailState | null;
    readinessFilter?: BuildReadiness | null;
    oversizedFilter?: boolean | null;
  } = {},
) {
  const filterBy: FilterMock = extra.filterBy ?? vi.fn();
  const filterByReadiness: ReadinessFilterMock = vi.fn();
  const filterByScope: Mock<() => void> = vi.fn();

  const wrapper = mount(MailFollowupList, {
    props: {
      board: board(...entries),
      actions,
      readinessOptions,
      scopeMarker,
      timeoutDays: 30,
      isLoading: false,
      isSaving: false,
      filterBy,
      filterByReadiness,
      filterByScope,
      goToPage: vi.fn(),
      save,
      query: "",
      stateFilter: extra.stateFilter ?? null,
      readinessFilter: extra.readinessFilter ?? null,
      oversizedFilter: extra.oversizedFilter ?? null,
    },
  });

  return { wrapper, save, filterBy, filterByReadiness, filterByScope };
}

/** Die Knöpfe *einer* Zeile, ohne Reiter und Werkzeugleiste. */
function rowButtons(wrapper: ReturnType<typeof mount>) {
  return wrapper.findAll("li button").map((button) => button.text());
}

describe("MailFollowupList", () => {
  it("bietet einen Reiter je Zustand, plus „Alle“", () => {
    const { wrapper } = mountList();

    const tabs = wrapper.findAll("[role='tab']").map((tab) => tab.attributes("data-tab"));

    expect(tabs).toEqual(["alle", "offen", "versendet", "positiv", "abgelehnt", "keine_antwort"]);
  });

  it("filtert beim Klick auf einen Reiter", async () => {
    const { wrapper, filterBy } = mountList();

    await wrapper.find("[data-tab='versendet']").trigger("click");

    expect(filterBy).toHaveBeenCalledWith("versendet");
  });

  it("hebt den Filter über den Reiter „Alle“ wieder auf", async () => {
    const { wrapper, filterBy } = mountList([], undefined, { stateFilter: "versendet" });

    await wrapper.find("[data-tab='alle']").trigger("click");

    expect(filterBy).toHaveBeenCalledWith(null);
  });

  it("markiert den aktiven Reiter – auch fuer Screenreader", () => {
    const { wrapper } = mountList([], undefined, { stateFilter: "versendet" });

    const active = wrapper.find("[data-tab='versendet']");

    expect(active.classes()).toContain("tab--active");
    expect(active.attributes("aria-selected")).toBe("true");
    expect(wrapper.find("[data-tab='alle']").attributes("aria-selected")).toBe("false");
  });

  it("zaehlt auf den Reitern alle Zusagen, nicht die gerade sichtbaren", () => {
    // Sonst zeigte jeder Reiter waehrend einer Suche die Zahl der Treffer –
    // und beantwortete die Frage nicht mehr, fuer die er da ist.
    const { wrapper } = mountList();

    expect(wrapper.find("[data-tab='alle']").text()).toContain("1");
    expect(wrapper.find("[data-tab='offen']").text()).toContain("1");
    expect(wrapper.find("[data-tab='positiv']").text()).toContain("0");
  });

  it("zeigt genau die Knoepfe, die das Backend der Zeile mitgibt", () => {
    // Die Uebergaenge stehen im Backend; eine Oberflaeche, die sie nachbaut,
    // bietet frueher oder spaeter einen an, der mit 400 antwortet.
    const { wrapper } = mountList();

    const labels = rowButtons(wrapper);

    expect(labels.some((text) => text.includes("Mail versendet"))).toBe(true);
    expect(labels.some((text) => text.includes("Antwort positiv"))).toBe(false);
    expect(labels.some((text) => text.includes("zurücksetzen"))).toBe(false);
  });

  it("schickt beim Klick den Zustand und sonst nichts", async () => {
    const { wrapper, save } = mountList();

    const button = wrapper.findAll("li button").find((b) => b.text().includes("Mail versendet"));
    await button?.trigger("click");

    expect(save).toHaveBeenCalledWith("k1", { state: "versendet" });
  });

  it("schickt eine Anmerkung ohne Zustand", async () => {
    // Notiert wird, waehrend eine Zeile wartet – ein Zustand im selben Aufruf
    // wuerde eine abgelaufene Frist als Entscheidung festschreiben.
    const { wrapper, save } = mountList();

    const noteButton = wrapper.findAll("li button").find((b) => b.text().includes("Anmerkung"));
    await noteButton?.trigger("click");
    await wrapper.find("li textarea").setValue("Angebot mit Preisliste");
    const submit = wrapper.findAll("li button").find((b) => b.text() === "Speichern");
    await submit?.trigger("click");

    expect(save).toHaveBeenCalledWith("k1", { note: "Angebot mit Preisliste" });
  });

  it("macht eine Zusage ohne Adresse kenntlich, statt sie zu verschweigen", () => {
    const { wrapper } = mountList([{ ...entry, contact_id: "k2", email: "", actions: [] }]);

    expect(wrapper.text()).toContain("keine E-Mail-Adresse");
    expect(rowButtons(wrapper).some((text) => text.includes("Mail versendet"))).toBe(false);
  });

  it("verlinkt die Website des Betriebs, auch ohne Schema in der CSV", () => {
    // Beim Nachfassen die Frage „mit wem rede ich hier eigentlich?" – und die
    // Analysen schreiben „www.beispiel.de", woraus ein relativer Link wuerde.
    const { wrapper } = mountList([{ ...entry, website: "www.tayfun-design.de" }]);

    // Ueber `target` und nicht ueber den Text: die Adresse der Zeile steht als
    // `mailto:` in derselben Zeile und traegt oft dieselbe Domain.
    const link = wrapper.find("li a[target='_blank']");

    expect(link.attributes("href")).toBe("https://www.tayfun-design.de/");
    expect(link.attributes("rel")).toBe("noopener noreferrer");
    expect(link.text()).toContain("tayfun-design.de");
  });

  it("zeigt eine Zeile ohne Website ohne leeren Link", () => {
    const { wrapper } = mountList();

    expect(wrapper.find("li a[target='_blank']").exists()).toBe(false);
  });

  it("macht aus einem Wort wie „keine“ keinen Link, laesst es aber stehen", () => {
    // In dieser Spalte steht auch, was gar keine Adresse ist.
    const { wrapper } = mountList([{ ...entry, website: "keine" }]);

    expect(wrapper.find("li a[target='_blank']").exists()).toBe(false);
    expect(wrapper.text()).toContain("keine");
  });

  it("weist den automatisch gesetzten Zustand als solchen aus", () => {
    // Sonst sieht die Zeile aus, als haette jemand sie abgeschlossen.
    const { wrapper } = mountList([
      {
        ...entry,
        state: "keine_antwort",
        state_label: "keine Antwort",
        automatic: true,
        sent_at: "2026-07-20T09:00:00Z",
        days_since_sent: 46,
        actions: ["versendet", "positiv", "abgelehnt", "offen"],
      },
    ]);

    expect(wrapper.text()).toContain("automatisch");
    expect(wrapper.text()).toContain("seit 46 Tagen");
  });

  it("sagt bei leerer Liste, woher die Zeilen kaemen", () => {
    const empty: MailBoard = { ...board(), entries: [], total: 0, matched: 0 };
    const wrapper = mount(MailFollowupList, {
      props: {
        board: empty,
        actions,
        readinessOptions,
        scopeMarker,
        timeoutDays: 30,
        isLoading: false,
        isSaving: false,
        filterBy: vi.fn(),
        filterByReadiness: vi.fn(),
        filterByScope: vi.fn(),
        goToPage: vi.fn(),
        save: vi.fn(),
        query: "",
        stateFilter: null,
        readinessFilter: null,
        oversizedFilter: null,
      },
    });

    expect(wrapper.text()).toContain("Telefonakquise");
  });
  it("setzt die Bau-Einschaetzung ohne Zustand", async () => {
    // Zwei unabhaengige Groessen: ein Marker darf den Versandstand nicht
    // anfassen – und erst gar nicht eine abgelaufene Frist festschreiben.
    const { wrapper, save } = mountList();

    await wrapper.find("li [data-marker='ready_to_build']").trigger("click");

    expect(save).toHaveBeenCalledWith("k1", { readiness: "ready_to_build" });
  });

  it("nimmt denselben Marker beim zweiten Klick wieder zurueck", async () => {
    // Der Fehlklick gehoert zum Werkzeug: ein Marker, den man nur setzen
    // kann, waere fuer die Zeile eine Einbahnstrasse.
    const { wrapper, save } = mountList([{ ...entry, readiness: "ready_to_build" }]);

    await wrapper.find("li [data-marker='ready_to_build']").trigger("click");

    expect(save).toHaveBeenCalledWith("k1", { readiness: "unbewertet" });
  });

  it("ersetzt den einen Marker durch den anderen", async () => {
    // Entweder die alte Seite hat Inhalt, oder sie hat keinen.
    const { wrapper, save } = mountList([{ ...entry, readiness: "ready_to_build" }]);

    await wrapper.find("li [data-marker='missing_content']").trigger("click");

    expect(save).toHaveBeenCalledWith("k1", { readiness: "missing_content" });
  });

  it("setzt den Marker fuer die Seite in Arbeit ohne den Versandstand", async () => {
    // Angefangen heisst nicht verschickt: auch dieser Marker schickt kein
    // `state` und ersetzt die Einschaetzung von vorher.
    const { wrapper, save } = mountList([{ ...entry, readiness: "ready_to_build" }]);

    const button = wrapper.find("li [data-marker='in_development']");

    expect(button.text()).toContain("In Development");
    expect(button.attributes("title")).toBe("Wird gerade gebaut.");

    await button.trigger("click");

    expect(save).toHaveBeenCalledWith("k1", { readiness: "in_development" });
  });

  it("setzt den Marker fuer die gebaute Seite ohne den Versandstand", async () => {
    // Die *Website* ist fertig, die Mail ist damit nicht heraus: der Marker
    // schickt kein `state`, sonst waere er ein sechster Versandzustand.
    const { wrapper, save } = mountList([{ ...entry, readiness: "ready_to_build" }]);

    const button = wrapper.find("li [data-marker='ready_to_mail']");

    expect(button.text()).toContain("Ready to Mail");
    expect(button.attributes("title")).toBe("Gebaut, muss noch raus.");

    await button.trigger("click");

    expect(save).toHaveBeenCalledWith("k1", { readiness: "ready_to_mail" });
  });

  it("zeigt den gesetzten Marker in der Zeile, den fehlenden nicht", () => {
    // Ein Marker, den man beim Ueberfliegen nicht sieht, ist keiner – und
    // „unbewertet" ist keine Aussage ueber eine Website.
    const marked = mountList([
      { ...entry, readiness: "missing_content", readiness_label: "Missing Content" },
    ]);

    expect(marked.wrapper.find("[data-readiness='missing_content']").exists()).toBe(true);
    expect(marked.wrapper.text()).toContain("Missing Content");

    const unmarked = mountList();

    expect(unmarked.wrapper.find("[data-readiness='unbewertet']").exists()).toBe(false);
  });

  it("beschriftet die Marker mit dem, was das Backend mitschickt", () => {
    // Wie bei den Zustands-Knoepfen: Beschriftung und Beschreibung sind Daten.
    const { wrapper } = mountList();

    const button = wrapper.find("li [data-marker='missing_content']");

    expect(button.text()).toContain("Missing Content");
    expect(button.attributes("title")).toBe("Erst Rücksprache.");
  });

  it("erklaert am gesetzten Marker den Rueckweg", () => {
    // Der Titel des aktiven Knopfes ist die Beschreibung von „entfernen" –
    // sonst ist der zweite Klick nicht zu erraten.
    const { wrapper } = mountList([{ ...entry, readiness: "ready_to_build" }]);

    const button = wrapper.find("li [data-marker='ready_to_build']");

    expect(button.attributes("title")).toBe("Für den Fehlklick.");
    expect(button.attributes("aria-pressed")).toBe("true");
  });

  it("filtert nach der Bau-Einschaetzung, unabhaengig vom Reiter", async () => {
    const { wrapper, filterByReadiness, filterBy } = mountList([], undefined, {
      stateFilter: "versendet",
    });

    await wrapper.find("[data-readiness-filter='ready_to_build']").trigger("click");

    expect(filterByReadiness).toHaveBeenCalledWith("ready_to_build");
    // Der Reiter bleibt, wo er ist: „verschickt und Ready to Build" ist die
    // Liste, mit der jemand zu bauen anfaengt.
    expect(filterBy).not.toHaveBeenCalled();
  });

  it("zaehlt an den Filtern alle Zusagen, nach Einschaetzung getrennt", () => {
    const { wrapper } = mountList([
      { ...entry, readiness: "ready_to_build" },
      { ...entry, contact_id: "k2", readiness: "missing_content" },
      { ...entry, contact_id: "k3", readiness: "ready_to_mail" },
      { ...entry, contact_id: "k4", readiness: "in_development" },
      { ...entry, contact_id: "k5" },
    ]);

    expect(wrapper.find("[data-readiness-filter='ready_to_build']").text()).toContain("1");
    expect(wrapper.find("[data-readiness-filter='missing_content']").text()).toContain("1");
    expect(wrapper.find("[data-readiness-filter='ready_to_mail']").text()).toContain("1");
    expect(wrapper.find("[data-readiness-filter='in_development']").text()).toContain("1");
    expect(wrapper.find("[data-readiness-filter='unbewertet']").text()).toContain("1");
  });

  it("markiert den aktiven Einschaetzungs-Filter fuer Screenreader", () => {
    const { wrapper } = mountList([], undefined, { readinessFilter: "missing_content" });

    expect(
      wrapper.find("[data-readiness-filter='missing_content']").attributes("aria-pressed"),
    ).toBe("true");
    expect(
      wrapper.find("[data-readiness-filter='ready_to_build']").attributes("aria-pressed"),
    ).toBe("false");
  });

  it("setzt den Umfang zusaetzlich zur Bau-Einschaetzung, nicht anstelle", async () => {
    // Der ganze Grund fuer die eigene Groesse: „In Development" UND groesser
    // als ein Onepager ist die Auskunft, fuer die es den Marker gibt. Der
    // Klick schickt deshalb nur `oversized` – alles andere heisst
    // „unveraendert".
    const { wrapper, save } = mountList([{ ...entry, readiness: "in_development" }]);

    const button = wrapper.find("li [data-scope-marker]");

    expect(button.text()).toContain("Bigger than expected");
    expect(button.attributes("title")).toBe("Mehr als ein Onepager.");

    await button.trigger("click");

    expect(save).toHaveBeenCalledWith("k1", { oversized: true });
  });

  it("nimmt den Umfangs-Marker beim zweiten Klick wieder zurueck", async () => {
    // `false` ist hier der Rueckweg – bei zwei Werten braucht es kein
    // „unbewertet" wie bei der Bau-Einschaetzung.
    const { wrapper, save } = mountList([{ ...entry, oversized: true }]);

    const button = wrapper.find("li [data-scope-marker]");

    expect(button.attributes("aria-pressed")).toBe("true");
    expect(button.attributes("title")).toBe("Zurück auf Umfang wie erwartet.");

    await button.trigger("click");

    expect(save).toHaveBeenCalledWith("k1", { oversized: false });
  });

  it("zeigt Umfang und Bau-Einschaetzung gleichzeitig in der Zeile", () => {
    // Zwei Marken in einer Zeile: genau das kann die Bau-Spur allein nicht.
    const { wrapper } = mountList([
      {
        ...entry,
        readiness: "in_development",
        readiness_label: "In Development",
        oversized: true,
      },
    ]);

    expect(wrapper.find("[data-readiness='in_development']").exists()).toBe(true);
    expect(wrapper.find("[data-oversized]").exists()).toBe(true);

    // Ohne Marker steht dort nichts – „hat niemand gesagt" ist keine Aussage.
    expect(mountList().wrapper.find("[data-oversized]").exists()).toBe(false);
  });

  it("filtert nach dem Umfang, ohne die anderen Filter anzufassen", async () => {
    const { wrapper, filterByScope, filterBy, filterByReadiness } = mountList([], undefined, {
      stateFilter: "versendet",
      readinessFilter: "in_development",
    });

    await wrapper.find("[data-scope-filter]").trigger("click");

    expect(filterByScope).toHaveBeenCalled();
    expect(filterBy).not.toHaveBeenCalled();
    expect(filterByReadiness).not.toHaveBeenCalled();
  });

  it("zaehlt am Umfangs-Filter und markiert ihn fuer Screenreader", () => {
    const counted = mountList([
      { ...entry, oversized: true },
      { ...entry, contact_id: "k2", oversized: true },
      { ...entry, contact_id: "k3" },
    ]);

    expect(counted.wrapper.find("[data-scope-filter]").text()).toContain("2");
    expect(counted.wrapper.find("[data-scope-filter]").attributes("aria-pressed")).toBe("false");

    const active = mountList([], undefined, { oversizedFilter: true });

    expect(active.wrapper.find("[data-scope-filter]").attributes("aria-pressed")).toBe("true");
  });

  it("kopiert alles ueber den Betrieb als Text", async () => {
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.defineProperty(navigator, "clipboard", { value: { writeText }, configurable: true });

    const { wrapper } = mountList();
    await wrapper.find("li [data-copy]").trigger("click");

    const text = writeText.mock.calls[0]?.[0] as string;

    // Stammdaten, Versandstand und die freien Spalten der Analyse – der Text
    // soll ohne die Anwendung daneben lesbar sein.
    expect(text).toContain("Betrieb: Azmanlar Tayfun Malermeister");
    expect(text).toContain("Telefon: +49 5224 79473");
    expect(text).toContain("Adresse: 32052 Herford");
    expect(text).toContain("Prio: A");
    expect(text).toContain("Versandstand: Mail noch nicht versendet");
    expect(text).toContain("Befunde:\nSeite lädt langsam");
    expect(text).toContain("Anmerkung aus dem Telefonat:\nwill Preise sehen");
    expect(text).toContain("Details aus der Liste:\n- Ladezeit: 4,2 s");

    // Leere Felder stehen nicht drin: „Website: “ waere im Prompt eine
    // Behauptung ueber einen Betrieb, ueber den wir nichts wissen.
    expect(text).not.toContain("Website:");
    expect(text).not.toContain("Antwort am:");
    // Und ein Marker, den niemand gesetzt hat, ist keine Aussage.
    expect(text).not.toContain("Bau-Einschätzung:");
    expect(text).not.toContain("Umfang:");
  });

  it("meldet das Kopieren am Knopf zurueck", async () => {
    Object.defineProperty(navigator, "clipboard", {
      value: { writeText: vi.fn().mockResolvedValue(undefined) },
      configurable: true,
    });

    const { wrapper } = mountList([entry, { ...entry, contact_id: "k2" }]);
    const copyButtons = () => wrapper.findAll("li [data-copy]").map((button) => button.text());

    expect(copyButtons()).toEqual(["content_copy Kopieren", "content_copy Kopieren"]);

    await wrapper.find("li [data-copy]").trigger("click");
    await wrapper.vm.$nextTick();

    // Nur die angeklickte Zeile bestaetigt – sonst sieht es aus, als haenge
    // die Zwischenablage an der Liste und nicht an diesem Betrieb.
    expect(copyButtons()).toEqual(["check Kopiert", "content_copy Kopieren"]);
  });

  it("laesst die Einschaetzung auch ohne E-Mail-Adresse zu", () => {
    // Ob eine Website Inhalt hat, ist von der Adresse unabhaengig – und
    // ausgerechnet diese Zeile will man einschaetzen koennen.
    const { wrapper } = mountList([{ ...entry, contact_id: "k2", email: "", actions: [] }]);

    expect(wrapper.find("li [data-marker='ready_to_build']").exists()).toBe(true);
  });
});
