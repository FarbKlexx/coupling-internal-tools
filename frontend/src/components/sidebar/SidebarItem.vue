<template>
  <button
    @click="$emit('select')"
    :class="[
      'flex items-center gap-3 rounded-lg px-1 py-1 text-left transition sidebar-item',
      isActive && 'sidebar-item--active'
    ]"
  >
    <span :class="[
      'material-symbols-outlined nav-icon',
      isActive && 'nav-icon--active',
      ]">
      {{ icon }}
    </span>

    <span :class="[
      'grey-text',
      isActive && 'white-text',
      ]">
      {{ label }}
    </span>
  </button>
</template>

<script setup lang="ts">
defineProps<{
  icon: string;
  label: string;
  isActive?: boolean;
}>();

defineEmits<{
  (e: 'select'): void;
}>();
</script>
