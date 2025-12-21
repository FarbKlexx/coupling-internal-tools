<script setup lang="ts">

</script>

<template>
  <div class="ml-auto flex items-center gap-4">
    <!-- Inbox -->
    <button
        class="relative items-center p-0 m-0 w-8 h-8 rounded-full nav-item"
    >

      <span class="material-symbols-outlined text-lg nav-icon">
        mail
      </span>

      <span class="badge">
        2
      </span>
    </button>

    <!-- Notifications -->
    <button
      class="relative items-center p-0 m-0 w-8 h-8 rounded-full nav-item"
    >

      <span class="material-symbols-outlined text-lg nav-icon">
        notifications
      </span>

      <span class="badge">
        2
      </span>
    </button>

    <!-- Avatar -->
    <button
        class="flex items-center gap-2 rounded-xl"
    >
      <div
          class="h-8 w-8 rounded-full light-grey-background"
      />
    </button>
  </div>
</template>

<style scoped>

</style>