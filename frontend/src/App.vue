<template>
  <a-config-provider
    :locale="zhCN"
    :theme="themeConfig"
  >
    <router-view v-slot="{ Component, route }">
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
    </router-view>
  </a-config-provider>
</template>

<script setup lang="ts">
import zhCN from 'ant-design-vue/es/locale/zh_CN'
import AppLayout from '@/layouts/AppLayout.vue'

// 全局主题：飞书浅色企业风（主色 #1B6EF3、圆角 6、弱边框 + 轻阴影）
const themeConfig = {
  token: {
    colorPrimary: '#1B6EF3',
    colorSuccess: '#2E7D32',
    colorWarning: '#ED6C02',
    colorError: '#C62828',
    colorBgLayout: '#F7F8FA',
    colorText: '#1F2329',
    colorTextSecondary: '#646A73',
    colorBorderSecondary: '#E5E6EB',
    borderRadius: 6,
    // 卡片/容器内边距收敛至 20px：紧凑信息密度（配合 16px 小卡）
    paddingLG: 20,
    // 弱化默认投影：仅保留贴近表面的轻阴影
    boxShadow:
      '0 1px 2px 0 rgba(0, 0, 0, 0.03), 0 1px 6px -1px rgba(0, 0, 0, 0.02), 0 2px 4px 0 rgba(0, 0, 0, 0.02)',
    boxShadowSecondary: '0 1px 2px 0 rgba(0, 0, 0, 0.03)',
    fontFamily:
      "'Microsoft YaHei', '微软雅黑', 'PingFang SC', 'Helvetica Neue', Arial, sans-serif",
  },
}
</script>

<style>
/* ── 全局设计变量（组件样式一律引用此处，禁止散落硬编码色值） ── */
:root {
  --app-bg: #F7F8FA;
  --card-bg: #FFFFFF;
  --color-primary: #1B6EF3;
  --color-warning: #ED6C02;
  --color-error: #C62828;
  --color-error-bg: rgba(198, 40, 40, 0.05);
  --text-primary: #1F2329;
  --text-secondary: #646A73;
  --text-disabled: rgba(31, 35, 41, 0.35);
  --border-color: #E5E6EB;
  --bg-block: rgba(27, 110, 243, 0.06);
  --bg-hover: rgba(0, 0, 0, 0.04);
  --bg-active: rgba(27, 110, 243, 0.08);
}

html,
body,
#app {
  height: 100%;
}

/* 桌面优先：低于 1280 出现横向滚动，不崩版式 */
#app {
  min-width: 1280px;
}

/* 全局卡片：统一 1px 弱边框 + 圆角 8 + 去重阴影（Notion 风弱边框卡片） */
.ant-card {
  border: 1px solid var(--border-color);
  border-radius: 8px;
  box-shadow: none;
}

/* 卡片 hover 抬升收敛 + 更轻阴影（0.2s 过渡） */
.ant-card-hoverable {
  transition: box-shadow 0.2s ease, transform 0.2s ease;
}

.ant-card-hoverable:hover {
  transform: translateY(-2px);
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.06);
}

/* 表格统一：表头浅灰底（飞书紧凑信息密度） */
.ant-table-thead > tr > th {
  background: var(--app-bg);
}

body {
  margin: 0;
  background: var(--app-bg);
  color: var(--text-primary);
  -webkit-font-smoothing: antialiased;
}

/* 细滚动条 */
::-webkit-scrollbar {
  width: 6px;
  height: 6px;
}

::-webkit-scrollbar-thumb {
  background: rgba(0, 0, 0, 0.2);
  border-radius: 3px;
}

::-webkit-scrollbar-thumb:hover {
  background: rgba(0, 0, 0, 0.3);
}

::-webkit-scrollbar-track {
  background: transparent;
}

/* 路由切换过渡：fade */
.fade-enter-active,
.fade-leave-active {
  transition: opacity 0.2s ease;
}

.fade-enter-from,
.fade-leave-to {
  opacity: 0;
}
</style>
