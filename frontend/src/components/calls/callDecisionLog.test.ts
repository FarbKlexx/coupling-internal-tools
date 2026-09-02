/**
 * Die Liste der zuletzt eingetragenen Entscheidungen.
 *
 * Drei Dinge sind hier eigene Logik und nicht bloß Anzeige: dass nur die
 * änderbaren Zeilen einen Knopf bekommen (und die übrigen den Grund als
 * Hinweis statt gar nichts), dass eine Richtigstellung Anmerkung und Adresse
 * mitschickt, und dass auch beim Korrigieren erst nach dem Zeitpunkt gefragt
 * wird — sonst läge der Betrieb danach ohne Wiedervorlage da.
 */
import { describe, expect, it } from "vitest";
import { mount } from "@vue/test-utils";
import CallDecisionLog from "./CallDecisionLog.vue";
import type { CallDecision, CallDecisionPage, OutcomeInfo } from "@/api/call_list.api";

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
];

const decision: CallDecision = {
  event_id: 7,
  contact_id: "k1",
  occurred_at: "2026-09-01T09:00:00Z",
  username: "anruferin",
  outcome: "abgelehnt",
  outcome_label: "Nein – ausdrücklich keine Mails",
  betrieb: "Azmanlar Tayfun Malermeister",
  telefon: "+49 5224 79473",
  list_name: "Handwerker Herford",
  note: "war der falsche Knopf",
  email: "info@tayfun-design.de",
  due_at: null,
  appointment_at: null,
  state: "abgelehnt",
  state_label: "abgelehnt",
  corrects_event_id: null,
  corrected: false,
  correctable: true,
  locked_reason: "",
};

function page(...entries: CallDecision[]): CallDecisionPage {
  return { entries, total: entries.length, offset: 0, limit: 20 };
}

function mountLog(...entries: CallDecision[]) {
  return mount(CallDecisionLog, {
    props: {
      page: page(...(entries.length ? entries : [decision])),
      outcomes,
      isLoading: false,
      isSaving: false,
      loadMore: () => {},
    },
  });
}

describe("CallDecisionLog", () => {
  it("zeigt die Eintragung mit Betrieb, Ergebnis und Konto", () => {
    const wrapper = mountLog();

    expect(wrapper.text()).toContain("Azmanlar Tayfun Malermeister");
    expect(wrapper.text()).toContain("Nein – ausdrücklich keine Mails");
    expect(wrapper.text()).toContain("anruferin");
    expect(wrapper.text()).toContain("war der falsche Knopf");
  });

  it("nennt bei einer gesperrten Zeile den Grund, statt den Knopf wegzulassen", () => {
    const wrapper = mountLog({
      ...decision,
      correctable: false,
      corrected: true,
      locked_reason: "Zu diesem Betrieb gibt es eine neuere Eintragung.",
    });

    expect(wrapper.find("button").exists()).toBe(false);
    expect(wrapper.get("span[title]").attributes("title")).toContain("neuere Eintragung");
  });

  it("schickt beim Richtigstellen Anmerkung und Adresse mit", async () => {
    const wrapper = mountLog();

    await wrapper.get("button").trigger("click");
    await wrapper.get("input[type='text']").setValue("doch zugesagt");
    await wrapper.get("button.outcome").trigger("click");

    expect(wrapper.emitted("correct")?.[0]).toEqual([
      7,
      {
        outcome: "zugesagt",
        note: "doch zugesagt",
        // Immer mitgeschickt: hier steht die Adresse der Zeile im Feld, und
        // wer sie leert, meint „streichen".
        email: "info@tayfun-design.de",
      },
    ]);
  });

  it("fragt auch beim Richtigstellen erst nach dem Zeitpunkt", async () => {
    const wrapper = mountLog();

    await wrapper.get("button").trigger("click");
    await wrapper.findAll("button.outcome")[1]!.trigger("click");

    // Noch nichts abgeschickt — sonst läge der Betrieb ohne Wiedervorlage da.
    expect(wrapper.emitted("correct")).toBeUndefined();
    expect(wrapper.text()).toContain("Wann erneut anrufen?");

    // „sofort wieder" gibt es nur hier: einen versehentlich abgeräumten
    // Betrieb einfach zurück in die Liste holen.
    const chips = wrapper.findAll("button.chip").map((chip) => chip.text());
    expect(chips[0]).toBe("sofort wieder");

    await wrapper.findAll("button.chip")[1]!.trigger("click");

    const payload = wrapper.emitted("correct")?.[0]?.[1] as Record<string, unknown>;
    expect(payload.outcome).toBe("nicht_erreichbar");
    expect(payload.snooze_minutes).toBe(60);
  });

  it("schließt den Kasten, sobald die Zeile nicht mehr änderbar ist", async () => {
    const wrapper = mountLog();

    await wrapper.get("button").trigger("click");
    expect(wrapper.find("button.outcome").exists()).toBe(true);

    // So kommt die Zeile nach einer erfolgreichen Korrektur zurück: die
    // Korrektur ist jetzt die jüngste Eintragung.
    await wrapper.setProps({
      page: page({ ...decision, correctable: false, corrected: true }),
    });

    expect(wrapper.find("button.outcome").exists()).toBe(false);
  });
});
