<script setup lang="ts">
/**
 * Die Ergebnisknöpfe samt Zeitpunkt-Rückfrage.
 *
 * Zwei Stellen brauchen sie: der Arbeitsplatz nach dem Gespräch und die
 * Richtigstellung einer bereits eingetragenen Entscheidung. Beide müssen exakt
 * gleich fragen – ein Ergebnis mit Zeitbedarf darf auch beim Korrigieren nicht
 * ohne Zeitpunkt abgeschickt werden, sonst liegt der Betrieb danach ohne
 * Wiedervorlage da.
 *
 * Beschriftung, Beschreibung und Tonlage kommen als Daten aus der Antwort des
 * Backends; hier steht nur, was reine Darstellung ist.
 */
import { ref, useId } from "vue";
import type { CallOutcome, OutcomeInfo, OutcomePayload } from "@/api/call_list.api";
import { toLocalInput, tomorrowMorning } from "./callTime";

/** Was der Wähler beisteuert – Anmerkung und Adresse hängt der Aufrufer an. */
export type OutcomeChoice = Pick<
  OutcomePayload,
  "outcome" | "snooze_minutes" | "due_at" | "appointment_at"
>;

const props = defineProps<{
  outcomes: OutcomeInfo[];
  disabled: boolean;
  /**
   * Zusätzlicher Vorschlag „sofort wieder anrufen".
   *
   * Nur beim Richtigstellen: dort ist der häufigste Wunsch, einen versehentlich
   * abgeräumten Betrieb einfach wieder in die Liste zu holen. Beim Anruf selbst
   * wäre der Knopf sinnlos – man hat gerade aufgelegt.
   */
  allowImmediate?: boolean;
}>();

const emit = defineEmits<{
  (event: "submit", choice: OutcomeChoice): void;
}>();

/**
 * Symbol pro Ergebnis.
 *
 * `callOutcomes.test.ts` hält diese Zuordnung mit dem `CallOutcome`-Enum des
 * Backends zusammen: eine ID ohne Symbol ist im Knopf ein leeres Kästchen, und
 * das fällt sonst erst dem auf, der telefoniert.
 */
const ICONS: Record<CallOutcome, string> = {
  zugesagt: "mark_email_read",
  nicht_erreichbar: "phone_missed",
  rueckruf: "event",
  kein_bedarf: "do_not_disturb_on",
  abgelehnt: "block",
  nummer_falsch: "wrong_location",
};

/** Welches Ergebnis wartet gerade auf einen Zeitpunkt? */
const pending = ref<OutcomeInfo | null>(null);
const customTime = ref("");

function pick(outcome: OutcomeInfo) {
  if (props.disabled) return;

  if (outcome.time_input === "none") {
    emit("submit", { outcome: outcome.id });
    return;
  }

  // Es fehlt noch ein Zeitpunkt – die Auswahl klappt darunter auf.
  pending.value = outcome;
  customTime.value = toLocalInput(
    outcome.time_input === "appointment"
      ? new Date(Date.now() + 60 * 60 * 1000)
      : tomorrowMorning(),
  );
}

function submitSnooze(minutes: number) {
  emit("submit", { outcome: "nicht_erreichbar", snooze_minutes: minutes });
}

function submitMoment(stamp: Date) {
  if (!pending.value) return;

  // Beim Rückruf ist der Zeitpunkt der *Termin*; das Backend zieht davon den
  // Vorlauf ab. Bei der Wiedervorlage ist er direkt der Zeitpunkt der Rückkehr.
  emit(
    "submit",
    pending.value.time_input === "appointment"
      ? { outcome: pending.value.id, appointment_at: stamp.toISOString() }
      : { outcome: pending.value.id, due_at: stamp.toISOString() },
  );
}

function submitCustom() {
  if (!customTime.value) return;

  const stamp = new Date(customTime.value);
  if (Number.isNaN(stamp.getTime())) return;

  submitMoment(stamp);
}

function toneClass(tone: OutcomeInfo["tone"]): string {
  if (tone === "positive") return "outcome outcome--positive";
  if (tone === "negative") return "outcome outcome--negative";
  return "outcome";
}

/**
 * Eigene ID pro Instanz: der Arbeitsplatz und eine offene Richtigstellung
 * können gleichzeitig auf der Seite stehen, und zwei gleiche `id` machen aus
 * dem zweiten Label eines, das auf das erste Feld zeigt.
 */
const timeFieldId = useId();
</script>

<template>
  <div class="space-y-2">
    <div class="grid grid-cols-1 sm:grid-cols-2 gap-2">
      <button
        v-for="outcome in outcomes"
        :key="outcome.id"
        :class="[toneClass(outcome.tone), pending?.id === outcome.id ? 'outcome--armed' : '']"
        :disabled="disabled"
        :title="outcome.description"
        @click="pick(outcome)"
      >
        <span class="material-symbols-outlined">{{ ICONS[outcome.id] }}</span>
        <span class="text-left">{{ outcome.label }}</span>
      </button>
    </div>

    <!-- Zeitpunkt, wenn das Ergebnis einen braucht -->
    <div v-if="pending" class="rounded-md grey-background light-grey-stroke p-3 space-y-3">
      <p class="text-sm font-medium">
        {{
          pending.time_input === "appointment"
            ? "Wann ist der Rückruf verabredet?"
            : "Wann erneut anrufen?"
        }}
      </p>
      <p class="text-xs text-zinc-500">{{ pending.description }}</p>

      <div v-if="pending.time_input === 'snooze'" class="flex flex-wrap gap-2">
        <button
          v-if="allowImmediate"
          class="chip"
          :disabled="disabled"
          @click="submitMoment(new Date())"
        >
          sofort wieder
        </button>
        <button class="chip" :disabled="disabled" @click="submitSnooze(60)">in 1 Stunde</button>
        <button class="chip" :disabled="disabled" @click="submitSnooze(120)">in 2 Stunden</button>
        <button class="chip" :disabled="disabled" @click="submitMoment(tomorrowMorning())">
          morgen früh
        </button>
      </div>

      <div class="flex flex-wrap items-end gap-2">
        <div class="flex flex-col gap-1">
          <label class="text-xs text-zinc-500" :for="timeFieldId">
            {{ pending.time_input === "appointment" ? "Termin" : "eigener Zeitpunkt" }}
          </label>
          <input
            :id="timeFieldId"
            v-model="customTime"
            type="datetime-local"
            class="rounded-md light-grey-background light-grey-stroke px-3 py-2 text-sm outline-none focus:border-blue-500 transition-colors"
          />
        </div>
        <button
          class="rounded-md bg-blue-600 px-4 py-2 text-sm font-medium hover:bg-blue-500 disabled:opacity-40 transition-colors"
          :disabled="disabled || !customTime"
          @click="submitCustom"
        >
          Übernehmen
        </button>
        <button
          class="rounded-md light-grey-background light-grey-stroke px-3 py-2 text-sm hover:text-white transition-colors"
          :disabled="disabled"
          @click="pending = null"
        >
          Abbrechen
        </button>
      </div>
    </div>
  </div>
</template>
