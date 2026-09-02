/**
 * Der Arbeitsplatz des Anrufers.
 *
 * Zwei Dinge sind hier eigene Logik und nicht bloß Anzeige: dass ein Ergebnis
 * mit Zeitbedarf **nicht** sofort abgeschickt wird (sonst landet „nicht
 * erreichbar" ohne Wiedervorlage im Protokoll), und dass die Eingaben beim
 * Wechsel des Kontakts geleert werden (sonst wandert die Anmerkung des vorigen
 * Gesprächs zum nächsten Betrieb). Beides ohne Netzwerk geprüft.
 */
import { describe, expect, it } from "vitest";
import { mount } from "@vue/test-utils";
import CallWorkbench from "./CallWorkbench.vue";
import type { CallContact, CallCounters, OutcomeInfo } from "@/api/call_list.api";

const counters: CallCounters = {
  gesamt: 3,
  offen: 3,
  wiedervorlage: 0,
  zugesagt: 0,
  kein_bedarf: 0,
  abgelehnt: 0,
  ungueltig: 0,
  zugesagt_ohne_email: 0,
};

/** Wie sie das Backend liefert – gekürzt auf das, was hier geprüft wird. */
const outcomes: OutcomeInfo[] = [
  {
    id: "zugesagt",
    label: "Zusage – E-Mail erlaubt",
    description: "Hat am Telefon zugestimmt.",
    tone: "positive",
    time_input: "none",
    resulting_state: "zugesagt",
  },
  {
    id: "nicht_erreichbar",
    label: "Nicht erreichbar",
    description: "Kommt später zurück.",
    tone: "neutral",
    time_input: "snooze",
    resulting_state: "wiedervorlage",
  },
  {
    id: "rueckruf",
    label: "Rückruf vereinbart",
    description: "Termin abgesprochen.",
    tone: "neutral",
    time_input: "appointment",
    resulting_state: "rueckruf",
  },
];

const contact: CallContact = {
  id: "k1",
  list_id: "l1",
  list_name: "Handwerker Herford",
  betrieb: "Azmanlar Tayfun Malermeister",
  telefon: "+49 5224 79473",
  email: "info@tayfun-design.de",
  ort: "Enger",
  plz: "32130",
  website: "http://tayfun-design.de/",
  gewerk: "Maler",
  prio: "A - dringend",
  befunde: "kein HTTPS +3 | Copyright 2010 +3",
  extras: [
    { label: "Punkte", value: "11" },
    { label: "CMS", value: "WordPress 5.8" },
  ],
  state: "offen",
  state_label: "offen",
  attempts: 0,
  due_at: null,
  appointment_at: null,
  note: "",
  history: [],
};

function mountWorkbench(overrides: Partial<CallContact> | null = {}) {
  return mount(CallWorkbench, {
    props: {
      contact: overrides === null ? null : { ...contact, ...overrides },
      counters,
      outcomes,
      nextDueAt: null,
      hasLists: true,
      isSaving: false,
      isWaiting: false,
      isDone: false,
    },
  });
}

