<template>
  <a-config-provider
    :locale="zhCN"
    :theme="themeConfig"
  >
    <RouteProgress />
    <GlobalToast />
    <router-view v-slot="{ Component, route }">
      <ErrorBoundary>
        <AppLayout v-if="route.meta.layout === 'app'">
          <transition
            name="fade"
            mode="out-in"
          >
            <component
              :is="Component"
              :key="route.path"
            />
          </transition>
        </AppLayout>
        <transition
          v-else
          name="fade"
          mode="out-in"
        >
          <component
            :is="Component"
            :key="route.path"
          />
        </transition>
      </ErrorBoundary>
    </router-view>
  </a-config-provider>
</template>

<script setup lang="ts">
import { computed, watch } from 'vue'
import zhCN from 'ant-design-vue/es/locale/zh_CN'
import { theme as antdTheme } from 'ant-design-vue'
import AppLayout from '@/layouts/AppLayout.vue'
import GlobalToast from '@/components/common/GlobalToast.vue'
import RouteProgress from '@/components/common/RouteProgress.vue'
import ErrorBoundary from '@/components/common/ErrorBoundary.vue'
import { useUiStore } from '@/stores/ui'

const uiStore = useUiStore()

/** Ant Design Vue 主题配置：根据当前模式切换算法 */
const themeConfig = computed(() => ({
  algorithm: uiStore.isDark ? antdTheme.darkAlgorithm : antdTheme.defaultAlgorithm,
  token: {
    colorPrimary: uiStore.isDark ? '#60a5fa' : '#3b82f6',
    colorSuccess: uiStore.isDark ? '#34d399' : '#10b981',
    colorWarning: uiStore.isDark ? '#fbbf24' : '#f59e0b',
    colorError: uiStore.isDark ? '#f87171' : '#ef4444',
    colorInfo: uiStore.isDark ? '#60a5fa' : '#3b82f6',
    borderRadius: 8,
    fontFamily:
      "'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', 'PingFang SC', 'Hiragino Sans GB', 'Microsoft YaHei', sans-serif",
  },
  components: {
    Layout: {
      bodyBg: 'transparent',
      headerBg: 'transparent',
      siderBg: 'transparent',
    },
    Menu: {
      itemBg: 'transparent',
      subMenuItemBg: 'transparent',
    },
    Card: {
      headerBg: 'transparent',
    },
    Table: {
      headerBg: 'transparent',
      rowHoverBg: 'var(--bg-surface-hover)',
    },
    Modal: {
      contentBg: 'var(--bg-elevated)',
      headerBg: 'var(--bg-elevated)',
    },
    Drawer: {
      contentBg: 'var(--bg-elevated)',
      headerBg: 'var(--bg-elevated)',
    },
    Dropdown: {
      contentBg: 'var(--bg-elevated)',
    },
    Select: {
      optionSelectedBg: 'var(--color-primary-light)',
    },
  },
}))

/** 监听主题变化，确保 html 属性同步 */
watch(
  () => uiStore.theme,
  () => {
    uiStore.init()
  },
)
</script>

<style>
/* 全局过渡动画 */
.fade-enter-active,
.fade-leave-active {
  transition: opacity var(--transition-normal);
}
.fade-enter-from,
.fade-leave-to {
  opacity: 0;
}

/* Ant Design Vue 组件深色模式适配覆盖 */
[data-theme='dark'] {
  --ant-color-bg-container: #111827;
  --ant-color-bg-layout: #0a0e1a;
  --ant-color-bg-spotlight: rgba(255, 255, 255, 0.05);
  --ant-color-text: #f1f5f9;
  --ant-color-text-secondary: #94a3b8;
  --ant-color-text-tertiary: #64748b;
  --ant-color-border: #1e293b;
  --ant-color-border-secondary: #1e293b;
  --ant-color-fill: rgba(255, 255, 255, 0.06);
  --ant-color-fill-secondary: rgba(255, 255, 255, 0.04);
  --ant-color-fill-tertiary: rgba(255, 255, 255, 0.03);
}

/* 卡片统一边框样式 */
.ant-card {
  border: 1px solid var(--border-color);
  border-radius: var(--radius-lg);
  background: var(--bg-surface);
  box-shadow: var(--shadow-sm);
  transition: box-shadow var(--transition-fast), border-color var(--transition-fast);
}
.ant-card-hoverable:hover {
  box-shadow: var(--shadow-md);
  border-color: var(--border-color-strong);
}

/* 表格表头 */
.ant-table-thead > tr > th {
  background: var(--bg-surface-hover) !important;
  color: var(--text-secondary) !important;
  font-weight: 600;
}

/* 按钮基础样式优化 */
.ant-btn {
  border-radius: var(--radius-md);
  font-weight: 500;
}

/* 输入框优化 */
.ant-input,
.ant-input-affix-wrapper {
  border-radius: var(--radius-md);
}

/* 标签优化 */
.ant-tag {
  border-radius: var(--radius-sm);
  font-weight: 500;
}

/* 进度条优化 */
.ant-progress-bg {
  border-radius: var(--radius-full);
}

/* 菜单项优化 */
.ant-menu-item {
  border-radius: var(--radius-md);
  margin: 2px 8px !important;
}
.ant-menu-item-selected {
  background: var(--color-primary-light) !important;
}

/* 抽屉/弹窗背景 */
.ant-drawer-content,
.ant-modal-content {
  background: var(--bg-elevated) !important;
}

/* 下拉菜单背景 */
.ant-dropdown-menu {
  background: var(--bg-elevated) !important;
  border: 1px solid var(--border-color);
  border-radius: var(--radius-lg);
  box-shadow: var(--shadow-lg);
}

/* 时间线/步骤条优化 */
.ant-steps-item-title {
  color: var(--text-primary) !important;
}

/* 空状态优化 */
.ant-empty-description {
  color: var(--text-secondary);
}

/* 警告框优化 */
.ant-alert {
  border-radius: var(--radius-md);
}

/* 徽标优化 */
.ant-badge-status-dot {
  width: 8px;
  height: 8px;
}

/* 头像优化 */
.ant-avatar {
  font-weight: 600;
}

/* 分割线优化 */
.ant-divider {
  border-color: var(--border-color);
}

/* 工具提示优化 */
.ant-tooltip-inner {
  border-radius: var(--radius-md);
  font-size: var(--font-size-sm);
}
</style>
