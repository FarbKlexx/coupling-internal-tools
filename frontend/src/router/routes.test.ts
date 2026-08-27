/**
 * Smoke-Test der Anwendung.
 *
 * `@/router` importiert jede View statisch – dieser Test scheitert also
 * bereits, wenn irgendeine View oder eine ihrer Komponenten nicht importierbar
 * ist. Das ist der guenstigste Weg, "startet die App ueberhaupt" in CI zu
 * pruefen, ohne einen Browser zu starten.
 */
import { beforeEach, describe, expect, it } from "vitest";
import { router, routes } from "@/router";
import { buildNavItems } from "@/navigation/buildNavItems";
import { buildRouteSearchIndex } from "@/search/buildRouteSearchIndex";
import { signInAs, signInWithPages, signOut } from "@/test/auth";

const EXPECTED_PATHS = [
  "/login",
  "/passwort-aendern",
  "/konto",
  "/benutzer",
  "/dashboard",
  "/abgleiche",
  "/awin-banner",
  "/webp-konverter",
  "/qr-code",
  "/pdf-schutz",
  "/namensschilder",
  "/kanban",
  "/telefonakquise",
  "/start",
];

/** Routen ohne Berechtigungsschluessel – mit Begruendung, nicht als Restmenge. */
const WITHOUT_PAGE = new Set([
  "/", // Weiterleitung
  "/start", // loest der Guard auf
  "/login", // oeffentlich
  "/passwort-aendern", // jede angemeldete Person
  "/konto", // das eigene Konto
  "/benutzer", // adminOnly statt page
  "/dashboard", // Stub ohne Backend
]);

/**
 * Neutraler Startpunkt vor jeder Navigation.
 *
 * Der Router ist ein Modul-Singleton, sein Zustand ueberlebt also den
 * einzelnen Test. Ein `push` auf die Route, auf der man schon steht, ist ein
 * No-op – ohne diesen Reset wuerde ein Test gruen, weil die Navigation gar
 * nicht stattgefunden hat.
 */
async function startFrom(path: string) {
  await router.replace(path);
  await router.isReady();
}

describe("router", () => {
  beforeEach(async () => {
    signInAs();
    await startFrom("/konto");
  });

  it("kennt genau die erwarteten Feature-Routen", () => {
    const paths = router
      .getRoutes()
      .map((route) => route.path)
      .filter((path) => path !== "/");

    expect(paths.sort()).toEqual([...EXPECTED_PATHS].sort());
  });

  it("hat fuer jede Route eine ladbare Komponente und ein Label", () => {
    for (const route of router.getRoutes()) {
      if (route.path === "/") continue;

      expect(route.components?.default, `Komponente fehlt: ${route.path}`).toBeTruthy();
      expect(route.meta.label, `label fehlt: ${route.path}`).toBeTruthy();
    }
  });

  it("gibt jeder navigierbaren Route ein Icon", () => {
    // Nur was in Sidebar, Suche oder Profilmenue auftaucht, braucht eins –
    // /login und /start werden nie als Eintrag gerendert.
    for (const route of router.getRoutes()) {
      if (!route.meta.sidebar && !route.meta.searchable) continue;

      expect(route.meta.icon, `icon fehlt: ${route.path}`).toBeTruthy();
    }
  });

  it("gibt jeder Feature-Route einen Berechtigungsschluessel", () => {
    for (const route of routes) {
      if (WITHOUT_PAGE.has(route.path)) continue;

      expect(route.meta?.page, `page fehlt: ${route.path}`).toBeTruthy();
    }
  });

  it("leitet / auf die erste erlaubte Seite um", async () => {
    await router.push("/");
    await router.isReady();

    expect(router.currentRoute.value.path).toBe("/abgleiche");
  });

  it("leitet / auf die erste *erlaubte* Seite um, nicht auf eine gesperrte", async () => {
    signInWithPages(["kanban"]);

    await router.push("/");
    await router.isReady();

    expect(router.currentRoute.value.path).toBe("/kanban");
  });
});

describe("Zugangs-Guard", () => {
  beforeEach(async () => {
    signInAs();
    await startFrom("/abgleiche");
  });

  it("schickt Unangemeldete zur Anmeldung und merkt sich das Ziel", async () => {
    signOut();

    await router.push("/kanban");

    expect(router.currentRoute.value.name).toBe("login");
    expect(router.currentRoute.value.query.weiter).toBe("/kanban");
  });

  it("laesst niemanden auf eine Seite ohne Berechtigung", async () => {
    signInWithPages(["qr-code"]);

    await router.push("/kanban");
    await router.isReady();

    expect(router.currentRoute.value.path).toBe("/qr-code");
  });

  it("haelt die Benutzerverwaltung von Nicht-Administratoren fern", async () => {
    signInWithPages(["kanban"]);

    await router.push("/benutzer");

    expect(router.currentRoute.value.path).toBe("/kanban");
  });

  it("zwingt zum Passwortwechsel, solange er aussteht", async () => {
    signInAs({ must_change_password: true });

    await router.push("/kanban");

    expect(router.currentRoute.value.name).toBe("passwort-aendern");
  });

  it("schickt Angemeldete von der Anmeldeseite weiter", async () => {
    signInAs();

    await router.push("/login");

    expect(router.currentRoute.value.name).not.toBe("login");
  });
});

describe("Suchindex", () => {
  beforeEach(() => signInAs());

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

  it("bietet keine Seite an, die der Benutzer nicht oeffnen darf", () => {
    const visibility = { mayOpen: (page?: string) => page === "kanban", isAdmin: false };

    const ids = buildRouteSearchIndex(router.getRoutes(), visibility).map((e) => e.id);

    expect(ids).toEqual(["kanban"]);
  });
});

describe("Sidebar-Eintraege", () => {
  it("enthaelt genau die als sidebar markierten Routen, in Deklarationsreihenfolge", () => {
    const expected = routes
      .filter((route) => route.meta?.sidebar)
      .map((route) => String(route.name));

    expect(buildNavItems(routes).map((item) => item.id)).toEqual(expected);
  });

  it("laesst das Dashboard aus", () => {
    expect(buildNavItems(routes).map((item) => item.id)).not.toContain("dashboard");
  });

  it("gibt jedem Eintrag Label und Icon aus der Route-Meta", () => {
    for (const item of buildNavItems(routes)) {
      const route = routes.find((candidate) => candidate.name === item.id);

      expect(item.label).toBe(route?.meta?.label);
      expect(item.icon).toBe(route?.meta?.icon);
    }
  });

  it("zeigt nur die erlaubten Seiten", () => {
    const visibility = {
      mayOpen: (page?: string) => page === "kanban" || page === "qr-code",
      isAdmin: false,
    };

    expect(buildNavItems(routes, visibility).map((item) => item.id)).toEqual(["qr-code", "kanban"]);
  });

  it("blendet die Benutzerverwaltung fuer Nicht-Administratoren aus", () => {
    const asUser = { mayOpen: () => true, isAdmin: false };
    const asAdmin = { mayOpen: () => true, isAdmin: true };

    expect(buildNavItems(routes, asUser).map((i) => i.id)).not.toContain("benutzer");
    expect(buildNavItems(routes, asAdmin).map((i) => i.id)).toContain("benutzer");
  });
});
