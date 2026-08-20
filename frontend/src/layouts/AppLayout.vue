<template>
  <a-layout class="app-layout">
    <a-layout-header class="app-layout__header">
      <div
        class="app-layout__brand"
        role="button"
        title="返回工作台"
        aria-label="返回工作台"
        @click="router.push({ name: 'Workbench' })"
      >
        <span class="app-layout__logo">
          <FileSearchOutlined />
        </span>
        <span class="app-layout__title">投标智能体</span>
      </div>

      <div class="app-layout__actions">
        <ThemeToggle />
        <a-dropdown placement="bottomRight">
          <span class="app-layout__user">
            <a-avatar
              :size="32"
              class="app-layout__avatar"
            >
              {{ avatarText }}
            </a-avatar>
            <span class="app-layout__username">{{ displayName }}</span>
            <DownOutlined class="app-layout__caret" />
          </span>
          <template #overlay>
            <a-menu @click="handleUserMenu">
              <a-menu-item
                v-if="hasPerm('kb:read')"
                key="kb"
              >
                <DatabaseOutlined />
                资料库
              </a-menu-item>
              <a-menu-item
                v-if="hasPerm('system:manage')"
                key="settings"
              >
                <SettingOutlined />
                模型设置
              </a-menu-item>
              <a-menu-item
                v-if="hasPerm('system:manage')"
                key="users"
              >
                <TeamOutlined />
                用户管理
              </a-menu-item>
              <a-menu-item
                v-if="hasPerm('system:manage')"
                key="audit"
              >
                <AuditOutlined />
                审计日志
              </a-menu-item>
              <a-menu-divider />
              <a-menu-item
                key="logout"
                class="app-layout__logout"
              >
                <LogoutOutlined />
                退出登录
              </a-menu-item>
            </a-menu>
          </template>
        </a-dropdown>
      </div>
    </a-layout-header>

    <a-layout class="app-layout__main">
      <a-layout-sider
        theme="light"
        :width="220"
        :collapsed-width="64"
        :collapsed="uiStore.siderCollapsed"
        breakpoint="lg"
        class="app-layout__sider"
      >
        <a-menu
          theme="light"
          mode="inline"
          :selected-keys="selectedNavKeys"
          :items="navItems"
          @click="handleNavClick"
        />
        <div class="app-layout__sider-footer">
          <a-button
            type="text"
            block
            :aria-label="uiStore.siderCollapsed ? '展开菜单' : '收起菜单'"
            @click="uiStore.toggleSider"
          >
            <template #icon>
              <MenuFoldOutlined v-if="!uiStore.siderCollapsed" />
              <MenuUnfoldOutlined v-else />
            </template>
            <span v-if="!uiStore.siderCollapsed">收起菜单</span>
          </a-button>
        </div>
      </a-layout-sider>

      <a-layout-content class="app-layout__content">
        <div class="app-layout__page">
          <slot />
        </div>
      </a-layout-content>
    </a-layout>
  </a-layout>
</template>

