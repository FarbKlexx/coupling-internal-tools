/**
 * Der Mailversand hat zwei Vokabulare, die je zweimal existieren: den
 * Versandstand (`MailState` / `MAIL_STATES`) und die Bau-Einschätzung
 * (`BuildReadiness` / `BUILD_READINESS`). Validiert und gespeichert wird im
 * Backend, im Frontend hängt an jeder ID die Darstellung.
 *
 * Beschriftung, Beschreibung und Tonlage der Knöpfe kommen dagegen *als Daten*
 * mit der Antwort und sind hier bewusst nicht gespiegelt – ein sechster
 * Zustand ist eine Änderung an einer Python-Datei. Was drüben trotzdem
 * nachgetragen werden muss, sind Symbol und Farbe, und genau das prüft dieser
 * Test.
 *
 * Nach dem Muster von `callOutcomes.test.ts` und `pageIds.test.ts`.
 */
import { existsSync, readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";
import { BUILD_READINESS, MAIL_STATES } from "./mail_followup.api";

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

function backendReadiness(): string[] {
  const source = read(SCHEMA);
  const enumBody = source.match(/class BuildReadiness\(str, Enum\):([\s\S]*?)\n\n\n/)?.[1];

  expect(enumBody, "BuildReadiness-Enum im Backend nicht gefunden").toBeTruthy();

  return [...(enumBody ?? "").matchAll(/^\s+[A-Z_]+ = "([a-z_]+)"$/gm)].flatMap((match) =>
    match[1] ? [match[1]] : [],
  );
}

/** Die Einschätzungen, für die die Oberfläche Symbol und Farbe kennt. */
function readinessStyleIds(): string[] {
  const source = read("../components/mail/MailFollowupList.vue");
  const block = source.match(
    /const READINESS: Record<\n?\s*BuildReadiness,[\s\S]*?\n> = \{([\s\S]*?)\n\};/,
  )?.[1];

  expect(block, "READINESS-Zuordnung in MailFollowupList.vue nicht gefunden").toBeTruthy();

  return [...(block ?? "").matchAll(/^ {2}([a-z_]+):\s*\{/gm)].flatMap((match) =>
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

describe("Umfangs-Marker", () => {
  it("faehrt als Daten mit und hat in der Oberflaeche ein Symbol", () => {
    // „Bigger than expected" ist die dritte Groesse und hat kein Enum: es
    // gibt nur einen Marker. Gespiegelt werden muss deshalb nichts – aber
    // beide Beschreibungen (setzen und zuruecknehmen) muessen aus dem
    // Backend kommen, sonst steht der Titel des gesetzten Knopfes im
    // Frontend und sagt dort etwas anderes als hier.
    const schema = read(SCHEMA);

    expect(schema).toContain("SCOPE_MARKER = ScopeMarkerInfo(");
    expect(schema).toContain("undo_description=(");

    const component = read("../components/mail/MailFollowupList.vue");

    expect(component).toMatch(/const SCOPE_ICON = "[a-z_]+";/);
    // Und die Beschriftung wird *nicht* im Frontend wiederholt, ausser als
    // Fallback fuer den noch nicht geladenen Stand.
    expect(component).toContain('scopeMarker?.label ?? "Bigger than expected"');
  });
});

describe("Bau-Einschaetzung", () => {
  it("stimmt zwischen Backend und Frontend ueberein", () => {
    expect([...BUILD_READINESS].sort()).toEqual(backendReadiness().sort());
  });

  it("hat je Wert ein Symbol und eine Farbe in der Oberflaeche", () => {
    // Beschriftung und Beschreibung kommen als Daten mit der Antwort – Symbol
    // und Farbe nicht, und die sind es, die beim Nachtragen eines vierten
    // Wertes vergessen werden. Ohne sie steht in der Filterzeile ein leeres
    // Kaestchen.
    expect(readinessStyleIds().sort()).toEqual([...BUILD_READINESS].sort());
  });

  it("bietet jeden Wert im Katalog des Backends an", () => {
    // `READINESS_OPTIONS` bestueckt die Knoepfe; ein Wert, der dort fehlt,
    // waere ein Zustand, in den die Oberflaeche nicht zurueckkommt – und
    // „unbewertet" ist ausgerechnet der Rueckweg aus dem Fehlklick.
    const source = read(SCHEMA);
    const table = source.match(
      /READINESS_OPTIONS: tuple\[ReadinessOptionInfo, \.\.\.\] = \(([\s\S]*?)\n\)/,
    )?.[1];

    expect(table, "READINESS_OPTIONS im Backend nicht gefunden").toBeTruthy();

    for (const value of BUILD_READINESS) {
      const member = value.toUpperCase();
      expect(table, `BuildReadiness.${member} fehlt in READINESS_OPTIONS`).toContain(
        `BuildReadiness.${member}`,
      );
    }
  });
});
