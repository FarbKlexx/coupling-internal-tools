<template>
  <div class="flex min-w-0 flex-col gap-4">
    <div class="space-y-1">
      <h2 class="text-lg font-semibold">Mailversand</h2>
      <p class="text-xs text-zinc-500">
        Jede Zusage aus der Telefonakquise mit dem, was daraus geworden ist. Bleibt eine versendete
        Mail {{ followupDays }} Tage ohne Antwort, rückt sie in den Reiter „Nachfassen“ – dort wird
        hinterhertelefoniert –, nach {{ timeoutDays }} Tagen gilt sie als unbeantwortet. Beides
        setzt niemand, beides ergibt sich aus dem Versanddatum. Die Marker daneben sagen, wo die
        Website steht – und „Bigger than expected“ als einziger von ihnen etwas über ihren Umfang,
        weshalb er sich mit jedem anderen zusammen setzen lässt. Betriebe ohne Anrufliste kommen
        über „+ Betrieb“ herein: sie werden als Zusage angelegt, mit Protokolleintrag wie jede
        andere.
      </p>
    </div>

    <div
      v-if="errorMessage"
      class="flex items-start justify-between gap-3 rounded-md border border-red-500/40 bg-red-500/10 px-3 py-2 text-sm text-red-200"
    >
      <span>{{ errorMessage }}</span>
      <button
        type="button"
        class="shrink-0 transition-opacity hover:opacity-65"
        @click="errorMessage = null"
      >
        <span class="material-symbols-outlined" style="font-size: 16px">close</span>
      </button>
    </div>

    <MailFollowupList
      v-model:query="query"
      v-model:state-filter="stateFilter"
      v-model:readiness-filter="readinessFilter"
      v-model:oversized-filter="oversizedFilter"
      :board="board"
      :actions="actions"
      :readiness-options="readinessOptions"
      :scope-marker="scopeMarker"
      :timeout-days="timeoutDays"
      :followup-days="followupDays"
      :is-loading="isLoading"
      :is-saving="isSaving"
      :filter-by="filterBy"
      :filter-by-readiness="filterByReadiness"
      :filter-by-scope="filterByScope"
      :go-to-page="goToPage"
      :save="save"
      :submit-contact="submitContact"
      :conflict="conflict"
      :form-error="formError"
    />
  </div>
</template>

<script setup lang="ts">
import { onMounted } from "vue";
import MailFollowupList from "@/components/mail/MailFollowupList.vue";
import { useMailFollowup } from "@/composables/useMailFollowup";

const {
  board,
  actions,
  readinessOptions,
  scopeMarker,
  timeoutDays,
  followupDays,
  query,
  stateFilter,
  readinessFilter,
  oversizedFilter,
  isLoading,
  isSaving,
  errorMessage,
  conflict,
  formError,
  load,
  submitContact,
  filterBy,
  filterByReadiness,
  filterByScope,
  goToPage,
  save,
} = useMailFollowup();

onMounted(load);
</script>
