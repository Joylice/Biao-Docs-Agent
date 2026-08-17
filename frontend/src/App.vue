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

// 全局主题：专业商务蓝（与登录页/工作台渐变一致）
const themeConfig = {
  token: {
    colorPrimary: '#1565C0',
    colorSuccess: '#2E7D32',
    colorWarning: '#ED6C02',
    colorError: '#C62828',
    borderRadius: 6,
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
  --color-primary: #1565c0;
  --color-warning: #ed6c02;
  --text-primary: rgba(0, 0, 0, 0.88);
  --text-secondary: rgba(0, 0, 0, 0.45);
  --text-disabled: rgba(0, 0, 0, 0.25);
  --border-color: #e8e8e8;
  --bg-block: rgba(21, 101, 192, 0.06);
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

/* 卡片 hover 抬升 + 阴影（0.2s 过渡） */
.ant-card-hoverable {
  transition: box-shadow 0.2s ease, transform 0.2s ease;
}

.ant-card-hoverable:hover {
  transform: translateY(-3px);
  box-shadow: 0 8px 20px rgba(21, 101, 192, 0.12);
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
