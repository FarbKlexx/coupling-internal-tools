<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import { useRouter } from "vue-router";
import {
  confirmTotpSetup,
  disableTotp,
  errorMessage,
  fetchSessions,
  revokeOtherSessions,
  revokeSession,
  startTotpSetup,
  type SessionInfo,
  type TotpSetup,
} from "@/api/auth.api";
import { useAuth } from "@/composables/useAuth";
import PasswordChangeView from "./PasswordChangeView.vue";

const auth = useAuth();
const router = useRouter();

const sessions = ref<SessionInfo[]>([]);
const sessionError = ref<string | null>(null);
const isBusy = ref(false);

// --- Zweiter Faktor -------------------------------------------------------

const setup = ref<TotpSetup | null>(null);
const confirmCode = ref("");
// ASVS 7.5.1: das Umhaengen eines Faktors verlangt das Passwort.
const confirmPassword = ref("");
const recoveryCodes = ref<string[] | null>(null);
const totpError = ref<string | null>(null);
const disablePassword = ref("");
const showDisable = ref(false);

const totpEnabled = computed(() => auth.user.value?.totp_enabled === true);

async function loadSessions() {
  try {
    sessions.value = await fetchSessions();
    sessionError.value = null;
  } catch (error) {
    sessionError.value = errorMessage(error, "Sitzungen konnten nicht geladen werden.");
  }
}

onMounted(loadSessions);

async function endSession(id: string) {
  isBusy.value = true;
  try {
    sessions.value = await revokeSession(id);
    sessionError.value = null;
  } catch (error) {
    sessionError.value = errorMessage(error, "Sitzung konnte nicht beendet werden.");
  } finally {
    isBusy.value = false;
  }
}

async function endOthers() {
  isBusy.value = true;
  try {
    sessions.value = await revokeOtherSessions();
    sessionError.value = null;
  } catch (error) {
    sessionError.value = errorMessage(error, "Sitzungen konnten nicht beendet werden.");
  } finally {
    isBusy.value = false;
  }
}

async function beginTotp() {
  totpError.value = null;
  recoveryCodes.value = null;
  try {
    setup.value = await startTotpSetup();
  } catch (error) {
    totpError.value = errorMessage(error, "Einrichtung konnte nicht gestartet werden.");
  }
}

async function confirmTotp() {
  if (!setup.value || confirmCode.value.trim() === "" || confirmPassword.value === "") return;

  totpError.value = null;
  try {
    recoveryCodes.value = await confirmTotpSetup(
      setup.value.secret,
      confirmCode.value.trim(),
      confirmPassword.value,
    );
    setup.value = null;
    confirmCode.value = "";
    confirmPassword.value = "";
    await auth.refresh();
  } catch (error) {
    totpError.value = errorMessage(error, "Der Code konnte nicht bestätigt werden.");
  }
}

async function turnOffTotp() {
  totpError.value = null;
  try {
    await disableTotp(disablePassword.value);
    disablePassword.value = "";
    showDisable.value = false;
    recoveryCodes.value = null;
    await auth.refresh();
  } catch (error) {
    totpError.value = errorMessage(error, "Der zweite Faktor konnte nicht entfernt werden.");
  }
}

async function signOut() {
  await auth.logout();
  await router.replace({ name: "login" });
}

/** Zeitpunkte kommen als UTC-ISO an und werden lokal dargestellt. */
function formatMoment(value: string): string {
  return new Date(value).toLocaleString("de-DE", {
    dateStyle: "short",
    timeStyle: "short",
  });
}

/** Aus dem User-Agent das herauslesen, was ein Mensch wiedererkennt. */
function describeDevice(agent: string): string {
  if (!agent) return "Unbekanntes Gerät";

  const browser = /Edg\//.test(agent)
    ? "Edge"
    : /Chrome\//.test(agent)
      ? "Chrome"
      : /Safari\//.test(agent)
        ? "Safari"
        : /Firefox\//.test(agent)
          ? "Firefox"
          : "Browser";

  const system = /Windows/.test(agent)
    ? "Windows"
    : /Mac OS X|Macintosh/.test(agent)
      ? "macOS"
      : /Android/.test(agent)
        ? "Android"
        : /iPhone|iPad/.test(agent)
          ? "iOS"
          : /Linux/.test(agent)
            ? "Linux"
            : "";

  return system ? `${browser} auf ${system}` : browser;
}
</script>

