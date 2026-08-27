<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import {
  createUser,
  deleteUser,
  errorMessage,
  fetchPageCatalogue,
  fetchUsers,
  resetUserPassword,
  resetUserTotp,
  revokeUserSessions,
  setUserPages,
  updateUser,
  type PageId,
  type UserSummary,
} from "@/api/auth.api";
import { useAuth } from "@/composables/useAuth";
import { routes } from "@/router";

const auth = useAuth();

const users = ref<UserSummary[]>([]);
const catalogue = ref<PageId[]>([]);
const errorText = ref<string | null>(null);
const isBusy = ref(false);

/** Neu angelegtes oder zurückgesetztes Passwort — wird genau einmal gezeigt. */
const revealed = ref<{ username: string; password: string } | null>(null);

const newUsername = ref("");
const newIsAdmin = ref(false);
const newPages = ref<PageId[]>([]);

/**
 * Beschriftung zu einer Berechtigungs-ID.
 *
 * Kommt aus der Route-Meta, nicht aus dem Backend: dort stehen bewusst nur die
 * IDs, damit deutsche UI-Texte nicht über die Sprachgrenze dupliziert werden.
 */
const labelOf = computed(() => {
  const byId = new Map<string, string>();
  for (const route of routes) {
    if (route.meta?.page) byId.set(route.meta.page, String(route.meta.label ?? route.meta.page));
  }
  return (page: PageId) => byId.get(page) ?? page;
});

/** Katalog in der Reihenfolge der Navigation, nicht in der des Backends. */
const orderedPages = computed(() => {
  const known = new Set(catalogue.value);
  const ordered = routes
    .flatMap((route) => (route.meta?.page ? [route.meta.page] : []))
    .filter((page) => known.has(page));

  // Was das Backend kennt, das Frontend aber (noch) nicht: hinten anhängen,
  // statt es verschwinden zu lassen.
  return [...ordered, ...catalogue.value.filter((page) => !ordered.includes(page))];
});

async function load() {
  try {
    const [list, pages] = await Promise.all([fetchUsers(), fetchPageCatalogue()]);
    users.value = list;
    catalogue.value = pages;
    errorText.value = null;
  } catch (error) {
    errorText.value = errorMessage(error, "Benutzer konnten nicht geladen werden.");
  }
}

onMounted(load);

async function run<T>(action: () => Promise<T>, fallback: string): Promise<T | null> {
  isBusy.value = true;
  errorText.value = null;
  try {
    return await action();
  } catch (error) {
    errorText.value = errorMessage(error, fallback);
    return null;
  } finally {
    isBusy.value = false;
  }
}

function replace(updated: UserSummary) {
  users.value = users.value.map((user) => (user.id === updated.id ? updated : user));
}

async function add() {
  if (newUsername.value.trim() === "") return;

  const created = await run(
    () => createUser(newUsername.value.trim(), newIsAdmin.value, newPages.value),
    "Benutzer konnte nicht angelegt werden.",
  );
  if (!created) return;

  users.value = [...users.value, created.user].sort((a, b) =>
    a.username.localeCompare(b.username, "de"),
  );
  revealed.value = { username: created.user.username, password: created.initial_password };
  newUsername.value = "";
  newIsAdmin.value = false;
  newPages.value = [];
}

async function togglePage(user: UserSummary, page: PageId) {
  const next = user.pages.includes(page)
    ? user.pages.filter((entry) => entry !== page)
    : [...user.pages, page];

  const updated = await run(
    () => setUserPages(user.id, next),
    "Berechtigung konnte nicht gespeichert werden.",
  );
  if (updated) replace(updated);
}

async function toggleAdmin(user: UserSummary) {
  const updated = await run(
    () => updateUser(user.id, { is_admin: !user.is_admin }),
    "Änderung nicht möglich.",
  );
  if (updated) replace(updated);
}

async function toggleActive(user: UserSummary) {
  const updated = await run(
    () => updateUser(user.id, { active: !user.active }),
    "Änderung nicht möglich.",
  );
  if (updated) replace(updated);
}

async function resetPassword(user: UserSummary) {
  if (!confirm(`Passwort von „${user.username}“ zurücksetzen? Alle Sitzungen enden dabei.`)) {
    return;
  }

  const result = await run(
    () => resetUserPassword(user.id),
    "Passwort konnte nicht zurückgesetzt werden.",
  );
  if (!result) return;

  replace(result.user);
  revealed.value = { username: result.user.username, password: result.initial_password };
}

