<template>
  <div class="word-toolbar">
    <a-tabs
      v-model:activeKey="activeTab"
      type="card"
      size="small"
    >
      <a-tab-pane key="home" tab="开始">
        <ToolbarHomeTab :editor="editor" />
      </a-tab-pane>

      <a-tab-pane key="insert" tab="插入">
        <ToolbarInsertTab
          :editor="editor"
          :project-id="projectId"
          :upload-image="uploadImage"
          @open-comments="emit('openComments')"
        />
      </a-tab-pane>

      <a-tab-pane key="layout" tab="布局">
        <ToolbarLayoutTab :editor="editor" />
      </a-tab-pane>

      <a-tab-pane key="view" tab="视图">
        <ToolbarViewTab
          @update:outline-visible="emit('update:outlineVisible', $event)"
          @update:zoom="emit('update:zoom', $event)"
        />
      </a-tab-pane>
    </a-tabs>
  </div>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import type { Editor } from '@tiptap/core'
import ToolbarHomeTab from './toolbar/ToolbarHomeTab.vue'
import ToolbarInsertTab from './toolbar/ToolbarInsertTab.vue'
import ToolbarLayoutTab from './toolbar/ToolbarLayoutTab.vue'
import ToolbarViewTab from './toolbar/ToolbarViewTab.vue'

defineProps<{
  /** 编辑器实例（由父组件传入；未就绪时为 undefined） */
  editor: Editor | undefined
  /** 项目 ID（图片上传需要） */
  projectId?: string
  /** 图片上传函数（从 WordEditorPage 注入） */
  uploadImage?: (file: File) => Promise<string>
}>()

const emit = defineEmits<{
  (e: 'update:outlineVisible', value: boolean): void
  (e: 'update:zoom', value: number): void
  (e: 'openComments'): void
}>()

const activeTab = ref<string>('home')
</script>

<style scoped>
.word-toolbar {
  background: var(--bg-surface);
  border-bottom: 1px solid var(--border-color);
}

/* a-tabs card 样式：紧凑 tab 栏 + 无边框内容区 */
.word-toolbar :deep(.ant-tabs-small > .ant-tabs-nav) {
  margin: 0;
  padding: 0 var(--space-2);
}
.word-toolbar :deep(.ant-tabs-card > .ant-tabs-nav::before) {
  border-bottom: none;
}
.word-toolbar :deep(.ant-tabs-card .ant-tabs-tab) {
  background: var(--bg-surface-active);
  border-color: var(--border-color);
}
.word-toolbar :deep(.ant-tabs-card .ant-tabs-tab-active) {
  background: var(--bg-surface);
  border-bottom-color: var(--bg-surface);
}
.word-toolbar :deep(.ant-tabs-content-holder) {
  padding: var(--space-1) var(--space-3);
}
</style>

<!-- 色板弹层渲染在 body 下（teleport），需非 scoped 样式覆盖深色适配 -->
<style>
.word-toolbar-popover .ant-popover-inner {
  background: var(--bg-elevated);
}
</style>
