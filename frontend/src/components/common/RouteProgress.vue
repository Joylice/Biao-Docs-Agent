<template>
  <div
    v-if="routeLoading"
    class="route-progress"
    :style="{ width: `${routeProgress}%` }"
  />
</template>

<script setup lang="ts">
import { useUiStore } from '@/stores/ui'

const uiStore = useUiStore()
const routeLoading = uiStore.routeLoading
const routeProgress = uiStore.routeProgress
</script>

<style scoped>
.route-progress {
  position: fixed;
  top: 0;
  left: 0;
  height: 3px;
  background: linear-gradient(90deg, var(--color-primary), var(--color-info));
  z-index: 10000;
  transition: width var(--transition-fast);
  box-shadow: 0 0 8px var(--color-primary);
}
</style>
