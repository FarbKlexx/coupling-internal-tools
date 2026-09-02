/**
 * Die Ergebnis-IDs der Telefonakquise existieren an zwei Stellen: dem
 * `CallOutcome`-Enum im Backend (dort wird validiert, gespeichert und
 * protokolliert) und `CALL_OUTCOMES` hier im Frontend, wo jeder ID ein Symbol
 * zugeordnet ist.
 *
 * Beschriftung, Beschreibung und Tonlage der Knöpfe kommen dagegen *als Daten*
 * mit der Antwort und sind hier bewusst nicht gespiegelt — ein sechstes
 * Ergebnis ist eine Änderung an einer Python-Datei. Was dabei trotzdem drüben
 * nachgetragen werden muss, ist genau das Symbol, und genau das prüft dieser
 * Test: eine ID ohne Symbol ist im Knopf ein leeres Kästchen, und das fällt
 * sonst erst dem auf, der telefoniert.
 *
 * Nach dem Muster von `labelPalette.test.ts` und `pageIds.test.ts`.
 */
import { existsSync, readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";
import { CALL_OUTCOMES } from "./call_list.api";

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

const SCHEMA = "../../../backend/app/schemas/call_list.py";

function backendOutcomes(): string[] {
  const source = read(SCHEMA);
  const enumBody = source.match(/class CallOutcome\(str, Enum\):([\s\S]*?)\n\n\n/)?.[1];

  expect(enumBody, "CallOutcome-Enum im Backend nicht gefunden").toBeTruthy();

  return [...(enumBody ?? "").matchAll(/^\s+[A-Z_]+ = "([a-z_]+)"$/gm)].flatMap((match) =>
    match[1] ? [match[1]] : [],
  );
}

/** Die IDs, für die `OutcomeChooser.vue` ein Symbol kennt. */
function iconIds(): string[] {
  const source = read("../components/calls/OutcomeChooser.vue");
  const block = source.match(/const ICONS: Record<CallOutcome, string> = \{([\s\S]*?)\};/)?.[1];

  expect(block, "ICONS-Zuordnung in OutcomeChooser.vue nicht gefunden").toBeTruthy();

  return [...(block ?? "").matchAll(/^\s+([a-z_]+):\s*"/gm)].flatMap((match) =>
    match[1] ? [match[1]] : [],
  );
}

describe("Anruf-Ergebnisse", () => {
  it("stimmen zwischen Backend und Frontend ueberein", () => {
    // Reihenfolge egal: die Reihenfolge der Knoepfe bestimmt `OUTCOMES` im
    // Backend und kommt mit der Antwort, nicht aus dieser Liste.
    expect([...CALL_OUTCOMES].sort()).toEqual(backendOutcomes().sort());
  });

  it("haben jeweils ein Symbol in der Oberflaeche", () => {
    expect(iconIds().sort()).toEqual([...CALL_OUTCOMES].sort());
  });

  it("tauchen alle in der Knopfliste des Backends auf", () => {
    // `OUTCOMES` ist, was der Anrufer sieht. Ein Ergebnis, das im Enum steht
    // und dort fehlt, waere ein Zustand, den niemand erreichen kann.
    const source = read(SCHEMA);
    const buttons = source.match(/OUTCOMES: tuple\[OutcomeInfo, \.\.\.\] = \(([\s\S]*?)\n\)/)?.[1];

    expect(buttons, "OUTCOMES-Liste im Backend nicht gefunden").toBeTruthy();

    for (const outcome of CALL_OUTCOMES) {
      const member = outcome.toUpperCase();
      expect(buttons, `CallOutcome.${member} fehlt in OUTCOMES`).toContain(`CallOutcome.${member}`);
    }
  });
});
