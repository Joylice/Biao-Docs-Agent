<template>
  <div
    class="loading-skeleton"
    :class="{ 'loading-skeleton--multi': columns > 1 }"
  >
    <a-card
      v-for="col in columns"
      :key="col"
      class="loading-skeleton__card"
      :bordered="false"
    >
      <a-skeleton
        active
        :paragraph="{ rows }"
      />
    </a-card>
  </div>
</template>

<script setup lang="ts">
withDefaults(
  defineProps<{
    /** 骨架段落行数 */
    rows?: number
    /** 并行骨架列数 */
    columns?: number
  }>(),
  {
    rows: 4,
    columns: 1,
  },
)
</script>

<style scoped>
.loading-skeleton--multi {
  display: flex;
  gap: 16px;
}

.loading-skeleton--multi .loading-skeleton__card {
  flex: 1;
}
</style>
