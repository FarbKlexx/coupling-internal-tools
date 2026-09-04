/**
 * Die Versandliste.
 *
 * Drei Dinge sind hier eigene Logik und nicht bloß Anzeige: dass eine Zeile
 * genau die Knöpfe zeigt, die das Backend ihr mitgibt (und keine, die es
 * ablehnen würde), dass eine Anmerkung *ohne* Zustand abgeschickt wird, und
 * dass eine Zusage ohne Adresse als solche kenntlich ist statt still zu
 * verschwinden.
 */
import { describe, expect, it, vi } from "vitest";
import { mount } from "@vue/test-utils";
import MailFollowupList from "./MailFollowupList.vue";
import type { MailActionInfo, MailBoard, MailEntry } from "@/api/mail_followup.api";

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

const entry: MailEntry = {
  contact_id: "k1",
  betrieb: "Azmanlar Tayfun Malermeister",
  telefon: "+49 5224 79473",
  email: "info@tayfun-design.de",
  ort: "Herford",
  plz: "32052",
  website: "",
  gewerk: "Maler",
  list_id: "l1",
  list_name: "Handwerker Herford",
  list_archived: false,
  promised_at: "2026-09-01T09:00:00Z",
  promised_by: "anruferin",
  note: "will Preise sehen",
  state: "offen",
  state_label: "Mail noch nicht versendet",
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
    },
    entries: rows,
    total: rows.length,
    matched: rows.length,
    offset: 0,
    limit: 50,
    actions,
    timeout_days: 30,
  };
}

function mountList(entries: MailEntry[] = [], save = vi.fn().mockResolvedValue(true)) {
  const wrapper = mount(MailFollowupList, {
    props: {
      board: board(...entries),
      actions,
      timeoutDays: 30,
      isLoading: false,
      isSaving: false,
      filterBy: vi.fn(),
      goToPage: vi.fn(),
      save,
      query: "",
      stateFilter: null,
    },
  });

  return { wrapper, save };
}

/** Die Knöpfe *einer* Zeile, ohne Zähler-Kacheln und Werkzeugleiste. */
function rowButtons(wrapper: ReturnType<typeof mount>) {
  return wrapper.findAll("li button").map((button) => button.text());
}

describe("MailFollowupList", () => {
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

    await wrapper.findAll("li button")[0]?.trigger("click");

    expect(save).toHaveBeenCalledWith("k1", { state: "versendet" });
  });

  it("schickt eine Anmerkung ohne Zustand", async () => {
    // Notiert wird, waehrend eine Zeile wartet – ein Zustand im selben Aufruf
    // wuerde eine abgelaufene Frist als Entscheidung festschreiben.
    const { wrapper, save } = mountList();

    const noteButton = wrapper.findAll("li button").find((b) => b.text().includes("Anmerkung"));
    await noteButton?.trigger("click");
    await wrapper.find("li input[type='text']").setValue("Angebot mit Preisliste");
    const submit = wrapper.findAll("li button").find((b) => b.text() === "Speichern");
    await submit?.trigger("click");

    expect(save).toHaveBeenCalledWith("k1", { note: "Angebot mit Preisliste" });
  });

  it("macht eine Zusage ohne Adresse kenntlich, statt sie zu verschweigen", () => {
    const { wrapper } = mountList([{ ...entry, contact_id: "k2", email: "", actions: [] }]);

    expect(wrapper.text()).toContain("keine E-Mail-Adresse");
    expect(rowButtons(wrapper).some((text) => text.includes("Mail versendet"))).toBe(false);
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
        timeoutDays: 30,
        isLoading: false,
        isSaving: false,
        filterBy: vi.fn(),
        goToPage: vi.fn(),
        save: vi.fn(),
        query: "",
        stateFilter: null,
      },
    });

    expect(wrapper.text()).toContain("Telefonakquise");
  });
});