async function resetTotp(user: UserSummary) {
  if (
    !confirm(
      `Zweiten Faktor von „${user.username}“ zurücksetzen? Das ist nur nach persönlicher ` +
        `Rückfrage zulässig — nicht auf Zuruf per Mail oder Telefon.`,
    )
  ) {
    return;
  }

  const updated = await run(
    () => resetUserTotp(user.id),
    "Zweiter Faktor konnte nicht zurückgesetzt werden.",
  );
  if (updated) replace(updated);
}

async function throwOut(user: UserSummary) {
  const updated = await run(
    () => revokeUserSessions(user.id),
    "Sitzungen konnten nicht beendet werden.",
  );
  if (updated) replace(updated);
}

function copyPassword() {
  if (revealed.value) void navigator.clipboard?.writeText(revealed.value.password);
}

async function remove(user: UserSummary) {
  if (!confirm(`„${user.username}“ endgültig löschen?`)) return;

  const done = await run(() => deleteUser(user.id), "Benutzer konnte nicht gelöscht werden.");
  if (done === null) return;

  users.value = users.value.filter((entry) => entry.id !== user.id);
}
</script>

<template>
  <div class="space-y-6">
    <div class="space-y-1">
      <h1 class="text-xl font-semibold">Benutzer</h1>
      <p class="text-xs text-zinc-500">
        Konten anlegen und festlegen, welche Seiten jemand öffnen darf. Administratoren sehen immer
        alles.
      </p>
    </div>

    <p
      v-if="errorText"
      class="rounded-md border border-red-500/40 bg-red-500/10 px-3 py-2 text-sm text-red-200"
      role="alert"
    >
      {{ errorText }}
    </p>

    <!-- Einmalige Passwortanzeige -->
    <div
      v-if="revealed"
      class="rounded-xl border border-amber-500/40 bg-amber-500/10 p-4 space-y-2"
    >
      <p class="text-sm text-amber-200">
        Startpasswort für <span class="font-semibold">{{ revealed.username }}</span> — wird nur
        jetzt angezeigt und muss bei der ersten Anmeldung gewechselt werden.
      </p>
      <div class="flex items-center gap-2">
        <code class="flex-1 rounded-md grey-background px-3 py-2 font-mono text-sm">
          {{ revealed.password }}
        </code>
        <button
          type="button"
          class="rounded-md grey-background light-grey-stroke px-3 py-2 text-sm"
          @click="copyPassword"
        >
          Kopieren
        </button>
        <button
          type="button"
          class="rounded-md grey-background light-grey-stroke px-3 py-2 text-sm"
          @click="revealed = null"
        >
          Verstanden
        </button>
      </div>
    </div>

    <!-- Neues Konto -->
    <section class="rounded-xl border light-grey-background light-grey-stroke p-6 space-y-4">
      <h2 class="text-lg font-semibold">Neues Konto</h2>

      <div class="flex flex-wrap items-end gap-3">
        <div class="flex min-w-56 flex-1 flex-col gap-1">
          <label class="text-sm font-medium" for="new-username">Benutzername</label>
          <input
            id="new-username"
            v-model="newUsername"
            type="text"
            placeholder="vorname.nachname"
            class="rounded-md grey-background light-grey-stroke px-3 py-2 text-sm outline-none focus:border-blue-500"
            @keydown.enter.prevent="add"
          />
        </div>
        <label class="flex items-center gap-2 py-2 text-sm">
          <input v-model="newIsAdmin" type="checkbox" class="accent-blue-600" />
          <span class="light-grey-text">Administrator</span>
        </label>
        <button
          type="button"
          class="rounded-md bg-blue-600 px-4 py-2 text-sm font-medium hover:bg-blue-500 disabled:opacity-40"
          :disabled="newUsername.trim() === '' || isBusy"
          @click="add"
        >
          Anlegen
        </button>
      </div>

      <div v-if="!newIsAdmin" class="space-y-2">
        <span class="text-sm font-medium">Zugriff auf</span>
        <div class="flex flex-wrap gap-2">
          <label
            v-for="page in orderedPages"
            :key="page"
            class="flex items-center gap-2 rounded-md grey-background light-grey-stroke px-3 py-1.5 text-sm"
          >
            <input v-model="newPages" type="checkbox" :value="page" class="accent-blue-600" />
            <span class="light-grey-text">{{ labelOf(page) }}</span>
          </label>
        </div>
      </div>
      <p v-else class="text-xs text-zinc-500">
        Administratoren haben Zugriff auf alle Seiten und auf diese Verwaltung.
      </p>
    </section>

    <!-- Bestehende Konten -->
    <section
      v-for="user in users"
      :key="user.id"
      class="rounded-xl border light-grey-background light-grey-stroke p-6 space-y-4"
      :class="user.active ? '' : 'opacity-60'"
    >
      <div class="flex flex-wrap items-start justify-between gap-3">
        <div class="space-y-1">
          <h3 class="flex items-center gap-2 text-base font-semibold">
            {{ user.username }}
            <span
              v-if="user.id === auth.user.value?.id"
              class="rounded bg-blue-500/15 px-1.5 py-0.5 text-xs text-blue-300"
            >
              das bin ich
            </span>
            <span
              v-if="user.is_admin"
              class="rounded bg-violet-500/15 px-1.5 py-0.5 text-xs text-violet-300"
            >
              Administrator
            </span>
            <span
              v-if="!user.active"
              class="rounded bg-zinc-500/15 px-1.5 py-0.5 text-xs text-zinc-300"
            >
              deaktiviert
            </span>
          </h3>
          <p class="text-xs text-zinc-500">
            {{ user.session_count }} aktive
            {{ user.session_count === 1 ? "Sitzung" : "Sitzungen" }} ·
            <span :class="user.totp_enabled ? 'text-emerald-300' : 'text-amber-300'">
              {{ user.totp_enabled ? "mit zweitem Faktor" : "ohne zweiten Faktor" }}
            </span>
            <span v-if="user.must_change_password"> · Passwortwechsel steht aus</span>
          </p>
        </div>

        <div class="flex flex-wrap gap-2">
          <button
            type="button"
            class="rounded-md grey-background light-grey-stroke px-3 py-1.5 text-xs"
            :disabled="isBusy"
            @click="toggleAdmin(user)"
          >
            {{ user.is_admin ? "Adminrechte entziehen" : "Zum Administrator machen" }}
          </button>
          <button
            type="button"
            class="rounded-md grey-background light-grey-stroke px-3 py-1.5 text-xs"
            :disabled="isBusy"
            @click="toggleActive(user)"
          >
            {{ user.active ? "Deaktivieren" : "Aktivieren" }}
          </button>
          <button
            type="button"
            class="rounded-md grey-background light-grey-stroke px-3 py-1.5 text-xs"
            :disabled="isBusy"
            @click="resetPassword(user)"
          >
            Passwort zurücksetzen
          </button>
          <button
            v-if="user.totp_enabled"
            type="button"
            class="rounded-md grey-background light-grey-stroke px-3 py-1.5 text-xs"
            :disabled="isBusy"
            @click="resetTotp(user)"
          >
            Zweiten Faktor zurücksetzen
          </button>
          <button
            type="button"
            class="rounded-md grey-background light-grey-stroke px-3 py-1.5 text-xs"
            :disabled="isBusy || user.session_count === 0"
            @click="throwOut(user)"
          >
            Überall abmelden
          </button>
          <button
            type="button"
            class="rounded-md border border-red-500/40 px-3 py-1.5 text-xs text-red-300"
            :disabled="isBusy"
            @click="remove(user)"
          >
            Löschen
          </button>
        </div>
      </div>

      <div v-if="!user.is_admin" class="space-y-2">
        <span class="text-sm font-medium">Zugriff auf</span>
        <div class="flex flex-wrap gap-2">
          <label
            v-for="page in orderedPages"
            :key="page"
            class="flex items-center gap-2 rounded-md grey-background light-grey-stroke px-3 py-1.5 text-sm"
          >
            <input
              type="checkbox"
              class="accent-blue-600"
              :checked="user.pages.includes(page)"
              :disabled="isBusy"
              @change="togglePage(user, page)"
            />
            <span class="light-grey-text">{{ labelOf(page) }}</span>
          </label>
        </div>
      </div>
    </section>
  </div>
</template>
