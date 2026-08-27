<script setup lang="ts">
import { computed, nextTick, ref } from "vue";
import { useRoute, useRouter } from "vue-router";
import { TotpRequired, errorMessage } from "@/api/auth.api";
import { useAuth } from "@/composables/useAuth";

const route = useRoute();
const router = useRouter();
const auth = useAuth();

const username = ref("");
const password = ref("");
const code = ref("");
const showPassword = ref(false);

/** Erst nach der Rückfrage des Servers sichtbar – nicht spekulativ. */
const needsCode = ref(false);
/** Wiederherstellungscode statt App-Code (Telefon weg). */
const useRecoveryCode = ref(false);

const isBusy = ref(false);
const errorText = ref<string | null>(null);

const codeInput = ref<HTMLInputElement | null>(null);

const canSubmit = computed(
  () =>
    username.value.trim() !== "" &&
    password.value !== "" &&
    (!needsCode.value || code.value.trim() !== "") &&
    !isBusy.value,
);

/**
 * Wohin nach der Anmeldung.
 *
 * Nur ein Pfad innerhalb dieser Anwendung. `//fremde-domain` sieht wie ein
 * Pfad aus, ist aber eine protokollrelative URL – deshalb der zweite Test.
 * vue-router wuerde daraus zwar keine echte Weiterleitung machen, aber ein
 * Ziel, das nur *fast* stimmt, ist schwerer zu erkennen als eines, das
 * verworfen wird.
 */
function safeTarget(value: unknown): string {
  if (typeof value !== "string") return "/";
  if (!value.startsWith("/") || value.startsWith("//")) return "/";

  return value;
}

async function submit() {
  if (!canSubmit.value) return;

  isBusy.value = true;
  errorText.value = null;

  try {
    await auth.login({
      username: username.value.trim(),
      password: password.value,
      ...(needsCode.value && !useRecoveryCode.value ? { totp_code: code.value.trim() } : {}),
      ...(needsCode.value && useRecoveryCode.value ? { recovery_code: code.value.trim() } : {}),
    });

    await router.replace(safeTarget(route.query.weiter));
  } catch (error) {
    if (error instanceof TotpRequired) {
      needsCode.value = true;
      errorText.value = null;
      await nextTick();
      codeInput.value?.focus();
      return;
    }

    errorText.value = errorMessage(error, "Anmeldung nicht möglich. Bitte erneut versuchen.");
    code.value = "";
  } finally {
    isBusy.value = false;
  }
}

function switchCodeKind() {
  useRecoveryCode.value = !useRecoveryCode.value;
  code.value = "";
  errorText.value = null;
}
</script>

<template>
  <main class="flex min-h-screen items-center justify-center p-6">
    <form
      class="w-full max-w-sm rounded-xl border light-grey-background light-grey-stroke p-6 space-y-5"
      @submit.prevent="submit"
    >
      <div class="space-y-1">
        <h1 class="text-lg font-semibold">Anmelden</h1>
        <p class="text-xs text-zinc-500">Coupling Internal Tools</p>
      </div>

      <div class="flex flex-col gap-1">
        <label class="text-sm font-medium" for="login-username">Benutzername</label>
        <input
          id="login-username"
          v-model="username"
          type="text"
          name="username"
          autocomplete="username"
          autofocus
          :disabled="needsCode"
          class="rounded-md grey-background light-grey-stroke px-3 py-2 text-sm outline-none focus:border-blue-500 transition-colors disabled:opacity-60"
        />
      </div>

      <div class="flex flex-col gap-1">
        <label class="text-sm font-medium" for="login-password">Passwort</label>
        <div class="flex gap-2">
          <!-- Kein autocomplete="off" und kein Paste-Blocker: Passwortmanager
               sollen greifen (ASVS 6.2.7). -->
          <input
            id="login-password"
            v-model="password"
            :type="showPassword ? 'text' : 'password'"
            name="password"
            autocomplete="current-password"
            :disabled="needsCode"
            class="flex-1 rounded-md grey-background light-grey-stroke px-3 py-2 text-sm outline-none focus:border-blue-500 transition-colors disabled:opacity-60"
          />
          <button
            type="button"
            class="rounded-md grey-background light-grey-stroke px-3 text-sm grey-text"
            :aria-label="showPassword ? 'Passwort verbergen' : 'Passwort anzeigen'"
            @click="showPassword = !showPassword"
          >
            <span class="material-symbols-outlined text-base">
              {{ showPassword ? "visibility_off" : "visibility" }}
            </span>
          </button>
        </div>
      </div>

      <div v-if="needsCode" class="flex flex-col gap-1">
        <label class="text-sm font-medium" for="login-code">
          {{ useRecoveryCode ? "Wiederherstellungscode" : "Code aus der App" }}
        </label>
        <input
          id="login-code"
          ref="codeInput"
          v-model="code"
          type="text"
          :inputmode="useRecoveryCode ? 'text' : 'numeric'"
          autocomplete="one-time-code"
          :placeholder="useRecoveryCode ? 'ABCD1234…' : '123456'"
          class="rounded-md grey-background light-grey-stroke px-3 py-2 text-sm tracking-widest outline-none focus:border-blue-500 transition-colors"
        />
        <button
          type="button"
          class="self-start text-xs text-blue-400 hover:text-blue-300"
          @click="switchCodeKind"
        >
          {{
            useRecoveryCode
              ? "Doch den Code aus der App verwenden"
              : "Kein Zugriff auf die App? Wiederherstellungscode verwenden"
          }}
        </button>
      </div>

      <p
        v-if="errorText"
        class="rounded-md border border-red-500/40 bg-red-500/10 px-3 py-2 text-sm text-red-200"
        role="alert"
      >
        {{ errorText }}
      </p>

      <button
        type="submit"
        :disabled="!canSubmit"
        class="w-full rounded-md bg-blue-600 py-2 font-medium hover:bg-blue-500 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
      >
        {{ isBusy ? "Wird geprüft …" : "Anmelden" }}
      </button>
    </form>
  </main>
</template>
