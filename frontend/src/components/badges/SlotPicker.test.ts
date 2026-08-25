/**
 * Das Kartenraster wird aus der Backend-Geometrie gezeichnet und ist im
 * Frontend nirgends fest verdrahtet. Dieser Test hält das fest: ein anderes
 * Format ergibt ein anderes Raster, ohne dass hier etwas geändert wird.
 */
import { describe, expect, it } from "vitest";
import { mount } from "@vue/test-utils";
import SlotPicker from "./SlotPicker.vue";
import type { BadgeSheetFormat } from "@/api/name_badge.api";

const A4: BadgeSheetFormat = {
  id: "a4_75x40",
  label: "A4 · 12 Einsteckschilder 75 × 40 mm",
  sheet_width_mm: 210,
  sheet_height_mm: 297,
  columns: 2,
  rows: 6,
  slots_per_sheet: 12,
  card_width_mm: 75,
  card_height_mm: 40,
  margin_left_mm: 30,
  margin_right_mm: 30,
  margin_top_mm: 28.5,
  margin_bottom_mm: 28.5,
  gap_x_mm: 0,
  gap_y_mm: 0,
  safety_mm: 4,
  fields: [],
};

function mountPicker(format: BadgeSheetFormat = A4, modelValue = 1) {
  return mount(SlotPicker, { props: { format, modelValue } });
}

describe("SlotPicker", () => {
  it("zeigt genau so viele Karten, wie auf den Bogen passen", () => {
    expect(mountPicker().findAll("[data-slot]")).toHaveLength(12);
  });

  it("folgt einem anderen Format ohne Anpassung", () => {
    const wrapper = mountPicker({ ...A4, columns: 3, rows: 4, slots_per_sheet: 12 });
    const grid = wrapper.find("[data-slot]").element.parentElement;

    expect(grid?.getAttribute("style")).toContain("repeat(3, 1fr)");
  });

  it("nummeriert die Karten zeilenweise ab 1", () => {
    const labels = mountPicker()
      .findAll("[data-slot]")
      .map((slot) => slot.text());

    expect(labels).toEqual(["1", "2", "3", "4", "5", "6", "7", "8", "9", "10", "11", "12"]);
  });

  it("meldet die angeklickte Karte nach oben", async () => {
    const wrapper = mountPicker();

    await wrapper.findAll("[data-slot]")[6]?.trigger("click");

    expect(wrapper.emitted("update:modelValue")).toEqual([[7]]);
  });

  it("markiert die gewählte Karte als gedrückt", () => {
    const pressed = mountPicker(A4, 5)
      .findAll("[data-slot]")
      .map((slot) => slot.attributes("aria-pressed"));

    expect(pressed[4]).toBe("true");
    expect(pressed[3]).toBe("false");
  });

  it("bildet die Ränder des Bogens maßstäblich ab", () => {
    const grid = mountPicker().find("[data-slot]").element.parentElement;
    const style = grid?.getAttribute("style") ?? "";

    // 30 von 210 mm Rand links, 28,5 von 297 mm oben.
    expect(style).toContain("left: 14.285714285714285%");
    expect(style).toContain("top: 9.595959595959595%");
  });

  it("erklärt, wie viele Karten frei bleiben", () => {
    expect(mountPicker(A4, 4).text()).toContain("3 Karten davor bleiben");
  });
});
