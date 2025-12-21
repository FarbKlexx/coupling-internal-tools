<script setup lang="ts">

</script>

<template>
  <div class="ml-auto flex items-center gap-3">
    <!-- Inbox -->
    <button
        class="relative rounded-xl border light-grey-stroke light-grey-background hover:bg-zinc-900"
    >
      <svg
          class="h-5 w-5 text-zinc-300"
          fill="none"
          viewBox="0 0 24 24"
          stroke="currentColor"
      >
        <path
            stroke-linecap="round"
            stroke-linejoin="round"
            stroke-width="2"
            d="M7 8h10M7 12h6m5 8H6a2 2 0 01-2-2V5a2 2 0 012-2h12a2 2 0 012 2v13a2 2 0 01-2 2z"
        />
      </svg>

      <!-- Badge -->
      <span
          class="absolute -right-1 -top-1 flex h-5 min-w-[20px] items-center justify-center rounded-full bg-orange-500 px-1 text-[11px] font-semibold text-zinc-950"
      >
            2
          </span>
    </button>

    <!-- Notifications -->
    <button
        class="rounded-xl border border-zinc-800/40 bg-zinc-900/40 p-2 hover:bg-zinc-900"
    >
      <svg
          class="h-5 w-5 text-zinc-300"
          fill="none"
          viewBox="0 0 24 24"
          stroke="currentColor"
      >
        <path
            stroke-linecap="round"
            stroke-linejoin="round"
            stroke-width="2"
            d="M15 17h5l-1.405-1.405A2.032 2.032 0 0118 14.158V11a6.002 6.002 0 00-4-5.659V4a2 2 0 10-4 0v1.341C7.67 6.165 6 8.388 6 11v3.159c0 .538-.214 1.055-.595 1.436L4 17h5"
        />
      </svg>
    </button>

    <!-- Avatar -->
    <button
        class="flex items-center gap-2 rounded-xl border border-zinc-800/40 bg-zinc-900/40 px-3 py-1.5 hover:bg-zinc-900"
    >
      <div
          class="h-8 w-8 rounded-full bg-zinc-700"
      />
      <span class="hidden text-sm font-medium text-zinc-100 sm:block">
            Mariana
          </span>
    </button>
  </div>
</template>

<style scoped>

</style>