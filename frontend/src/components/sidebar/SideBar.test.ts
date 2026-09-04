/**
 * Die Sidebar leitet sich aus den Routen ab. Dieser Test haelt beides
 * zusammen: jeder sichtbare Eintrag muss auf eine existierende Route zeigen,
 * und jede suchbare Route muss ueber die Sidebar erreichbar sein – auch
 * seit die Eintraege in einklappbaren Gruppen stehen.
 */
import { beforeEach, describe, expect, it } from "vitest";
import { flushPromises, mount } from "@vue/test-utils";
import { router } from "@/router";
import { signInAs, signInWithPages } from "@/test/auth";
import { useSidebar } from "@/composables/useSidebar";
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

  it("klappt eine Gruppe zu und wieder auf", async () => {
    await router.push("/abgleiche");
    const wrapper = mount(SideBar, { global: { plugins: [router] } });

    const tools = wrapper
      .findAll("button[aria-expanded]")
      .find((button) => button.text().includes("Tools"));

    expect(tools, "keine Gruppenueberschrift 'Tools'").toBeTruthy();
    expect(wrapper.text()).toContain("QR-Code Generator");

    await tools!.trigger("click");
    expect(wrapper.text()).not.toContain("QR-Code Generator");
    // Die anderen Gruppen bleiben davon unberuehrt.
    expect(wrapper.text()).toContain("AWIN Abgleiche");

    await tools!.trigger("click");
    expect(wrapper.text()).toContain("QR-Code Generator");
  });

  it("stellt die Benutzerverwaltung unter die Gruppen", async () => {
    await router.push("/abgleiche");
    const wrapper = mount(SideBar, { global: { plugins: [router] } });

    const items = wrapper.findAll("[data-nav-item]");

    expect(items[items.length - 1]?.text()).toContain("Benutzer");
  });

  it("zeigt eingeklappt alle Eintraege, auch die zugeklappter Gruppen", async () => {
    const { collapsed, toggleGroup } = useSidebar();
    toggleGroup("tools");
    collapsed.value = true;

    try {
      await router.push("/abgleiche");
      const wrapper = mount(SideBar, { global: { plugins: [router] } });

      expect(wrapper.findAll("button[aria-expanded]")).toHaveLength(0);
      expect(wrapper.text()).toContain("QR-Code Generator");
      // Die Eintraege behalten ihre Reihenfolge, die Verwaltung bleibt unten.
      const items = wrapper.findAll("[data-nav-item]");
      expect(items[0]?.text()).toContain("AWIN Abgleiche");
      expect(items[items.length - 1]?.text()).toContain("Benutzer");
    } finally {
      collapsed.value = false;
      toggleGroup("tools");
    }
  });

  it("gliedert eingeklappt mit Strichen statt Ueberschriften", async () => {
    const { collapsed } = useSidebar();
    await router.push("/abgleiche");

    const wrapper = mount(SideBar, { global: { plugins: [router] } });
    const groups = wrapper.findAll("button[aria-expanded]").length;

    expect(groups).toBeGreaterThan(1);
    // Ausgeklappt trennt allein der Fussbereich.
    expect(wrapper.findAll(".sidebar-rule")).toHaveLength(1);

    collapsed.value = true;
    try {
      await flushPromises();

      // Je ein Strich zwischen den Gruppen – vor der ersten keiner – plus der
      // des Fussbereichs.
      expect(wrapper.findAll(".sidebar-rule")).toHaveLength(groups - 1 + 1);
    } finally {
      collapsed.value = false;
    }
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
