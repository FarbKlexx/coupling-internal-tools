/**
 * Smoke-Test der Anwendung.
 *
 * `@/router` importiert jede View statisch – dieser Test scheitert also
 * bereits, wenn irgendeine View oder eine ihrer Komponenten nicht importierbar
 * ist. Das ist der guenstigste Weg, "startet die App ueberhaupt" in CI zu
 * pruefen, ohne einen Browser zu starten.
 */
import { describe, expect, it } from "vitest";
import { router } from "@/router";
import { buildRouteSearchIndex } from "@/search/buildRouteSearchIndex";

const EXPECTED_PATHS = [
  "/dashboard",
  "/abgleiche",
  "/awin-banner",
  "/webp-konverter",
  "/qr-code",
  "/pdf-schutz",
  "/kanban",
];

describe("router", () => {
  it("kennt genau die erwarteten Feature-Routen", () => {
    const paths = router
      .getRoutes()
      .map((route) => route.path)
      .filter((path) => path !== "/");

    expect(paths.sort()).toEqual([...EXPECTED_PATHS].sort());
  });

  it("hat fuer jede Route eine ladbare Komponente und vollstaendige Meta-Daten", () => {
    for (const route of router.getRoutes()) {
      if (route.path === "/") continue;

      expect(route.components?.default, `Komponente fehlt: ${route.path}`).toBeTruthy();
      expect(route.meta.label, `label fehlt: ${route.path}`).toBeTruthy();
      expect(route.meta.icon, `icon fehlt: ${route.path}`).toBeTruthy();
    }
  });

  it("leitet / auf /abgleiche um", async () => {
    // resolve() folgt dem Redirect nicht - dafuer muss navigiert werden.
    await router.push("/");
    await router.isReady();

    expect(router.currentRoute.value.path).toBe("/abgleiche");
  });
});

describe("Suchindex", () => {
  it("enthaelt genau die als searchable markierten Routen", () => {
    const index = buildRouteSearchIndex(router.getRoutes());
    const searchable = router.getRoutes().filter((route) => route.meta.searchable);

    expect(index.map((entry) => entry.id).sort()).toEqual(
      searchable.map((route) => String(route.name)).sort(),
    );
    // Das Dashboard ist ein Stub und darf nicht in der Suche auftauchen.
    expect(index.map((entry) => entry.id)).not.toContain("dashboard");
  });

  it("gibt jedem Eintrag Label, Icon und Pfad", () => {
    for (const entry of buildRouteSearchIndex(router.getRoutes())) {
      expect(entry.label).toBeTruthy();
      expect(entry.icon).not.toBe("undefined");
      expect(entry.path.startsWith("/")).toBe(true);
    }
  });
});
