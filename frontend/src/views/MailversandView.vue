<template>
  <div class="flex min-w-0 flex-col gap-4">
    <div class="space-y-1">
      <h2 class="text-lg font-semibold">Mailversand</h2>
      <p class="text-xs text-zinc-500">
        Jede Zusage aus der Telefonakquise mit dem, was daraus geworden ist. Ohne Antwort gilt eine
        versendete Mail nach {{ timeoutDays }} Tagen als unbeantwortet – das setzt niemand, das
        ergibt sich aus dem Versanddatum.
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

    <MailFollowupList
      v-model:query="query"
      v-model:state-filter="stateFilter"
      :board="board"
      :actions="actions"
      :timeout-days="timeoutDays"
      :is-loading="isLoading"
      :is-saving="isSaving"
      :filter-by="filterBy"
      :go-to-page="goToPage"
      :save="save"
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
  timeoutDays,
  query,
  stateFilter,
  isLoading,
  isSaving,
  errorMessage,
  load,
  filterBy,
  goToPage,
  save,
} = useMailFollowup();

onMounted(load);
</script>
