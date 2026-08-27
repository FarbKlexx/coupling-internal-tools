<script setup lang="ts">
import { computed, ref } from "vue";
import { useRouter } from "vue-router";
import { changePassword, errorMessage } from "@/api/auth.api";
import { useAuth } from "@/composables/useAuth";

const router = useRouter();
const auth = useAuth();

const currentPassword = ref("");
const newPassword = ref("");
const repeatPassword = ref("");
const showPasswords = ref(false);

const isBusy = ref(false);
const errorText = ref<string | null>(null);
const successText = ref<string | null>(null);

/** Muss zur Richtlinie im Backend passen (`core/security.MIN_PASSWORD_LENGTH`). */
const MIN_LENGTH = 15;

const tooShort = computed(() => newPassword.value !== "" && newPassword.value.length < MIN_LENGTH);
const mismatch = computed(
  () => repeatPassword.value !== "" && newPassword.value !== repeatPassword.value,
);

const canSubmit = computed(
  () =>
    currentPassword.value !== "" &&
    newPassword.value.length >= MIN_LENGTH &&
    newPassword.value === repeatPassword.value &&
    !isBusy.value,
);

/** Erzwungener Wechsel: dann gibt es kein Zurück und keinen Abbrechen-Knopf. */
const isForced = computed(() => auth.mustChangePassword.value);

async function submit() {
  if (!canSubmit.value) return;

  isBusy.value = true;
  errorText.value = null;
  successText.value = null;

  try {
    await changePassword(currentPassword.value, newPassword.value);
    // `must_change_password` ist jetzt weg – der Guard lässt danach durch.
    await auth.refresh();

    currentPassword.value = "";
    newPassword.value = "";
    repeatPassword.value = "";
    successText.value = "Passwort geändert. Alle anderen Sitzungen wurden beendet.";

    if (!auth.mustChangePassword.value) await router.replace("/");
  } catch (error) {
    errorText.value = errorMessage(error, "Passwort konnte nicht geändert werden.");
  } finally {
    isBusy.value = false;
  }
}
</script>

<template>
  <div class="max-w-lg rounded-xl border light-grey-background light-grey-stroke p-6 space-y-5">
    <div class="space-y-1">
      <h2 class="text-lg font-semibold">Passwort ändern</h2>
      <p v-if="isForced" class="text-xs text-amber-300">
        Das Startpasswort muss einmalig gewechselt werden, bevor die Werkzeuge nutzbar sind.
      </p>
      <p v-else class="text-xs text-zinc-500">
        Der Wechsel beendet alle anderen angemeldeten Geräte. Dieses bleibt angemeldet.
      </p>
    </div>

    <form class="space-y-4" @submit.prevent="submit">
      <div class="flex flex-col gap-1">
        <label class="text-sm font-medium" for="pw-current">Aktuelles Passwort</label>
        <input
          id="pw-current"
          v-model="currentPassword"
          :type="showPasswords ? 'text' : 'password'"
          autocomplete="current-password"
          class="rounded-md grey-background light-grey-stroke px-3 py-2 text-sm outline-none focus:border-blue-500 transition-colors"
        />
      </div>

      <div class="flex flex-col gap-1">
        <label class="text-sm font-medium" for="pw-new">Neues Passwort</label>
        <input
          id="pw-new"
          v-model="newPassword"
          :type="showPasswords ? 'text' : 'password'"
          autocomplete="new-password"
          class="rounded-md grey-background light-grey-stroke px-3 py-2 text-sm outline-none focus:border-blue-500 transition-colors"
        />
        <!-- Bewusst nur die Länge als Regel. Zeichenklassen zu verlangen ist
             laut ASVS 6.2.5 verboten, weil es Passwörter schlechter macht. -->
        <p class="text-xs" :class="tooShort ? 'text-red-300' : 'text-zinc-500'">
          Mindestens {{ MIN_LENGTH }} Zeichen. Eine Folge von vier Wörtern ist leichter zu merken
          und sicherer als ein kurzes mit Sonderzeichen.
        </p>
      </div>

      <div class="flex flex-col gap-1">
        <label class="text-sm font-medium" for="pw-repeat">Neues Passwort wiederholen</label>
        <input
          id="pw-repeat"
          v-model="repeatPassword"
          :type="showPasswords ? 'text' : 'password'"
          autocomplete="new-password"
          class="rounded-md grey-background light-grey-stroke px-3 py-2 text-sm outline-none focus:border-blue-500 transition-colors"
        />
        <p v-if="mismatch" class="text-xs text-red-300">
          Die beiden Eingaben stimmen nicht überein.
        </p>
      </div>

      <label class="flex items-center gap-2 text-sm">
        <input v-model="showPasswords" type="checkbox" class="accent-blue-600" />
        <span class="light-grey-text">Passwörter anzeigen</span>
      </label>

      <p
        v-if="errorText"
        class="rounded-md border border-red-500/40 bg-red-500/10 px-3 py-2 text-sm text-red-200"
        role="alert"
      >
        {{ errorText }}
      </p>
      <p
        v-if="successText"
        class="rounded-md border border-emerald-500/40 bg-emerald-500/10 px-3 py-2 text-sm text-emerald-200"
      >
        {{ successText }}
      </p>

      <button
        type="submit"
        :disabled="!canSubmit"
        class="w-full rounded-md bg-blue-600 py-2 font-medium hover:bg-blue-500 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
      >
        {{ isBusy ? "Wird geändert …" : "Passwort ändern" }}
      </button>
    </form>
  </div>
</template>
