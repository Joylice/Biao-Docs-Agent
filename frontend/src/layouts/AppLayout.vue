<template>
  <a-layout class="app-layout">
    <a-layout-header class="app-layout__header">
      <div class="app-layout__brand">
        <span class="app-layout__logo">
          <FileSearchOutlined />
        </span>
        <span class="app-layout__title">投标智能体</span>
      </div>
      <a-dropdown placement="bottomRight">
        <span class="app-layout__user">
          <a-avatar
            :size="28"
            class="app-layout__avatar"
          >
            {{ avatarText }}
          </a-avatar>
          <span class="app-layout__username">{{ displayName }}</span>
          <DownOutlined class="app-layout__caret" />
        </span>
        <template #overlay>
          <a-menu @click="handleUserMenu">
            <a-menu-item key="kb">
              <DatabaseOutlined />
              资料库
            </a-menu-item>
            <a-menu-item
              v-if="isAdmin"
              key="settings"
            >
              <SettingOutlined />
              模型设置
            </a-menu-item>
            <a-menu-item
              v-if="isAdmin"
              key="users"
            >
              <TeamOutlined />
              用户管理
            </a-menu-item>
            <a-menu-item
              v-if="isAdmin"
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
    </a-layout-header>
    <a-layout-content class="app-layout__content">
      <div class="app-layout__page">
        <slot />
      </div>
    </a-layout-content>
  </a-layout>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { message } from 'ant-design-vue'
import {
  AuditOutlined,
  DatabaseOutlined,
  DownOutlined,
  FileSearchOutlined,
  LogoutOutlined,
  SettingOutlined,
  TeamOutlined,
} from '@ant-design/icons-vue'
import api from '@/api/client'
import { isAdmin, setCurrentUser, setRole } from '@/stores/currentUser'

interface CurrentUser {
  id: string
  email: string
  display_name: string
  role?: string
}

const router = useRouter()

const displayName = ref('')
const email = ref('')

const avatarText = computed(() => (displayName.value || email.value || '用').charAt(0).toUpperCase())

const fetchCurrentUser = async () => {
  try {
    const { data } = await api.get('/auth/me')
    if (data.code === 0) {
      const user = data.data as CurrentUser
      displayName.value = user.display_name || user.email
      email.value = user.email
      setRole(user.role)  // 三期：角色写入全局状态，控制管理入口展示
      if (user.id) {
        setCurrentUser(user.id)
      }
    }
  } catch {
    // 401 由 client 拦截器统一清 token 并跳转登录
  }
}

const handleUserMenu = ({ key }: { key: string }) => {
  if (key === 'kb') {
    // 全局资料库独立管理页（不再依赖项目上下文）
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
  height: 56px;
  padding: 0 24px;
  background: #fff;
  box-shadow: 0 1px 4px rgba(0, 0, 0, 0.08);
}

.app-layout__brand {
  display: flex;
  align-items: center;
  gap: 10px;
}

.app-layout__logo {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 32px;
  height: 32px;
  border-radius: 6px;
  background: var(--color-primary);
  color: #fff;
  font-size: 18px;
}

.app-layout__title {
  font-size: 17px;
  font-weight: 600;
  color: var(--text-primary);
}

.app-layout__user {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  padding: 4px 8px;
  border-radius: 6px;
  cursor: pointer;
  transition: background-color 0.2s;
}

.app-layout__user:hover {
  background: var(--bg-hover);
}

.app-layout__avatar {
  background: var(--color-primary);
  color: #fff;
  font-size: 13px;
}

.app-layout__username {
  font-size: 14px;
  color: var(--text-primary);
}

.app-layout__caret {
  font-size: 12px;
  color: var(--text-secondary);
}

.app-layout__content {
  background: var(--app-bg);
}

.app-layout__page {
  max-width: 1200px;
  margin: 0 auto;
  padding: 24px;
}
</style>
