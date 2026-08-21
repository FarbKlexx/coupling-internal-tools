/**
 * Die Label-Farbpalette existiert an drei Stellen, die uebereinstimmen muessen:
 * dem `LabelColor`-Enum im Backend (dort wird der Slug validiert und
 * gespeichert), `LABEL_COLORS` hier im Frontend und den `.label-<slug>`-Klassen
 * in style.css (den tatsaechlichen Farbwerten).
 *
 * Driftet eine davon, faellt es sonst erst auf, wenn ein Label unsichtbar oder
 * ein Anlegen mit 422 abgewiesen wird. Deshalb prueft CI das hier – der
 * einzige Test, der ueber die Frontend-Grenze hinausliest.
 */
import { existsSync, readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";
import { LABEL_COLORS } from "./kanban.api";

/**
 * Liest eine Datei relativ zu diesem Test.
 *
 * Setzt das Repo-Layout voraus (`backend/` und `frontend/` als Geschwister) –
 * in CI nach `actions/checkout` gegeben. Ohne diesen Hinweis wäre ein
 * unvollständiger Checkout nur ein nacktes ENOENT.
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

/** Alle ersten Capture-Groups eines globalen Patterns, ohne Leertreffer. */
const captures = (text: string, pattern: RegExp): string[] =>
  [...text.matchAll(pattern)].flatMap((match) => (match[1] ? [match[1]] : []));

function backendSlugs(): string[] {
  const source = read("../../../backend/app/schemas/kanban.py");
  const enumBody = source.match(/class LabelColor\(str, Enum\):([\s\S]*?)\n\n\nclass /)?.[1];

  expect(enumBody, "LabelColor-Enum im Backend nicht gefunden").toBeTruthy();

  return captures(enumBody ?? "", /^\s+[A-Z_]+ = "([a-z]+)"$/gm);
}

function styleSlugs(): string[] {
  // Nur Klassen, die tatsaechlich eine Farbe definieren - .label-chip und
  // .label-swatch sind Struktur, keine Palette.
  return captures(read("../style.css"), /^\.label-([a-z]+)\s*\{\s*\n\s*--label-color:/gm);
}

describe("Label-Farbpalette", () => {
  it("stimmt zwischen Backend und Frontend ueberein - inklusive Reihenfolge", () => {
    // Die Reihenfolge ist bedeutungstragend: die automatische Farbwahl nimmt
    // die am wenigsten benutzte und entscheidet Gleichstand ueber genau diese
    // Reihenfolge.
    expect([...LABEL_COLORS]).toEqual(backendSlugs());
  });

  it("hat fuer jeden Slug eine CSS-Klasse", () => {
    const inCss = styleSlugs();

    for (const color of LABEL_COLORS) {
      expect(inCss, `.label-${color} fehlt in style.css`).toContain(color);
    }
  });

  it("hat keine CSS-Klasse ohne zugehoerigen Slug", () => {
    for (const slug of styleSlugs()) {
      expect(LABEL_COLORS as readonly string[], `.label-${slug} ist verwaist`).toContain(slug);
    }
  });
});
