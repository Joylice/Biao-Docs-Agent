import { createRouter, createWebHistory } from 'vue-router'
import type { RouteRecordRaw } from 'vue-router'
import { message } from 'ant-design-vue'
import { fetchCurrentUserRole, hasPerm } from '@/stores/currentUser'
import { useUiStore } from '@/stores/ui'

const routes: RouteRecordRaw[] = [
  {
    path: '/login',
    name: 'Login',
    component: () => import('@/views/login/LoginView.vue'),
    meta: { public: true },
  },
  {
    path: '/',
    redirect: { name: 'Workbench' },
  },
  {
    path: '/workbench',
    name: 'Workbench',
    component: () => import('@/views/workbench/WorkbenchView.vue'),
    meta: { requiresAuth: true, layout: 'app' },
  },
  {
    path: '/projects',
    name: 'Projects',
    component: () => import('@/views/projects/ProjectListView.vue'),
    meta: { requiresAuth: true, layout: 'app' },
  },
  {
    path: '/materials',
    name: 'Materials',
    component: () => import('@/views/materials/MaterialsView.vue'),
    meta: { requiresAuth: true, layout: 'app' },
  },
  {
    path: '/settings',
    name: 'Settings',
    component: () => import('@/views/settings/SettingsView.vue'),
    meta: { requiresAuth: true, layout: 'app', perm: 'system:manage' },
  },
  {
    path: '/users',
    name: 'Users',
    component: () => import('@/views/users/UsersView.vue'),
    meta: { requiresAuth: true, layout: 'app', perm: 'system:manage' },
  },
  {
    path: '/audit-logs',
    name: 'AuditLogs',
    component: () => import('@/views/audit/AuditLogsView.vue'),
    meta: { requiresAuth: true, layout: 'app', perm: 'system:manage' },
  },
  {
    path: '/projects/:projectId',
    name: 'Workspace',
    component: () => import('@/views/workspace/WorkspaceView.vue'),
    meta: { requiresAuth: true },
    redirect: { name: 'Parse' },
    children: [
      {
        path: 'parse',
        name: 'Parse',
        component: () => import('@/views/parse/ParseView.vue'),
      },
      {
        path: 'generate',
        name: 'Generate',
        component: () => import('@/views/generate/GenerateView.vue'),
      },
      {
        path: 'review',
        name: 'Review',
        component: () => import('@/views/review/ReviewView.vue'),
      },
      {
        path: 'division',
        name: 'Division',
        component: () => import('@/views/division/DivisionView.vue'),
      },
    ],
  },
]

const router = createRouter({
  history: createWebHistory(),
  routes,
})

// 路由守卫：进度条 + 认证 + 权限
router.beforeEach(async (to) => {
  const uiStore = useUiStore()
  uiStore.startRouteProgress()

  const token = localStorage.getItem('access_token')
  if (to.meta.requiresAuth && !token) {
    return { name: 'Login', query: { redirect: to.fullPath } }
  }
  if (to.name === 'Login' && token) {
    return { name: 'Workbench' }
  }
  if (to.meta.perm) {
    const perm = to.meta.perm as string
    if (!hasPerm(perm)) {
      await fetchCurrentUserRole()
    }
    if (!hasPerm(perm)) {
      message.warning('无权访问：该页面仅限管理员')
      return { name: 'Workbench' }
    }
  }
  return true
})

router.afterEach(() => {
  const uiStore = useUiStore()
  uiStore.finishRouteProgress()
})

router.onError(() => {
  const uiStore = useUiStore()
  uiStore.finishRouteProgress()
})

export default router