describe("CallWorkbench", () => {
  it("zeigt den Kontakt mit Nummer, Aufhänger und Zähler", () => {
    const wrapper = mountWorkbench();

    expect(wrapper.text()).toContain("Azmanlar Tayfun Malermeister");
    expect(wrapper.text()).toContain("+49 5224 79473");
    expect(wrapper.text()).toContain("kein HTTPS");
    expect(wrapper.text()).toContain("Handwerker Herford");
    // Die Nummer ist wählbar, nicht nur lesbar — Leerzeichen fallen dabei weg.
    expect(wrapper.get("a[href^='tel:']").attributes("href")).toBe("tel:+49522479473");
  });

  it("baut die Ergebnisknöpfe aus der Antwort des Backends", () => {
    const wrapper = mountWorkbench();
    const labels = wrapper.findAll("button.outcome").map((button) => button.text());

    expect(labels).toHaveLength(3);
    expect(labels[0]).toContain("Zusage");
    expect(wrapper.get("button.outcome").classes()).toContain("outcome--positive");
  });

  it("schickt ein Ergebnis ohne Zeitbedarf sofort ab", async () => {
    const wrapper = mountWorkbench();

    await wrapper.get("button.outcome").trigger("click");

    const answered = wrapper.emitted("answer");
    expect(answered).toHaveLength(1);
    expect(answered?.[0]?.[0]).toBe("k1");
    expect(answered?.[0]?.[1]).toEqual({ outcome: "zugesagt", note: "" });
  });

  it("fragt bei „nicht erreichbar“ erst nach dem Zeitpunkt", async () => {
    const wrapper = mountWorkbench();
    const buttons = wrapper.findAll("button.outcome");

    await buttons[1]!.trigger("click");

    // Noch nichts abgeschickt — sonst läge der Kontakt ohne Wiedervorlage.
    expect(wrapper.emitted("answer")).toBeUndefined();
    expect(wrapper.text()).toContain("Wann erneut anrufen?");

    const chips = wrapper.findAll("button.chip");
    expect(chips.map((chip) => chip.text())).toEqual([
      "in 1 Stunde",
      "in 2 Stunden",
      "morgen früh",
    ]);

    await chips[1]!.trigger("click");

    expect(wrapper.emitted("answer")?.[0]?.[1]).toEqual({
      outcome: "nicht_erreichbar",
      snooze_minutes: 120,
      note: "",
    });
  });

  it("schickt beim Rückruf einen Termin mit Zeitzone", async () => {
    const wrapper = mountWorkbench();

    await wrapper.findAll("button.outcome")[2]!.trigger("click");
    expect(wrapper.text()).toContain("Wann ist der Rückruf verabredet?");

    await wrapper.get("input[type='datetime-local']").setValue("2026-09-01T14:00");

    const apply = wrapper.findAll("button").find((button) => button.text() === "Übernehmen");
    await apply!.trigger("click");

    // Der Browser liest das Feld als Ortszeit; abgeschickt wird UTC.
    const payload = wrapper.emitted("answer")?.[0]?.[1] as Record<string, string>;
    expect(payload.outcome).toBe("rueckruf");
    expect(payload.appointment_at).toMatch(/^2026-09-01T\d{2}:00:00\.000Z$/);
    expect(payload.due_at).toBeUndefined();
  });

  it("schickt die Adresse nur mit, wenn sie geändert wurde", async () => {
    const wrapper = mountWorkbench();

    await wrapper.get("input[type='email']").setValue("neu@tayfun-design.de");
    await wrapper.get("button.outcome").trigger("click");

    expect(wrapper.emitted("answer")?.[0]?.[1]).toEqual({
      outcome: "zugesagt",
      note: "",
      email: "neu@tayfun-design.de",
    });
  });

  it("leert die Eingaben beim Wechsel des Kontakts", async () => {
    const wrapper = mountWorkbench();

    await wrapper.get("textarea").setValue("Ruft nachher zurück");
    await wrapper.setProps({ contact: { ...contact, id: "k2", email: "" } });

    expect((wrapper.get("textarea").element as HTMLTextAreaElement).value).toBe("");
    expect((wrapper.get("input[type='email']").element as HTMLInputElement).value).toBe("");
  });

  it("unterscheidet „keine Liste“ von „alles auf Wiedervorlage“", () => {
    const withoutLists = mount(CallWorkbench, {
      props: {
        contact: null,
        counters: { ...counters, gesamt: 0, offen: 0 },
        outcomes,
        nextDueAt: null,
        hasLists: false,
        isSaving: false,
        isWaiting: false,
        isDone: false,
      },
    });

    expect(withoutLists.text()).toContain("Noch keine Anrufliste hinterlegt");

    const waiting = mount(CallWorkbench, {
      props: {
        contact: null,
        counters: { ...counters, offen: 0, wiedervorlage: 3 },
        outcomes,
        nextDueAt: "2026-09-01T12:00:00Z",
        hasLists: true,
        isSaving: false,
        isWaiting: true,
        isDone: false,
      },
    });

    expect(waiting.text()).toContain("Gerade nichts zu tun");
  });
});
