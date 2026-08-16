<template>
  <a-layout class="workspace">
    <a-layout-sider
      theme="light"
      :width="200"
    >
      <a-menu
        mode="inline"
        :selected-keys="[$route.path]"
        @click="handleMenuClick"
      >
        <a-menu-item key="kb">
          资料库
        </a-menu-item>
        <a-menu-item key="parse">
          招标解析
        </a-menu-item>
        <a-menu-item key="generate">
          方案生成
        </a-menu-item>
        <a-menu-item key="review">
          审阅
        </a-menu-item>
        <a-menu-item key="settings">
          <template #icon>
            <SettingOutlined />
          </template>
          模型设置
        </a-menu-item>
      </a-menu>
    </a-layout-sider>
    <a-layout-content class="workspace-content">
      <router-view />
    </a-layout-content>
  </a-layout>
</template>

<script setup lang="ts">
import { useRouter, useRoute } from 'vue-router'
import { SettingOutlined } from '@ant-design/icons-vue'

const router = useRouter()
const route = useRoute()

const handleMenuClick = ({ key }: { key: string }) => {
  if (key === 'settings') {
    router.push({ name: 'Settings' })
    return
  }
  router.push({ name: key.charAt(0).toUpperCase() + key.slice(1), params: { projectId: route.params.projectId } })
}
</script>

<style scoped>
.workspace {
  min-height: 100vh;
}
.workspace-content {
  padding: 24px;
  background: #fff;
}
</style>
