<template>
  <a-modal
    :open="store.visible"
    :width="modalWidth"
    :style="modalStyle"
    wrap-class-name="config-center-modal-wrap"
    :mask-closable="false"
    :keyboard="false"
    @cancel="store.requestClose()"
  >
    <template #title>
      <div class="config-center-modal__title">
        <SettingOutlined class="config-center-modal__title-icon" />
        <span>配置中心</span>
      </div>
    </template>

    <div class="config-center-modal__main">
      <ConfigNav class="config-center-modal__nav" />
      <div class="config-center-modal__content">
        <component
          :is="activePanel"
          v-if="activePanel"
          :key="store.activeItemId ?? 'none'"
          :title="activeEntry?.title"
          :desc="activeEntry?.desc"
          :entry-id="activeEntry?.id ?? null"
        />
      </div>
    </div>

    <template #footer>
      <ConfigFooterBar />
    </template>
  </a-modal>
</template>

<script setup lang="ts">
/**
 * 配置中心弹窗骨架（ARCH §1.3 根组件）。
 *
 * 尺寸与滚动策略（风险点 1）：
 * - 宽 min(1200px, 92vw)、body 高 min(72vh, 720px)（全局样式，见下方非 scoped 块）；
 * - body padding:0 / overflow:hidden，左导航与右内容区各自 overflow-y:auto，
 *   严禁 body 级滚动（否则双滚动条 + footer 不吸底）；
 * - footer 用自定义插槽渲染 ConfigFooterBar（关闭确认走 store.requestClose）。
 *
 * 右侧面板按 registry 条目动态挂载（:is），:key=条目 id 保证条目间状态隔离；
 * 面板迁移（T02-T04）前统一渲染 PlaceholderPanel。
 */
import { computed } from 'vue'
import { SettingOutlined } from '@ant-design/icons-vue'
import { useConfigCenterStore } from '@/stores/configCenter'
import { resolveEntry } from '@/config/configRegistry'
import ConfigNav from './ConfigNav.vue'
import ConfigFooterBar from './ConfigFooterBar.vue'
import PlaceholderPanel from './panels/PlaceholderPanel.vue'

const store = useConfigCenterStore()

const modalWidth = 'min(1200px, 92vw)'
const modalStyle = { top: '6vh', paddingBottom: '0' }

const activeEntry = computed(() => resolveEntry(store.activeItemId))
const activePanel = computed(() => activeEntry.value?.component ?? PlaceholderPanel)
</script>

<style>
/* 非 scoped：Modal 经 portal 渲染至 body，须以 wrap-class-name 全局定位 */
.config-center-modal-wrap .ant-modal-body {
  padding: 0;
  overflow: hidden;
  height: min(72vh, 720px);
}

.config-center-modal-wrap .ant-modal-header {
  padding: 14px 24px;
  border-bottom: 1px solid var(--border-color);
  margin-bottom: 0;
}

.config-center-modal-wrap .config-center-modal__title {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 16px;
  font-weight: 700;
  color: var(--text-primary);
}

.config-center-modal-wrap .config-center-modal__title-icon {
  color: var(--color-primary);
  font-size: 18px;
}

.config-center-modal-wrap .config-center-modal__main {
  display: flex;
  height: 100%;
  min-height: 0;
}

/* 左导航独立滚动 */
.config-center-modal-wrap .config-center-modal__nav {
  width: 240px;
  flex-shrink: 0;
  overflow-y: auto;
  border-right: 1px solid var(--border-color);
  background: var(--bg-surface);
}

/* 右内容区独立滚动 */
.config-center-modal-wrap .config-center-modal__content {
  flex: 1;
  min-width: 0;
  overflow-y: auto;
  padding: var(--space-5);
  background: var(--bg-app);
}

/* 小屏适配（风险点 10）：<1024px 时导航折叠为顶部横向分类条 */
@media (max-width: 1024px) {
  .config-center-modal-wrap .config-center-modal__main {
    flex-direction: column;
  }

  .config-center-modal-wrap .config-center-modal__nav {
    width: 100%;
    flex-shrink: 0;
    max-height: 180px;
    border-right: none;
    border-bottom: 1px solid var(--border-color);
  }
}
</style>
