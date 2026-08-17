<template>
  <div class="page-container">
    <div
      v-if="showHeader"
      class="page-container__header"
    >
      <div class="page-container__heading">
        <a-breadcrumb
          v-if="breadcrumb.length > 0"
          class="page-container__breadcrumb"
        >
          <a-breadcrumb-item
            v-for="item in breadcrumb"
            :key="item.title"
          >
            <router-link
              v-if="item.path"
              :to="item.path"
            >
              {{ item.title }}
            </router-link>
            <span v-else>{{ item.title }}</span>
          </a-breadcrumb-item>
        </a-breadcrumb>
        <h2 class="page-container__title">
          {{ title }}
        </h2>
        <p
          v-if="subtitle"
          class="page-container__subtitle"
        >
          {{ subtitle }}
        </p>
      </div>
      <div
        v-if="$slots.extra"
        class="page-container__extra"
      >
        <slot name="extra" />
      </div>
    </div>
    <div class="page-container__body">
      <slot />
    </div>
  </div>
</template>

<script setup lang="ts">
/** 面包屑项：title 必填，path 可选（有 path 渲染为链接） */
interface BreadcrumbItem {
  title: string
  path?: string
}

withDefaults(
  defineProps<{
    /** 页面标题 */
    title: string
    /** 副标题 */
    subtitle?: string
    /** 可选面包屑 */
    breadcrumb?: BreadcrumbItem[]
    /** 是否渲染标题区（内嵌子页面时置 false） */
    showHeader?: boolean
  }>(),
  {
    subtitle: '',
    breadcrumb: () => [],
    showHeader: true,
  },
)
</script>

<style scoped>
.page-container__header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
  margin-bottom: 16px;
}

.page-container__breadcrumb {
  margin-bottom: 4px;
}

.page-container__title {
  margin: 0;
  font-size: 20px;
  font-weight: 600;
  color: var(--text-primary);
  line-height: 1.4;
}

.page-container__subtitle {
  margin: 4px 0 0;
  font-size: 13px;
  color: var(--text-secondary);
}

.page-container__extra {
  flex-shrink: 0;
}
</style>
