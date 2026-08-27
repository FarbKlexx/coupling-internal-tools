<script setup lang="ts">
import { computed } from "vue";
import { useRoute } from "vue-router";
import DashboardLayout from "./layouts/DashboardLayout.vue";

const route = useRoute();

/**
 * Die Anmeldeseite bekommt kein Dashboard-Layout.
 *
 * Sidebar und TopBar zeigen Navigation, die ohne angemeldeten Benutzer weder
 * gefüllt noch benutzbar wäre.
 */
const isPublic = computed(() => route.meta.public === true);
</script>

<template>
  <RouterView v-if="isPublic" />
  <DashboardLayout v-else />
</template>