<template>
  <div class="space-y-6">
    <div class="flex items-start justify-between gap-4">
      <div class="space-y-1">
        <h1 class="text-xl font-semibold">Mein Konto</h1>
        <p class="text-xs text-zinc-500">
          Angemeldet als <span class="white-text">{{ auth.user.value?.username }}</span>
          <span v-if="auth.isAdmin.value"> · Administrator</span>
        </p>
      </div>
      <button
        type="button"
        class="rounded-md grey-background light-grey-stroke px-4 py-2 text-sm"
        @click="signOut"
      >
        Abmelden
      </button>
    </div>

    <PasswordChangeView />

    <!-- Zweiter Faktor -->
    <section
      class="max-w-lg rounded-xl border light-grey-background light-grey-stroke p-6 space-y-4"
    >
      <div class="space-y-1">
        <h2 class="text-lg font-semibold">Zwei-Faktor-Authentifizierung</h2>
        <p class="text-xs text-zinc-500">
          Ein Code aus einer Authenticator-App zusätzlich zum Passwort. Das ist der wirksamste
          Einzelschutz für dieses Konto.
        </p>
      </div>

      <p
        v-if="totpError"
        class="rounded-md border border-red-500/40 bg-red-500/10 px-3 py-2 text-sm text-red-200"
        role="alert"
      >
        {{ totpError }}
      </p>

      <!-- Aktiv -->
      <template v-if="totpEnabled">
        <p class="flex items-center gap-2 text-sm text-emerald-300">
          <span class="material-symbols-outlined text-base">verified_user</span>
          Aktiv
        </p>

        <div v-if="recoveryCodes" class="space-y-2">
          <p class="text-xs text-amber-300">
            Diese Wiederherstellungscodes werden nur jetzt angezeigt. Jeder funktioniert genau
            einmal — sicher aufbewahren.
          </p>
          <ul class="grid grid-cols-2 gap-1 rounded-md grey-background p-3 font-mono text-xs">
            <li v-for="code in recoveryCodes" :key="code">{{ code }}</li>
          </ul>
        </div>

        <div v-if="!showDisable">
          <button
            type="button"
            class="rounded-md grey-background light-grey-stroke px-4 py-2 text-sm"
            @click="showDisable = true"
          >
            Zweiten Faktor entfernen
          </button>
        </div>
        <div v-else class="space-y-2">
          <label class="text-sm font-medium" for="totp-off-pw">
            Zur Bestätigung das eigene Passwort
          </label>
          <div class="flex gap-2">
            <input
              id="totp-off-pw"
              v-model="disablePassword"
              type="password"
              autocomplete="current-password"
              class="flex-1 rounded-md grey-background light-grey-stroke px-3 py-2 text-sm outline-none focus:border-blue-500"
            />
            <button
              type="button"
              class="rounded-md bg-red-600/80 px-4 py-2 text-sm font-medium hover:bg-red-600 disabled:opacity-40"
              :disabled="disablePassword === ''"
              @click="turnOffTotp"
            >
              Entfernen
            </button>
            <button
              type="button"
              class="rounded-md grey-background light-grey-stroke px-4 py-2 text-sm"
              @click="((showDisable = false), (disablePassword = ''))"
            >
              Abbrechen
            </button>
          </div>
        </div>
      </template>

      <!-- Einrichtung läuft -->
      <template v-else-if="setup">
        <ol class="space-y-3 text-sm light-grey-text">
          <li>1. QR-Code mit der Authenticator-App scannen.</li>
          <li>
            2. Falls das nicht geht, den Schlüssel eintippen:
            <code class="rounded grey-background px-1 py-0.5 font-mono text-xs">
              {{ setup.secret }}
            </code>
          </li>
          <li>3. Den angezeigten Code und das eigene Passwort eingeben.</li>
        </ol>

        <img
          :src="setup.qr_code_data_uri"
          alt="QR-Code zur Einrichtung"
          class="h-48 w-48 rounded-md bg-white p-2"
        />

        <input
          v-model="confirmCode"
          type="text"
          inputmode="numeric"
          placeholder="123456"
          autocomplete="one-time-code"
          class="w-full rounded-md grey-background light-grey-stroke px-3 py-2 text-sm tracking-widest outline-none focus:border-blue-500"
        />

        <div class="flex gap-2">
          <!-- Das Passwort ist hier keine Zeremonie: ohne diese Pruefung
               koennte jemand mit einer uebernommenen Sitzung den zweiten
               Faktor auf sein eigenes Geraet umhaengen. -->
          <input
            v-model="confirmPassword"
            type="password"
            placeholder="Eigenes Passwort"
            autocomplete="current-password"
            class="flex-1 rounded-md grey-background light-grey-stroke px-3 py-2 text-sm outline-none focus:border-blue-500"
            @keydown.enter.prevent="confirmTotp"
          />
          <button
            type="button"
            class="rounded-md bg-blue-600 px-4 py-2 text-sm font-medium hover:bg-blue-500 disabled:opacity-40"
            :disabled="confirmCode.trim() === '' || confirmPassword === ''"
            @click="confirmTotp"
          >
            Bestätigen
          </button>
          <button
            type="button"
            class="rounded-md grey-background light-grey-stroke px-4 py-2 text-sm"
            @click="((setup = null), (confirmPassword = ''))"
          >
            Abbrechen
          </button>
        </div>
      </template>

      <!-- Nicht eingerichtet -->
      <template v-else>
        <p class="flex items-center gap-2 text-sm text-zinc-400">
          <span class="material-symbols-outlined text-base">shield</span>
          Nicht eingerichtet
        </p>
        <button
          type="button"
          class="rounded-md bg-blue-600 px-4 py-2 text-sm font-medium hover:bg-blue-500"
          @click="beginTotp"
        >
          Jetzt einrichten
        </button>
      </template>
    </section>

    <!-- Sitzungen -->
    <section
      class="max-w-3xl rounded-xl border light-grey-background light-grey-stroke p-6 space-y-4"
    >
      <div class="flex items-start justify-between gap-4">
        <div class="space-y-1">
          <h2 class="text-lg font-semibold">Aktive Sitzungen</h2>
          <p class="text-xs text-zinc-500">
            Jedes angemeldete Gerät. Etwas dabei, das nicht sein soll? Hier beenden und danach das
            Passwort ändern.
          </p>
        </div>
        <button
          type="button"
          class="shrink-0 rounded-md grey-background light-grey-stroke px-4 py-2 text-sm disabled:opacity-40"
          :disabled="isBusy || sessions.length < 2"
          @click="endOthers"
        >
          Alle anderen beenden
        </button>
      </div>

      <p
        v-if="sessionError"
        class="rounded-md border border-red-500/40 bg-red-500/10 px-3 py-2 text-sm text-red-200"
        role="alert"
      >
        {{ sessionError }}
      </p>

      <ul class="divide-y divide-white/5">
        <li
          v-for="session in sessions"
          :key="session.id"
          class="flex items-center justify-between gap-4 py-3"
        >
          <div class="min-w-0 space-y-0.5">
            <p class="truncate text-sm">
              {{ describeDevice(session.user_agent) }}
              <span
                v-if="session.current"
                class="ml-1 rounded bg-emerald-500/15 px-1.5 py-0.5 text-xs text-emerald-300"
              >
                dieses Gerät
              </span>
            </p>
            <p class="text-xs text-zinc-500">
              {{ session.ip }} · zuletzt {{ formatMoment(session.last_seen_at) }} · läuft ab
              {{ formatMoment(session.expires_at) }}
            </p>
          </div>
          <button
            v-if="!session.current"
            type="button"
            class="shrink-0 rounded-md grey-background light-grey-stroke px-3 py-1.5 text-xs disabled:opacity-40"
            :disabled="isBusy"
            @click="endSession(session.id)"
          >
            Beenden
          </button>
        </li>
      </ul>
    </section>
  </div>
</template>
