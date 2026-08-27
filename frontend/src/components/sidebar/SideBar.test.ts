/**
 * Die Sidebar ist ein **hartkodiertes** Array – eine neue Route erscheint dort
 * nicht automatisch. Dieser Test haelt beides zusammen: jeder sichtbare
 * Eintrag muss auf eine existierende Route zeigen, und jede suchbare Route
 * muss ueber die Sidebar erreichbar sein.
 */
import { beforeEach, describe, expect, it } from "vitest";
import { flushPromises, mount } from "@vue/test-utils";
import { router } from "@/router";
import { signInAs, signInWithPages } from "@/test/auth";
import SideBar from "./SideBar.vue";

/** Klickt jeden Eintrag durch und sammelt, wo man landet. */
async function reachableRouteNames(): Promise<string[]> {
  await router.push("/abgleiche");
  await router.isReady();

  const wrapper = mount(SideBar, { global: { plugins: [router] } });
  const names: string[] = [];

  // Nur die Nav-Eintraege – der Ein-/Ausklapp-Button ist ebenfalls ein
  // <button>, navigiert aber nicht.
  for (const item of wrapper.findAll("[data-nav-item]")) {
    await item.trigger("click");
    // Der Klick-Handler ruft router.push, wartet es aber nicht ab.
    await flushPromises();

    names.push(String(router.currentRoute.value.name));
  }

  return names;
}

describe("SideBar", () => {
  // Die Sidebar zeigt nur, was der angemeldete Benutzer oeffnen darf, und der
  // Router-Guard laesst ohne Anmeldung ohnehin nichts durch.
  beforeEach(() => signInAs());

  it("verweist mit jedem Eintrag auf eine existierende Route", async () => {
    const names = await reachableRouteNames();
    const known = new Set(router.getRoutes().map((route) => String(route.name)));

    expect(names.length).toBeGreaterThan(0);
    for (const name of names) {
      expect(known, `unbekannte Route in der Sidebar: ${name}`).toContain(name);
    }
  });

  it("macht jede suchbare Route erreichbar", async () => {
    const reachable = new Set(await reachableRouteNames());

    for (const route of router.getRoutes().filter((r) => r.meta.searchable)) {
      expect(reachable, `nicht in der Sidebar: ${String(route.name)}`).toContain(
        String(route.name),
      );
    }
  });

  it("blendet das deaktivierte Dashboard aus", async () => {
    await router.push("/abgleiche");
    const wrapper = mount(SideBar, { global: { plugins: [router] } });

    expect(wrapper.text()).not.toContain("Dashboard");
  });

  it("zeigt einem eingeschraenkten Konto nur dessen Seiten", async () => {
    signInWithPages(["kanban"]);
    await router.push("/kanban");

    const wrapper = mount(SideBar, { global: { plugins: [router] } });

    expect(wrapper.text()).toContain("Kanban Board");
    expect(wrapper.text()).not.toContain("QR-Code Generator");
    expect(wrapper.text()).not.toContain("Benutzer");
  });
});