<script setup lang="ts">
import { computed, h, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { message } from 'ant-design-vue'
import type { MenuProps } from 'ant-design-vue'
import {
  AuditOutlined,
  DashboardOutlined,
  DatabaseOutlined,
  DownOutlined,
  FileSearchOutlined,
  FolderOpenOutlined,
  LogoutOutlined,
  MenuFoldOutlined,
  MenuUnfoldOutlined,
  SettingOutlined,
  TeamOutlined,
} from '@ant-design/icons-vue'
import api from '@/api/client'
import { hasPerm, setCurrentPermissions, setCurrentUser, setRole } from '@/stores/currentUser'
import { useUiStore } from '@/stores/ui'
import ThemeToggle from '@/components/common/ThemeToggle.vue'

interface CurrentUser {
  id: string
  email: string
  display_name: string
  role?: string
  permissions?: string[]
}

const router = useRouter()
const route = useRoute()
const uiStore = useUiStore()

const displayName = ref('')
const email = ref('')

const avatarText = computed(() => (displayName.value || email.value || '用').charAt(0).toUpperCase())

/* ---------------- 侧边导航 ---------------- */
const NAV_ROUTES: Record<string, string> = {
  workbench: 'Workbench',
  projects: 'Projects',
  materials: 'Materials',
}

const ROUTE_NAV_KEYS: Record<string, string> = {
  Workbench: 'workbench',
  Projects: 'projects',
  Materials: 'materials',
}

const navItems: MenuProps['items'] = [
  {
    key: 'workbench',
    icon: () => h(DashboardOutlined),
    label: '工作台',
  },
  {
    key: 'projects',
    icon: () => h(FolderOpenOutlined),
    label: '项目列表',
  },
  {
    key: 'materials',
    icon: () => h(DatabaseOutlined),
    label: '资料库',
  },
]

const selectedNavKeys = computed(() => {
  const key = ROUTE_NAV_KEYS[String(route.name)]
  return key ? [key] : []
})

const handleNavClick = ({ key }: { key: string }) => {
  const name = NAV_ROUTES[key]
  if (name) router.push({ name })
}

const fetchCurrentUser = async () => {
  try {
    const { data } = await api.get('/auth/me')
    if (data.code === 0) {
      const user = data.data as CurrentUser
      displayName.value = user.display_name || user.email
      email.value = user.email
      setRole(user.role)
      setCurrentPermissions(user.permissions)
      if (user.id) {
        setCurrentUser(user.id)
      }
    }
  } catch {
    // 401 由 client 拦截器统一处理
  }
}

const handleUserMenu = ({ key }: { key: string }) => {
  if (key === 'kb') {
    router.push({ name: 'Materials' })
  } else if (key === 'settings') {
    router.push({ name: 'Settings' })
  } else if (key === 'users') {
    router.push({ name: 'Users' })
  } else if (key === 'audit') {
    router.push({ name: 'AuditLogs' })
  } else if (key === 'logout') {
    localStorage.removeItem('access_token')
    localStorage.removeItem('refresh_token')
    message.success('已退出登录')
    router.push({ name: 'Login' })
  }
}

onMounted(fetchCurrentUser)
</script>

<style scoped>
.app-layout {
  min-height: 100vh;
}

.app-layout__header {
  position: sticky;
  top: 0;
  z-index: 100;
  display: flex;
  align-items: center;
  justify-content: space-between;
  height: 60px;
  padding: 0 var(--space-6);
  background: var(--bg-surface);
  border-bottom: 1px solid var(--border-color);
  backdrop-filter: blur(12px);
}

.app-layout__brand {
  display: flex;
  align-items: center;
  gap: var(--space-3);
  cursor: pointer;
}

.app-layout__logo {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 36px;
  height: 36px;
  border-radius: var(--radius-lg);
  background: linear-gradient(135deg, var(--color-primary), var(--color-info));
  color: var(--text-inverse);
  font-size: 20px;
  box-shadow: var(--shadow-sm);
}

.app-layout__title {
  font-size: 18px;
  font-weight: 700;
  color: var(--text-primary);
  letter-spacing: -0.01em;
}

.app-layout__actions {
  display: flex;
  align-items: center;
  gap: var(--space-3);
}

.app-layout__user {
  display: inline-flex;
  align-items: center;
  gap: 10px;
  padding: 6px 12px;
  border-radius: var(--radius-lg);
  cursor: pointer;
  transition: background-color var(--transition-fast);
}

.app-layout__user:hover {
  background: var(--bg-surface-hover);
}

.app-layout__avatar {
  background: linear-gradient(135deg, var(--color-primary), var(--color-info));
  color: var(--text-inverse);
  font-size: 14px;
  font-weight: 600;
}

.app-layout__username {
  font-size: 14px;
  font-weight: 500;
  color: var(--text-primary);
}

.app-layout__caret {
  font-size: 12px;
  color: var(--text-tertiary);
}

.app-layout__main {
  background: transparent;
}

.app-layout__sider {
  position: sticky;
  top: 60px;
  height: calc(100vh - 60px);
  overflow-y: auto;
  background: var(--bg-surface);
  border-right: 1px solid var(--border-color);
  display: flex;
  flex-direction: column;
}

.app-layout__sider :deep(.ant-menu) {
  background: transparent;
  flex: 1;
  padding: 12px 0;
}

.app-layout__sider-footer {
  padding: var(--space-2);
  border-top: 1px solid var(--border-color);
}

.app-layout__content {
  background: var(--bg-app);
  min-width: 0;
}

.app-layout__page {
  max-width: var(--content-max-width);
  margin: 0 auto;
  padding: var(--space-6);
}

.app-layout__logout {
  color: var(--color-error);
}
</style>
