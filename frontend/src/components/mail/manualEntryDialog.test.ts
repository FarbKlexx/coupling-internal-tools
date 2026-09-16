/**
 * Das Formular für einen von Hand erfassten Betrieb.
 *
 * Geprueft wird, was die Oberflaeche entscheidet — nicht, was das Backend
 * prueft: dass Pflichtfelder den Knopf sperren, dass das Aendern mit den
 * Werten der Zeile beginnt, und dass der Befund zu einer schon bekannten
 * Nummer seinen eigenen Weg hat („trotzdem anlegen" schickt `force`).
 *
 * `v-overlay` wird gestubbt: Vuetify ist in dieser Anwendung global
 * registriert, im Test aber nicht — und der Dialog haengt an seinem Inhalt,
 * nicht an der Huelle.
 */
import { mount } from "@vue/test-utils";
import { describe, expect, it } from "vitest";
import ManualEntryDialog from "./ManualEntryDialog.vue";
import type { MailEntry, ManualEntry } from "@/api/mail_followup.api";

const overlayStub = {
  "v-overlay": { template: "<div><slot /></div>" },
};

const entry: MailEntry = {
  contact_id: "k9",
  betrieb: "Dachdecker Wolff",
  telefon: "05221 999",
  email: "info@wolff-dach.de",
  ort: "Bünde",
  plz: "32257",
  website: "wolff-dach.de",
  gewerk: "Dachdecker",
  prio: "",
  befunde: "",
  extras: [],
  list_id: "manuell",
  list_name: "Manuell erfasst",
  list_archived: false,
  manual: true,
  promised_at: "2026-09-16T09:00:00Z",
  promised_by: "chefin",
  note: "Messe Hannover",
  state: "offen",
  state_label: "Mail noch nicht versendet",
  readiness: "unbewertet",
  readiness_label: "noch nicht eingeschätzt",
  readiness_actions: [],
  oversized: false,
  automatic: false,
  sent_at: null,
  answered_at: null,
  followed_up_at: null,
  days_since_sent: null,
  mail_note: "",
  updated_at: null,
  updated_by: "",
  actions: ["versendet"],
};

function mountDialog(props: Partial<InstanceType<typeof ManualEntryDialog>["$props"]> = {}) {
  return mount(ManualEntryDialog, {
    props: {
      entry: null,
      isBusy: false,
      conflict: null,
      errorMessage: null,
      ...props,
    },
    global: { stubs: overlayStub },
  });
}

/** Der zuletzt abgeschickte Eintrag. */
function submitted(wrapper: ReturnType<typeof mountDialog>): ManualEntry | undefined {
  const events = wrapper.emitted("submit");
  return events?.[events.length - 1]?.[0] as ManualEntry | undefined;
}

describe("ManualEntryDialog", () => {
  it("laesst sich ohne Betrieb und Adresse nicht abschicken", async () => {
    // Die Zeile existiert, damit eine Mail hinausgeht – ohne Adresse waere
    // sie sofort die Nacharbeit, die das Werkzeug sichtbar machen soll.
    const wrapper = mountDialog();
    const submit = wrapper.find("[data-submit]");

    expect(submit.attributes("disabled")).toBeDefined();

    await wrapper.findAll("input")[0]?.setValue("Dachdecker Wolff");

    expect(submit.attributes("disabled")).toBeDefined();

    await wrapper.findAll("input")[1]?.setValue("info@wolff-dach.de");

    expect(submit.attributes("disabled")).toBeUndefined();
  });

  it("schickt die eingegebenen Felder, ohne zu forcieren", async () => {
    const wrapper = mountDialog();
    const inputs = wrapper.findAll("input");

    await inputs[0]?.setValue("Dachdecker Wolff");
    await inputs[1]?.setValue("info@wolff-dach.de");
    await inputs[2]?.setValue("05221 999");
    await wrapper.find("textarea").setValue("Messe Hannover");
    await wrapper.find("[data-submit]").trigger("click");

    expect(submitted(wrapper)).toMatchObject({
      betrieb: "Dachdecker Wolff",
      email: "info@wolff-dach.de",
      telefon: "05221 999",
      note: "Messe Hannover",
      force: false,
    });
  });

  it("beginnt beim Aendern mit den Werten der Zeile", () => {
    const wrapper = mountDialog({ entry });
    const values = wrapper.findAll("input").map((input) => input.element.value);

    expect(values).toContain("Dachdecker Wolff");
    expect(values).toContain("info@wolff-dach.de");
    expect(wrapper.find("textarea").element.value).toBe("Messe Hannover");
    // Und der Knopf sagt, was passiert – „Anlegen" waere hier gelogen.
    expect(wrapper.find("[data-submit]").text()).toBe("Speichern");
  });

  it("bietet zur schon bekannten Nummer den ausdruecklichen Weg an", async () => {
    // Erst der Befund, wo die Nummer steht, dann die Bestaetigung: dasselbe
    // Verfahren wie beim Loeschen einer Liste mit Protokoll.
    const wrapper = mountDialog({
      entry,
      conflict: "Dachdecker Wolff: die Nummer steht bereits in der Liste „Herford“.",
    });

    expect(wrapper.text()).toContain("steht bereits in der Liste");

    await wrapper.find("[data-force]").trigger("click");

    expect(submitted(wrapper)?.force).toBe(true);
  });

  it("zeigt eine gewoehnliche Fehlermeldung ohne diesen Knopf", () => {
    // Ein Tippfehler in der Adresse ist kein Befund, den man uebergehen darf.
    const wrapper = mountDialog({ errorMessage: "„keine-adresse“ sieht nicht wie eine aus." });

    expect(wrapper.text()).toContain("sieht nicht wie eine aus");
    expect(wrapper.find("[data-force]").exists()).toBe(false);
  });
});
