/**
 * Ein Mount pro Komponentenart: beweist, dass die SFCs zur Laufzeit
 * funktionieren und nicht nur typpruefbar sind. Ohne Netzwerk, ohne Backend.
 */
import { describe, expect, it } from "vitest";
import { mount } from "@vue/test-utils";
import KanbanCard from "./KanbanCard.vue";
import LabelChip from "./LabelChip.vue";
import type { KanbanCard as KanbanCardType, KanbanLabel } from "@/api/kanban.api";

const label: KanbanLabel = {
  id: "l1",
  name: "Jeans Fritz",
  color: "blue",
  archived: false,
};

const card: KanbanCardType = {
  id: "c1",
  column_id: "ideen",
  position: 0,
  title: "Sommerkampagne",
  description: "Banner abstimmen",
  labels: [label],
  created_at: "2026-08-21T09:00:00Z",
  updated_at: "2026-08-21T09:00:00Z",
  created_by: "au",
};

describe("LabelChip", () => {
  it("rendert den Namen mit der Farbklasse des Slugs", () => {
    const wrapper = mount(LabelChip, { props: { label } });

    expect(wrapper.text()).toContain("Jeans Fritz");
    expect(wrapper.classes()).toContain("label-blue");
    expect(wrapper.classes()).not.toContain("label-chip--archived");
  });

  it("markiert archivierte Labels", () => {
    const wrapper = mount(LabelChip, {
      props: { label: { ...label, archived: true } },
    });

    expect(wrapper.classes()).toContain("label-chip--archived");
  });
});

describe("KanbanCard", () => {
  it("zeigt Titel, Labels und den Notiz-Hinweis", () => {
    const wrapper = mount(KanbanCard, { props: { card } });

    expect(wrapper.text()).toContain("Sommerkampagne");
    expect(wrapper.text()).toContain("Jeans Fritz");
    expect(wrapper.text()).toContain("Notiz");
    expect(wrapper.text()).toContain("au");
    // sortablejs identifiziert die Karte beim Drop ueber dieses Attribut.
    expect(wrapper.attributes("data-card-id")).toBe("c1");
  });

  it("laesst den Notiz-Hinweis weg, wenn keine Notiz da ist", () => {
    const wrapper = mount(KanbanCard, {
      props: { card: { ...card, description: "" } },
    });

    expect(wrapper.text()).not.toContain("Notiz");
  });

  it("meldet einen Klick als open-Event mit der Karte", async () => {
    const wrapper = mount(KanbanCard, { props: { card } });

    await wrapper.trigger("click");

    expect(wrapper.emitted("open")?.[0]).toEqual([card]);
  });

  it("bietet in Ideen genau einen Weg nach TODO", async () => {
    const wrapper = mount(KanbanCard, {
      props: { card, columnLabels: { todo: "TODO" } },
    });
    const button = wrapper.get("button");

    expect(wrapper.findAll("button")).toHaveLength(1);
    expect(button.attributes("title")).toBe("Nach TODO verschieben");

    await button.trigger("click");

    expect(wrapper.emitted("advance")?.[0]).toEqual([{ card, to: "todo" }]);
    // click.stop: der Button darf nicht zusaetzlich den Dialog aufmachen.
    expect(wrapper.emitted("open")).toBeUndefined();
  });

  it("bietet aus In Progress sowohl Done als auch On hold", () => {
    const wrapper = mount(KanbanCard, {
      props: {
        card: { ...card, column_id: "in_progress" },
        columnLabels: { done: "Done", on_hold: "On hold" },
      },
    });

    // Ueber `title` statt `text`: der Buttontext enthaelt auch die Icon-Ligatur.
    expect(wrapper.findAll("button").map((b) => b.attributes("title"))).toEqual([
      "Nach Done verschieben",
      "Nach On hold verschieben",
    ]);
  });

  it("laesst Endspalten ohne Button", () => {
    for (const columnId of ["done", "on_hold"] as const) {
      const wrapper = mount(KanbanCard, {
        props: { card: { ...card, column_id: columnId } },
      });

      expect(wrapper.findAll("button")).toHaveLength(0);
    }
  });

  it("sperrt die Buttons waehrend eines Schreibvorgangs", () => {
    const wrapper = mount(KanbanCard, { props: { card, isBusy: true } });

    expect(wrapper.get("button").attributes("disabled")).toBeDefined();
  });
});
