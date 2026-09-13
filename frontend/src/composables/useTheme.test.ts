import { describe, expect, it } from "vitest";
import { nextTick } from "vue";
import { useTheme } from "./useTheme";

/**
 * Der Umschalter schreibt genau ein Attribut, und daran haengen alle Farben
 * (siehe den Token-Block in `style.css`). Diese beiden Tests halten die
 * Kopplung fest: geht das Attribut verloren, faellt die Anwendung stumm in
 * den Dunkelmodus zurueck, statt einen Fehler zu werfen.
 */
describe("useTheme", () => {
  it("schreibt den Modus an das <html>-Element", async () => {
    const { theme, isLight, toggle } = useTheme();
    const vorher = theme.value;

    toggle();
    await nextTick();

    expect(theme.value).toBe(vorher === "dark" ? "light" : "dark");
    expect(isLight.value).toBe(theme.value === "light");
    expect(document.documentElement.dataset.theme).toBe(theme.value);
  });

  it("teilt einen Zustand, egal wer fragt", async () => {
    // Der State liegt auf Modulebene: die Topbar schaltet um, und jede andere
    // Stelle, die den Modus liest, sieht dasselbe – ohne Store dazwischen.
    const eins = useTheme();
    const zwei = useTheme();

    eins.toggle();
    await nextTick();

    expect(zwei.theme.value).toBe(eins.theme.value);
    expect(zwei.isLight.value).toBe(eins.isLight.value);
  });
});
