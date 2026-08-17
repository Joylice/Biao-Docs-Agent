<template>
  <a-layout class="workspace">
    <a-layout-sider
      theme="light"
      :width="200"
      :collapsed="siderCollapsed"
      :collapsed-width="64"
      :trigger="null"
      collapsible
      class="workspace__sider"
    >
      <div class="workspace__project">
        <span class="workspace__project-icon">
          <FolderOutlined />
        </span>
        <div
          v-if="!siderCollapsed"
          class="workspace__project-info"
        >
          <span class="workspace__project-label">当前项目</span>
          <span
            class="workspace__project-name"
            :title="projectName"
          >
            {{ projectName || '加载中…' }}
          </span>
        </div>
        <a-button
          v-if="!siderCollapsed"
          class="workspace__collapse-btn"
          type="text"
          size="small"
          @click="siderCollapsed = true"
        >
          <template #icon>
            <MenuFoldOutlined />
          </template>
        </a-button>
      </div>
      <a-button
        v-if="siderCollapsed"
        class="workspace__expand-btn"
        type="text"
        size="small"
        @click="siderCollapsed = false"
      >
        <template #icon>
          <MenuUnfoldOutlined />
        </template>
      </a-button>
      <a-menu
        mode="inline"
        :selected-keys="selectedKeys"
        :items="menuItems"
        :inline-collapsed="siderCollapsed"
        @click="handleMenuClick"
      />
      <div class="workspace__footer">
        <a-button
          type="text"
          block
          @click="goBackToProjects"
        >
          <template #icon>
            <ArrowLeftOutlined />
          </template>
          <span v-if="!siderCollapsed">返回项目列表</span>
        </a-button>
      </div>
    </a-layout-sider>
    <a-layout-content class="workspace-content">
      <router-view />
    </a-layout-content>
  </a-layout>
</template>

<script setup lang="ts">
import { computed, h, onMounted, ref, watch } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import type { MenuProps } from 'ant-design-vue'
import {
  ArrowLeftOutlined,
  FolderOutlined,
  MenuFoldOutlined,
  MenuUnfoldOutlined,
} from '@ant-design/icons-vue'
import api from '@/api/client'

interface ProjectDetail {
  id: string
  name: string
}

const router = useRouter()
const route = useRoute()
const projectId = route.params.projectId as string

const projectName = ref('')

// 侧栏折叠态持久化（localStorage）
const SIDER_KEY = 'bid.workspace.sider.collapsed'
const siderCollapsed = ref(localStorage.getItem(SIDER_KEY) === '1')
watch(siderCollapsed, (v) => {
  localStorage.setItem(SIDER_KEY, v ? '1' : '0')
})

// 菜单 key → 路由 name 映射（菜单 key 与路由 name 不一致，需显式映射）
const menuRoutes: Record<string, string> = {
  parse: 'Parse',
  generate: 'Generate',
  review: 'Review',
}

// 路由 name → 菜单 key（选中态反查）
const routeMenuKeys: Record<string, string> = {
  Parse: 'parse',
  Generate: 'generate',
  Review: 'review',
}

// 按投标流程步骤先后排列：招标解析 → 方案生成 → 审阅
const menuItems: MenuProps['items'] = [
  {
    key: 'parse',
    icon: () => h('span', { class: 'workspace__step' }, '1'),
    label: '招标解析',
  },
  {
    key: 'generate',
    icon: () => h('span', { class: 'workspace__step' }, '2'),
    label: '方案生成',
  },
  {
    key: 'review',
    icon: () => h('span', { class: 'workspace__step' }, '3'),
    label: '审阅',
  },
]

const selectedKeys = computed(() => {
  const key = routeMenuKeys[String(route.name)]
  return key ? [key] : []
})

const fetchProject = async () => {
  try {
    const { data } = await api.get(`/projects/${projectId}`)
    if (data.code === 0) {
      const project = data.data as ProjectDetail
      projectName.value = project.name
    } else {
      projectName.value = '加载失败'
    }
  } catch {
    // 项目不存在或无权访问：详情接口失败时明确展示失败态，避免静默
    projectName.value = '加载失败'
  }
}

const handleMenuClick = ({ key }: { key: string }) => {
  const name = menuRoutes[key]
  if (!name) return
  router.push({ name, params: { projectId } })
}

const goBackToProjects = () => {
  router.push({ name: 'Projects' })
}

onMounted(fetchProject)
</script>

<style scoped>
.workspace {
  min-height: 100vh;
}

.workspace__sider {
  position: sticky;
  top: 0;
  height: 100vh;
  overflow-y: auto;
  border-right: 1px solid var(--border-color);
}

.workspace__project {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 20px 16px;
  border-bottom: 1px solid var(--border-color);
}

.workspace__collapse-btn {
  margin-left: auto;
  flex-shrink: 0;
  color: var(--text-secondary, #999);
}

.workspace__expand-btn {
  margin-left: auto;
  flex-shrink: 0;
  color: var(--text-secondary, #999);
}

.workspace__project-icon {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 32px;
  height: 32px;
  border-radius: 6px;
  background: var(--color-primary);
  color: #fff;
  font-size: 16px;
  flex-shrink: 0;
}

.workspace__project-info {
  display: flex;
  flex-direction: column;
  min-width: 0;
}

.workspace__project-label {
  font-size: 11px;
  color: var(--text-secondary);
}

.workspace__project-name {
  font-size: 14px;
  font-weight: 600;
  color: var(--text-primary);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.workspace__footer {
  position: absolute;
  bottom: 0;
  left: 0;
  right: 0;
  padding: 12px 8px;
  border-top: 1px solid var(--border-color);
}

.workspace-content {
  padding: 24px;
  background: var(--app-bg);
  min-width: 0;
  display: flex;
  justify-content: center;
}

.workspace-content > * {
  width: 100%;
  max-width: 1100px;
}

.workspace__step {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 22px;
  height: 22px;
  border-radius: 50%;
  background: var(--color-primary);
  color: #fff;
  font-size: 12px;
  font-weight: 600;
  line-height: 1;
}
</style>
