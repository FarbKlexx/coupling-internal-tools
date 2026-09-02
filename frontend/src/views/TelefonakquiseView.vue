<template>
  <div class="flex min-w-0 flex-col gap-4">
    <div class="space-y-1">
      <h2 class="text-lg font-semibold">Telefonakquise</h2>
      <p class="text-xs text-zinc-500">
        Immer genau ein Betrieb, immer mit dem, was in der Liste steht. Jedes Ergebnis wird
        protokolliert – erst eine Zusage am Telefon erlaubt die E-Mail.
      </p>
    </div>

    <div
      v-if="errorMessage"
      class="flex items-start justify-between gap-3 rounded-md border border-red-500/40 bg-red-500/10 px-3 py-2 text-sm text-red-200"
    >
      <span>{{ errorMessage }}</span>
      <button type="button" class="shrink-0" @click="errorMessage = null">
        <span class="material-symbols-outlined" style="font-size: 16px">close</span>
      </button>
    </div>

    <p v-if="isLoading && !state" class="light-grey-text">Arbeitsstand wird geladen …</p>

    <template v-else>
      <CallWorkbench
        :contact="contact"
        :counters="counters"
        :outcomes="outcomes"
        :next-due-at="state?.next_due_at ?? null"
        :has-lists="activeLists.length > 0"
        :is-saving="isSaving"
        :is-waiting="isWaiting"
        :is-done="isDone"
        @answer="recordOutcome"
      />

      <!-- Steht bewusst *nicht* hinter `isAdmin`: der Fehlklick passiert dem,
           der telefoniert, und ihn dafür auf einen Administrator warten zu
           lassen hieße, dass die falsche Angabe so lange im Nachweis steht.
           Das Backend hält den Endpunkt entsprechend nur hinter der Sitzung. -->
      <CallDecisionLog
        :page="decisions"
        :outcomes="outcomes"
        :is-loading="isDecisionsLoading"
        :is-saving="isSaving"
        :load-more="loadMoreDecisions"
        @correct="correctDecision"
      />

      <!-- Die Listenpflege liegt auf derselben Seite, ist aber nur für
           Administratoren sichtbar; durchgesetzt wird sie im Backend, das die
           Verwaltungsendpunkte hinter `require_admin` hält. -->
      <CallListManager
        v-if="isAdmin"
        v-model:blacklist-query="blacklistQuery"
        :lists="lists"
        :is-saving="isSaving"
        :upload="uploadList"
        :edit="editList"
        :remove="removeList"
        :blacklist="blacklist"
        :blacklist-count="blacklistCount"
        :is-blacklist-loading="isBlacklistLoading"
        :load-blacklist="loadBlacklist"
        :add-to-blacklist="addToBlacklist"
        :upload-blacklist="uploadBlacklist"
        :release-number="releaseNumber"
      />
    </template>
  </div>
</template>

<script setup lang="ts">
import { onMounted } from "vue";
import CallDecisionLog from "@/components/calls/CallDecisionLog.vue";
import CallListManager from "@/components/calls/CallListManager.vue";
import CallWorkbench from "@/components/calls/CallWorkbench.vue";
import { useAuth } from "@/composables/useAuth";
import { useCallList } from "@/composables/useCallList";

const { isAdmin } = useAuth();

const {
  state,
  contact,
  counters,
  outcomes,
  lists,
  activeLists,
  blacklist,
  blacklistCount,
  blacklistQuery,
  isBlacklistLoading,
  decisions,
  isDecisionsLoading,
  isLoading,
  isSaving,
  isWaiting,
  isDone,
  errorMessage,
  load,
  loadBlacklist,
  loadDecisions,
  loadMoreDecisions,
  startPolling,
  recordOutcome,
  correctDecision,
  uploadList,
  editList,
  removeList,
  addToBlacklist,
  uploadBlacklist,
  releaseNumber,
} = useCallList();

onMounted(async () => {
  // Nebeneinander: die Entscheidungsliste ist eine Zugabe und darf den
  // Arbeitsplatz nicht aufhalten.
  await Promise.all([load(), loadDecisions()]);
  // Der Poll holt fällige Wiedervorlagen von selbst herein – ohne ihn müsste
  // jemand die Seite neu laden, um zu sehen, dass wieder etwas zu tun ist.
  startPolling();
});
</script>
