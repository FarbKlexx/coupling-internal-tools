<template>
  <button
    class="flex items-center gap-3 rounded-lg px-3 py-2 text-left transition"
  >
    <span class="material-symbols-outlined text-xl">
      {{ icon }}
    </span>

    <span class="text-sm font-medium">
      {{ label }}
    </span>
  </button>
</template>

<script setup lang="ts">
defineProps<{
  icon: string;
  label: string;
}>();
</script>
