<template>
  <div class="placeholder-panel">
    <div class="placeholder-panel__card">
      <h3 class="placeholder-panel__title">{{ title }}</h3>
      <p class="placeholder-panel__desc">{{ desc }}</p>
      <p class="placeholder-panel__hint">该配置面板将在后续任务（T02-T04）中迁移为真实表单</p>
    </div>
  </div>
</template>

<script setup lang="ts">
/**
 * 配置中心占位面板（T01）。
 *
 * configRegistry 各条目在 T02-T04 迁移真实面板（ProviderPanel/StageRoutesPanel/
 * RetrievalPanel/WebSearchPanel/ToolBindingsPanel/RuntimePanel/OverviewPanel）之前，
 * 统一以本组件占位，保证弹窗骨架、两级导航与保存/脏状态链路可先行集成验证。
 */
withDefaults(
  defineProps<{
    /** 条目标题（父级未传时退化为通用文案） */
    title?: string
    /** 条目描述 */
    desc?: string
  }>(),
  { title: '配置条目', desc: '面板迁移中' },
)
</script>

<style scoped>
.placeholder-panel {
  display: flex;
  align-items: center;
  justify-content: center;
  min-height: 100%;
  padding: var(--space-6);
}

.placeholder-panel__card {
  max-width: 480px;
  padding: var(--space-6);
  text-align: center;
  background: var(--bg-surface);
  border: 1px dashed var(--border-color);
  border-radius: var(--radius-lg);
}

.placeholder-panel__title {
  margin: 0;
  font-size: 16px;
  font-weight: 700;
  color: var(--text-primary);
}

.placeholder-panel__desc {
  margin: var(--space-2) 0 0;
  font-size: 13px;
  color: var(--text-secondary);
  line-height: 1.6;
}

.placeholder-panel__hint {
  margin: var(--space-4) 0 0;
  font-size: 12px;
  color: var(--text-tertiary);
}
</style>
