/**
 * Die Berechtigungs-IDs existieren an zwei Stellen: dem `Page`-Enum im Backend
 * (dort wird durchgesetzt) und `meta.page` an den Routen hier (dort wird
 * gefiltert, was in Sidebar und Suche auftaucht).
 *
 * Ein Tippfehler faellt sonst nirgends auf: das Backend antwortet mit 403 auf
 * eine Seite, die im Frontend anders heisst, und im Admin-UI haengt eine
 * Checkbox an einer ID, zu der es keine Seite gibt. Deshalb prueft CI das hier
 * – nach demselben Muster wie `labelPalette.test.ts`.
 *
 * Anders als bei der Farbpalette ist die *Reihenfolge* egal: das Admin-UI
 * sortiert die Checkboxen nach der Navigationsreihenfolge des Frontends, das
 * Backend liefert nur die Menge.
 */
import { existsSync, readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";
import { routes } from "./index";

/** Liest eine Datei relativ zu diesem Test. */
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

function backendPageIds(): string[] {
  const source = read("../../../backend/app/schemas/access.py");
  const enumBody = source.match(/class Page\(str, Enum\):([\s\S]*?)\n\n\nclass /)?.[1];

  expect(enumBody, "Page-Enum im Backend nicht gefunden").toBeTruthy();

  return [...(enumBody ?? "").matchAll(/^\s+[A-Z_]+ = "([a-z0-9-]+)"$/gm)].flatMap((match) =>
    match[1] ? [match[1]] : [],
  );
}

function frontendPageIds(): string[] {
  return routes.flatMap((route) => (route.meta?.page ? [route.meta.page] : []));
}

describe("Seiten-IDs", () => {
  it("stimmen zwischen Backend und Frontend ueberein", () => {
    expect(frontendPageIds().sort()).toEqual(backendPageIds().sort());
  });

  it("kommen im Frontend nicht doppelt vor", () => {
    // Mehrere Routen duerfen sich spaeter eine Berechtigung teilen – dann ist
    // dieser Test anzupassen. Heute waere ein Duplikat ein Copy-Paste-Fehler.
    const ids = frontendPageIds();

    expect(new Set(ids).size).toBe(ids.length);
  });

  it("liegen an jeder Route, die in Sidebar oder Suche auftaucht", () => {
    // Eine sichtbare Seite ohne Berechtigungsschluessel waere fuer jeden
    // offen – und niemandem faellt es auf, weil alles funktioniert.
    //
    // Ausnahme mit Ansage: `adminOnly`-Routen haengen am Administratorflag
    // statt an einer Seitenberechtigung und haben deshalb bewusst keinen
    // Eintrag im `Page`-Enum des Backends.
    for (const route of routes) {
      if (!route.meta?.sidebar && !route.meta?.searchable) continue;
      if (route.meta?.adminOnly) continue;

      expect(route.meta?.page, `page fehlt: ${route.path}`).toBeTruthy();
    }
  });

  it("kennt genau eine adminOnly-Route – die Benutzerverwaltung", () => {
    // Damit die Ausnahme oben eine Ausnahme bleibt und nicht zur Hintertuer
    // wird, durch die neue Seiten ohne Berechtigung hereinkommen.
    const adminOnly = routes.filter((route) => route.meta?.adminOnly).map((r) => r.path);

    expect(adminOnly).toEqual(["/benutzer"]);
  });
});
