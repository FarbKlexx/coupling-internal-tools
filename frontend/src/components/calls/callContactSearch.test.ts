/**
 * Die Kontaktsuche unter dem Arbeitsplatz.
 *
 * Drei Dinge sind hier eigene Logik und nicht bloß Anzeige: dass jede Eingabe
 * bei der Suche des Composables landet (die Verzögerung liegt dort, nicht
 * hier), dass eine beendete Liste als solche zu erkennen ist — sonst liest man
 * einen Zustand als aktuellen Arbeitsvorrat — und dass das Protokoll eines
 * Treffers aufklappbar ist, weil es die eigentliche Antwort auf „was war da?"
 * enthält.
 */
import { describe, expect, it, vi } from "vitest";
import { mount } from "@vue/test-utils";
import CallContactSearch from "./CallContactSearch.vue";
import type { CallContact, CallContactPage } from "@/api/call_list.api";

function contact(overrides: Partial<CallContact> = {}): CallContact {
  return {
    id: "k1",
    list_id: "l1",
    list_name: "Handwerker Herford",
    list_archived: false,
    betrieb: "Klappschmidt Zaunbau",
    telefon: "05221 111",
    email: "",
    ort: "Herford",
    plz: "32049",
    website: "",
    gewerk: "Zaunbau",
    prio: "A",
    befunde: "",
    extras: [],
    state: "wiedervorlage",
    state_label: "Wiedervorlage",
    attempts: 2,
    due_at: "2026-09-02T07:00:00Z",
    appointment_at: null,
    note: "Erste Zeile\nZweite Zeile",
    history: [
      {
        occurred_at: "2026-09-01T09:00:00Z",
        username: "anruferin",
        outcome: "ap_nicht_da",
        outcome_label: "Ansprechpartner nicht da",
        note: "Chef ist ab Montag wieder da",
        email: "",
        appointment_at: null,
        due_at: "2026-09-02T07:00:00Z",
      },
    ],
    ...overrides,
  };
}

function page(overrides: Partial<CallContactPage> = {}): CallContactPage {
  return {
    entries: [contact()],
    matched: 1,
    offset: 0,
    limit: 10,
    query: "klappschmidt",
    ...overrides,
  };
}

function mountSearch(props: Partial<Record<string, unknown>> = {}) {
  return mount(CallContactSearch, {
    props: {
      page: page(),
      isSearching: false,
      search: vi.fn(),
      goToPage: vi.fn(),
      ...props,
    },
  });
}

describe("Kontaktsuche", () => {
  it("gibt jede Eingabe an die Suche weiter", async () => {
    const search = vi.fn();
    const wrapper = mountSearch({ page: null, search });

    await wrapper.get("input[type='search']").setValue("klappschmidt");

    expect(search).toHaveBeenCalledWith("klappschmidt");
  });

  it("zeigt Zustand, Liste und Versuche eines Treffers", () => {
    const text = mountSearch().text();

    expect(text).toContain("Klappschmidt Zaunbau");
    expect(text).toContain("Wiedervorlage");
    expect(text).toContain("Handwerker Herford");
    expect(text).toContain("2 Versuche");
    // Die Nummer ist wählbar, nicht nur lesbar.
    expect(mountSearch().get("a[href^='tel:']").attributes("href")).toBe("tel:05221111");
  });

  it("kennzeichnet eine beendete Liste", () => {
    // Ohne den Hinweis liest sich der Zustand wie aktueller Arbeitsvorrat,
    // obwohl der Betrieb in keiner laufenden Liste mehr steht.
    const wrapper = mountSearch({
      page: page({ entries: [contact({ list_archived: true })] }),
    });

    expect(wrapper.text()).toContain("(archiviert)");
  });

  it("klappt das Protokoll eines Treffers auf", async () => {
    const wrapper = mountSearch();

    expect(wrapper.text()).not.toContain("Chef ist ab Montag wieder da");

    await wrapper.get("button[aria-expanded]").trigger("click");

    expect(wrapper.text()).toContain("Ansprechpartner nicht da");
    expect(wrapper.text()).toContain("Chef ist ab Montag wieder da");
  });

  it("sagt beim Fehlschlag, wonach gesucht wurde", () => {
    const wrapper = mountSearch({ page: page({ entries: [], matched: 0, query: "meier" }) });

    expect(wrapper.text()).toContain("Kein Betrieb passt zu „meier“");
  });

  it("blättert nur, wenn es mehr Treffer als eine Seite gibt", async () => {
    const goToPage = vi.fn();
    const single = mountSearch({ goToPage });

    expect(single.text()).not.toContain("weiter");

    const many = mountSearch({
      page: page({ matched: 25, limit: 10, offset: 10 }),
      goToPage,
    });
    const next = many.findAll("button").find((button) => button.text() === "weiter");
    await next!.trigger("click");

    expect(goToPage).toHaveBeenCalledWith(20);
  });
});
