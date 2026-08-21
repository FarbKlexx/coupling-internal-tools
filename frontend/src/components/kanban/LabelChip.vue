<template>
  <span :class="['label-chip', `label-${label.color}`, label.archived && 'label-chip--archived']">
    {{ label.name }}
    <span v-if="label.archived" class="material-symbols-outlined" style="font-size: 12px">
      archive
    </span>
  </span>
</template>

<script setup lang="ts">
import type { KanbanLabel } from "@/api/kanban.api";

defineProps<{
  label: KanbanLabel;
}>();
</script>
