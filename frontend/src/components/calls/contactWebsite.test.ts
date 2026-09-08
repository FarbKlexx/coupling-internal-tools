/**
 * Die Website aus der Liste, anklickbar gemacht.
 *
 * Der Sinn des Moduls ist ein einziger Fall: die Analysen schreiben
 * „www.beispiel.de“ ohne Schema, und ein solches `href` ist **relativ** – der
 * Klick landete in der eigenen SPA statt beim Betrieb. Alles andere hier ist
 * die Kehrseite davon: in diesen Spalten steht auch, was gar keine Adresse
 * ist, und daraus darf kein Link werden.
 */
import { describe, expect, it } from "vitest";
import { contactWebsite } from "./contactWebsite";

describe("contactWebsite", () => {
  it("ergänzt das fehlende Schema, statt einen relativen Link zu bauen", () => {
    expect(contactWebsite("www.beispiel.de")?.href).toBe("https://www.beispiel.de/");
    expect(contactWebsite("beispiel.de")?.href).toBe("https://beispiel.de/");
  });

  it("lässt ein vorhandenes Schema in Ruhe – auch http", () => {
    expect(contactWebsite("https://beispiel.de/")?.href).toBe("https://beispiel.de/");
    // Nicht auf https „verbessern": viele dieser Betriebe haben kein
    // Zertifikat, und der Link soll funktionieren, nicht vorbildlich sein.
    expect(contactWebsite("http://tayfun-design.de/")?.href).toBe("http://tayfun-design.de/");
  });

  it("behält den Pfad, weil er zwei Einträge derselben Domain unterscheidet", () => {
    const site = contactWebsite("beispiel.de/handwerk/maler");

    expect(site?.href).toBe("https://beispiel.de/handwerk/maler");
    expect(site?.label).toBe("beispiel.de/handwerk/maler");
  });

  it("zeigt kurz an: ohne Schema, ohne „www.“, ohne Schrägstrich am Ende", () => {
    expect(contactWebsite("https://www.beispiel.de/")?.label).toBe("beispiel.de");
  });

  it("ist bei leerem Feld nichts – der Aufrufer zeigt dann keine Zeile", () => {
    expect(contactWebsite("")).toBeNull();
    expect(contactWebsite("   ")).toBeNull();
  });

  it.each([
    // Wörter aus der Tabelle: ein Hostname ohne Punkt ist keine Website.
    "keine",
    "nicht vorhanden",
    // Was danebengerutscht ist.
    "mailto:info@beispiel.de",
    "0521 123456",
    // Andere Schemata gehören nicht in ein href dieser Seite.
    "ftp://beispiel.de",
  ])("macht aus %j Text und keinen Link", (raw) => {
    const site = contactWebsite(raw);

    expect(site?.href).toBeNull();
    // Sichtbar bleibt es: ein falscher Eintrag, den man sieht, ist beim
    // Telefonieren mehr wert als einer, den die Oberfläche weglässt.
    expect(site?.label).toBe(raw);
  });

  it("lässt „javascript:“ nicht ins href", () => {
    expect(contactWebsite("javascript:alert(1)")?.href).toBeNull();
  });
});
