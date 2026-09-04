/**
 * Die Zustands-IDs des Mailversands existieren an zwei Stellen: dem
 * `MailState`-Enum im Backend (dort wird validiert und gespeichert) und
 * `MAIL_STATES` hier im Frontend, wo jeder ID ein Symbol zugeordnet ist.
 *
 * Beschriftung, Beschreibung und Tonlage der Knöpfe kommen dagegen *als Daten*
 * mit der Antwort und sind hier bewusst nicht gespiegelt – ein sechster
 * Zustand ist eine Änderung an einer Python-Datei. Was drüben trotzdem
 * nachgetragen werden muss, ist genau das Symbol, und genau das prüft dieser
 * Test.
 *
 * Nach dem Muster von `callOutcomes.test.ts` und `pageIds.test.ts`.
 */
import { existsSync, readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";
import { MAIL_STATES } from "./mail_followup.api";

/**
 * Liest eine Datei relativ zu diesem Test.
 *
 * Setzt das Repo-Layout voraus (`backend/` und `frontend/` als Geschwister) –
 * in CI nach `actions/checkout` gegeben.
 */
function read(relative: string): string {
  const path = fileURLToPath(new URL(relative, import.meta.url));

  if (!existsSync(path)) {
    throw new Error(
      `${path} nicht gefunden – dieser Test braucht das vollständige Repo ` +
        `(backend/ neben frontend/), nicht nur den frontend-Ordner.`,
    );
  }

  return readFileSync(path, "utf8");
}

const SCHEMA = "../../../backend/app/schemas/mail_followup.py";

function backendStates(): string[] {
  const source = read(SCHEMA);
  const enumBody = source.match(/class MailState\(str, Enum\):([\s\S]*?)\n\n\n/)?.[1];

  expect(enumBody, "MailState-Enum im Backend nicht gefunden").toBeTruthy();

  return [...(enumBody ?? "").matchAll(/^\s+[A-Z_]+ = "([a-z_]+)"$/gm)].flatMap((match) =>
    match[1] ? [match[1]] : [],
  );
}

/** Die IDs, für die `MailFollowupList.vue` ein Symbol kennt. */
function iconIds(): string[] {
  const source = read("../components/mail/MailFollowupList.vue");
  const block = source.match(/const ICONS: Record<MailState, string> = \{([\s\S]*?)\};/)?.[1];

  expect(block, "ICONS-Zuordnung in MailFollowupList.vue nicht gefunden").toBeTruthy();

  return [...(block ?? "").matchAll(/^\s+([a-z_]+):\s*"/gm)].flatMap((match) =>
    match[1] ? [match[1]] : [],
  );
}

describe("Versand-Zustaende", () => {
  it("stimmen zwischen Backend und Frontend ueberein", () => {
    // Reihenfolge egal: welcher Knopf an welcher Zeile steht, entscheidet
    // `MAIL_TRANSITIONS` im Backend und kommt mit der Antwort.
    expect([...MAIL_STATES].sort()).toEqual(backendStates().sort());
  });

  it("haben jeweils ein Symbol in der Oberflaeche", () => {
    expect(iconIds().sort()).toEqual([...MAIL_STATES].sort());
  });

  it("sind alle aus irgendeinem Zustand erreichbar", () => {
    // Ein Zustand, in den kein Uebergang fuehrt, waere ein Knopf, den niemand
    // druecken kann – die Uebergangstabelle steht im Backend, geprueft wird
    // sie dort auch (test_mail_followup.py). Hier reicht die ID-Ebene: jede
    // ID muss in der Tabelle ueberhaupt vorkommen.
    const source = read(SCHEMA);
    const table = source.match(
      /MAIL_TRANSITIONS: dict\[MailState, tuple\[MailState, \.\.\.\]\] = \{([\s\S]*?)\n\}/,
    )?.[1];

    expect(table, "MAIL_TRANSITIONS im Backend nicht gefunden").toBeTruthy();

    for (const state of MAIL_STATES) {
      const member = state.toUpperCase();
      expect(table, `MailState.${member} fehlt in MAIL_TRANSITIONS`).toContain(
        `MailState.${member}`,
      );
    }
  });
});
