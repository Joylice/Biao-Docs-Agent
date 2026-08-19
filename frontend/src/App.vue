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

// 全局主题：科技简约（主色 #1B6EF3、圆角 6、弱化阴影）
const themeConfig = {
  token: {
    colorPrimary: '#1B6EF3',
    colorSuccess: '#2E7D32',
    colorWarning: '#ED6C02',
    colorError: '#C62828',
    borderRadius: 6,
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
  --app-bg: #f5f7fa;
  --card-bg: #ffffff;
  --color-primary: #1b6ef3;
  --color-warning: #ed6c02;
  --text-primary: rgba(0, 0, 0, 0.88);
  --text-secondary: rgba(0, 0, 0, 0.45);
  --text-disabled: rgba(0, 0, 0, 0.25);
  --border-color: #e8e8e8;
  --bg-block: rgba(27, 110, 243, 0.06);
  --bg-hover: rgba(0, 0, 0, 0.04);
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

/* 卡片 hover 抬升 + 轻阴影（0.2s 过渡，科技简约弱化投影） */
.ant-card-hoverable {
  transition: box-shadow 0.2s ease, transform 0.2s ease;
}

.ant-card-hoverable:hover {
  transform: translateY(-3px);
  box-shadow: 0 6px 16px rgba(27, 110, 243, 0.1);
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
