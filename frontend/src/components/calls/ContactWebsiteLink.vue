<script setup lang="ts">
/**
 * Die Website eines Betriebs, anklickbar – oder als Text, wenn das nicht geht.
 *
 * Eine eigene Komponente und keine Funktion im Template, weil das Ergebnis
 * *zwei* Dinge trägt (Adresse und Beschriftung) und je nachdem ein `<a>` oder
 * ein `<span>` daraus wird. Im Template ließe sich das nur über mehrfache
 * Aufrufe mit `!`-Zusicherungen schreiben.
 *
 * Rendert nichts, wenn das Feld leer ist – der Aufrufer braucht kein `v-if`.
 * Klassen von außen landen dank Attribut-Durchreichung an der Wurzel.
 *
 * Die Entscheidung, was ein Link wird, liegt in `contactWebsite`.
 */
import { computed } from "vue";
import { contactWebsite } from "./contactWebsite";

const props = defineProps<{
  /** Der Wert aus der CSV, unverändert. */
  website: string;
  /** Feste Beschriftung statt des Hostnamens. */
  text?: string;
  /** Schriftgröße des Symbols in px – es soll zur Textzeile passen. */
  iconSize?: number;
}>();

const site = computed(() => contactWebsite(props.website));
</script>

<template>
  <a
    v-if="site?.href"
    :href="site.href"
    target="_blank"
    rel="noopener noreferrer"
    class="inline-flex items-baseline gap-0.5 hover:text-strong transition-colors"
  >
    {{ text ?? site.label }}
    <span class="material-symbols-outlined" :style="{ fontSize: `${iconSize ?? 13}px` }">
      open_in_new
    </span>
  </a>

  <!-- Nicht verlinkbar: „keine“, eine Nummer, eine Adresse. Sichtbar bleiben
       muss es trotzdem – beim Telefonieren ist ein falscher Eintrag, den man
       sieht, mehr wert als einer, den die Oberfläche weglässt. -->
  <span v-else-if="site" class="text-zinc-500" :title="site.label">{{ text ?? site.label }}</span>
</template>
