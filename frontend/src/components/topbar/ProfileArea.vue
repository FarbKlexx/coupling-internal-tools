<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from "vue";
import { useRouter } from "vue-router";
import { useAuth } from "@/composables/useAuth";

// Mail und Notifications sind weiterhin reine Platzhalter ohne Backend (feste
// Badge-Zahlen, kein Ziel beim Klick). Der Avatar dagegen ist jetzt echt: er
// öffnet das Konto- und Abmeldemenü, das ASVS 7.4.4 verlangt ("auf jeder
// angemeldeten Seite sichtbar erreichbar").
const SHOW_PLACEHOLDER_ACTIONS = false;

const auth = useAuth();
const router = useRouter();

const open = ref(false);
const container = ref<HTMLElement | null>(null);

const initials = computed(() => {
  const name = auth.user.value?.username ?? "";
  const parts = name.split(/[.\-_\s]+/).filter(Boolean);

  const short =
    parts.length >= 2 ? `${parts[0]?.[0] ?? ""}${parts[1]?.[0] ?? ""}` : name.slice(0, 2);

  return short.toUpperCase();
});

function closeOnOutside(event: MouseEvent) {
  if (!container.value?.contains(event.target as Node)) open.value = false;
}

onMounted(() => document.addEventListener("click", closeOnOutside));
onBeforeUnmount(() => document.removeEventListener("click", closeOnOutside));

async function go(name: string) {
  open.value = false;
  await router.push({ name });
}

async function signOut() {
  open.value = false;
  await auth.logout();
  await router.replace({ name: "login" });
}
</script>

<template>
  <!-- Container bleibt bestehen: TopBar ist ein 3-Spalten-Grid, sonst rutscht die Suche aus der Mitte. -->
  <div ref="container" class="relative ml-auto flex items-center gap-4">
    <template v-if="SHOW_PLACEHOLDER_ACTIONS">
      <button class="relative items-center p-0 m-0 w-8 h-8 rounded-full nav-item">
        <span class="material-symbols-outlined text-lg nav-icon"> mail </span>
        <span class="badge"> 2 </span>
      </button>

      <button class="relative items-center p-0 m-0 w-8 h-8 rounded-full nav-item">
        <span class="material-symbols-outlined text-lg nav-icon"> notifications </span>
        <span class="badge"> 2 </span>
      </button>
    </template>

    <button
      v-if="auth.isAuthenticated.value"
      type="button"
      class="flex items-center gap-2 rounded-xl"
      :aria-expanded="open"
      aria-haspopup="menu"
      :aria-label="`Konto von ${auth.user.value?.username}`"
      @click="open = !open"
    >
      <div
        class="flex h-8 w-8 items-center justify-center rounded-full grey-background light-grey-stroke text-xs font-semibold"
      >
        {{ initials }}
      </div>
    </button>

    <div
      v-if="open"
      role="menu"
      class="absolute right-0 top-11 z-50 w-60 overflow-hidden rounded-xl border light-grey-background light-grey-stroke py-1 shadow-xl"
    >
      <div class="border-b light-grey-stroke px-4 py-3">
        <p class="truncate text-sm font-medium">{{ auth.user.value?.username }}</p>
        <p class="text-xs text-zinc-500">
          {{ auth.isAdmin.value ? "Administrator" : "Benutzer" }}
          <span v-if="!auth.user.value?.totp_enabled" class="text-amber-300">
            · ohne zweiten Faktor
          </span>
        </p>
      </div>

      <button
        type="button"
        role="menuitem"
        class="flex w-full items-center gap-2 px-4 py-2 text-left text-sm nav-item"
        @click="go('konto')"
      >
        <span class="material-symbols-outlined text-base nav-icon">account_circle</span>
        Mein Konto
      </button>

      <button
        v-if="auth.isAdmin.value"
        type="button"
        role="menuitem"
        class="flex w-full items-center gap-2 px-4 py-2 text-left text-sm nav-item"
        @click="go('benutzer')"
      >
        <span class="material-symbols-outlined text-base nav-icon">group</span>
        Benutzer verwalten
      </button>

      <button
        type="button"
        role="menuitem"
        class="flex w-full items-center gap-2 border-t light-grey-stroke px-4 py-2 text-left text-sm nav-item"
        @click="signOut"
      >
        <span class="material-symbols-outlined text-base nav-icon">logout</span>
        Abmelden
      </button>
    </div>
  </div>
</template>

<style scoped></style>
