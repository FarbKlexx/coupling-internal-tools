<script setup lang="ts">

</script>

<template>
  <div class="ml-6 flex-1 max-w-xl">
    <div
        class="flex items-center gap-3 rounded-xl border border-zinc-800/40 bg-zinc-900/40 px-4 py-2"
    >
      <svg
          class="h-4 w-4 text-zinc-400"
          fill="none"
          viewBox="0 0 24 24"
          stroke="currentColor"
      >
        <path
            stroke-linecap="round"
            stroke-linejoin="round"
            stroke-width="2"
            d="M21 21l-4.35-4.35m0 0A7.5 7.5 0 1110.5 3a7.5 7.5 0 016.15 13.65z"
        />
      </svg>

      <input
          type="text"
          placeholder="Type to search"
          class="w-full bg-transparent text-sm text-zinc-100 placeholder-zinc-500 focus:outline-none"
      />
    </div>
  </div>
</template>

<style scoped>

</style>