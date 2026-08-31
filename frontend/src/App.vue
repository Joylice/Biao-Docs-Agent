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
import type { ThemeConfig } from 'ant-design-vue/es/config-provider/context'

const uiStore = useUiStore()

/** Ant Design Vue 主题配置：根据当前模式切换算法 */
const themeConfig = computed<ThemeConfig>(() => ({
  algorithm: uiStore.isDark ? antdTheme.darkAlgorithm : antdTheme.defaultAlgorithm,
  token: {
    // 注意：以下色值为 variables.css 同名 token 的镜像。antd 主题算法需要真实色值
    // 做派生计算（调色板/对比度），无法接受 var(--xxx)，故保留字面量；
    // 修改 variables.css 对应 token 时须同步此处。
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
    // OverrideToken 为全键必选 mapped type，且 DrawerToken 未声明 contentBg/headerBg，
    // 主题覆盖场景下按未知组件 token 断言
  } as unknown as ThemeConfig['components'],
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
/* 全局过渡动画：fade + 轻微上浮（200ms ease-out） */
.fade-enter-active,
.fade-leave-active {
  transition: opacity 200ms ease-out, transform 200ms ease-out;
}
.fade-enter-from,
.fade-leave-to {
  opacity: 0;
  transform: translateY(8px);
}

/* Ant Design Vue 组件深色模式适配覆盖 */
[data-theme='dark'] {
  /* 统一引用 variables.css 深色 token，不再硬编码（--text-tertiary 提亮后此处自动同步） */
  --ant-color-bg-container: var(--bg-surface);
  --ant-color-bg-layout: var(--bg-app);
  --ant-color-bg-spotlight: var(--bg-spotlight);
  --ant-color-text: var(--text-primary);
  --ant-color-text-secondary: var(--text-secondary);
  --ant-color-text-tertiary: var(--text-tertiary);
  --ant-color-border: var(--border-color);
  --ant-color-border-secondary: var(--border-color-light);
  --ant-color-fill: var(--fill);
  --ant-color-fill-secondary: var(--fill-secondary);
  --ant-color-fill-tertiary: var(--fill-tertiary);
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

/* 卡片三级状态样式（供列表/看板等交互态复用）：
   default=常规卡片；hover=加深边框+shadow-md；selected=主色边框+主色浅底 */
.card--default {
  border: 1px solid var(--border-color);
  background: var(--bg-surface);
  box-shadow: var(--shadow-sm);
  transition: border-color var(--transition-fast), box-shadow var(--transition-fast),
    background-color var(--transition-fast);
}
.card--hover {
  border: 1px solid var(--border-color-strong);
  background: var(--bg-surface);
  box-shadow: var(--shadow-md);
  transition: border-color var(--transition-fast), box-shadow var(--transition-fast),
    background-color var(--transition-fast);
}
.card--selected {
  border: 1px solid var(--color-primary);
  background: var(--color-primary-light);
  box-shadow: var(--shadow-md);
  transition: border-color var(--transition-fast), box-shadow var(--transition-fast),
    background-color var(--transition-fast);
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

/* antd cssinjs 会为 .ant-btn:not(:disabled):focus-visible 注入固定色 outline（#2b4059），
   以更高特异性选择器压过（不用 !important），统一为主色焦点环 */
body .ant-btn:not(:disabled):not(.ant-btn-link):focus-visible {
  outline: 2px solid var(--color-primary);
  outline-offset: 2px;
}

/* 按钮按压反馈：轻微缩放。antd cssinjs 的 transition 仅声明在其类选择器上，
   此处以 body 前缀提升特异性补齐 transform 过渡（含原色彩/边框过渡项，不破坏 loading 态） */
body .ant-btn {
  transition: color var(--transition-fast), background-color var(--transition-fast),
    border-color var(--transition-fast), box-shadow var(--transition-fast),
    opacity var(--transition-fast), transform var(--transition-fast);
}
body .ant-btn:not(:disabled):not(.ant-btn-loading):active {
  transform: scale(0.97);
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
  margin: 2px var(--space-2) !important;
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
