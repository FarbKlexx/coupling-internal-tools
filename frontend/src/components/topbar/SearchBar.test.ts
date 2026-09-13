/**
 * Die Palette ohne Suchbegriff.
 *
 * Ein leeres Feld hiess frueher „keine Treffer", obwohl niemand etwas gesucht
 * hatte — wer die Suche oeffnet, um zu sehen *was* es gibt, bekam ein leeres
 * Fenster. Jetzt steht dort alles, was dieser Benutzer oeffnen darf, und
 * dieser Test haelt das an denselben Routen fest, an denen auch die Sidebar
 * gemessen wird.
 */
import { beforeEach, describe, expect, it } from "vitest";
import { flushPromises, mount } from "@vue/test-utils";
import { router } from "@/router";
import { signInAs, signInWithPages } from "@/test/auth";
import SearchBar from "./SearchBar.vue";

async function openPalette() {
  await router.push("/abgleiche");
  await router.isReady();

  const wrapper = mount(SearchBar, { global: { plugins: [router] } });

  // Die Palette oeffnet erst, wenn das Feld den Fokus bekommt — genau das
  // macht der Platzhalter in der Kopfzeile beim Klick.
  await wrapper.find("input").trigger("focus");
  await flushPromises();

  return wrapper;
}

describe("SearchBar", () => {
  beforeEach(() => signInAs());

  it("zeigt ohne Suchbegriff jede suchbare Route", async () => {
    const wrapper = await openPalette();
    const text = wrapper.text();

    const searchable = router.getRoutes().filter((route) => route.meta.searchable);

    expect(searchable.length).toBeGreaterThan(0);
    for (const route of searchable) {
      expect(text, `fehlt in der Palette: ${String(route.name)}`).toContain(
        String(route.meta.label),
      );
    }
  });

  it("laesst die Reihenfolge der Routen stehen, solange nichts gesucht wird", async () => {
    const wrapper = await openPalette();

    const gezeigt = wrapper.findAll("button").map((button) => button.text());
    const erwartet = router
      .getRoutes()
      .filter((route) => route.meta.searchable)
      .map((route) => String(route.meta.label));

    // Ohne Begriff gibt es keine Treffergenauigkeit, nach der sortiert werden
    // koennte — also dieselbe Reihenfolge wie in der Navigation.
    expect(gezeigt.map((zeile) => erwartet.find((label) => zeile.includes(label)))).toEqual(
      erwartet,
    );
  });

  it("zeigt nur, was der angemeldete Benutzer oeffnen darf", async () => {
    signInWithPages(["qr-code"]);

    const wrapper = await openPalette();

    expect(wrapper.text()).toContain("QR-Code Generator");
    expect(wrapper.text()).not.toContain("Kanban Board");
  });

  it("sucht, sobald etwas eingetippt ist", async () => {
    const wrapper = await openPalette();

    await wrapper.find("input").setValue("qr");
    await flushPromises();

    const zeilen = wrapper.findAll("button");

    expect(zeilen.length).toBeGreaterThan(0);
    expect(zeilen.length).toBeLessThan(router.getRoutes().length);
    expect(zeilen[0]?.text()).toContain("QR-Code Generator");
  });
});
