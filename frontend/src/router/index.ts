import { createRouter, createWebHistory } from 'vue-router'
import type { RouteRecordRaw } from 'vue-router'
import { message } from 'ant-design-vue'
import { fetchCurrentUserRole, hasPerm } from '@/stores/currentUser'

const routes: RouteRecordRaw[] = [
  {
    path: '/login',
    name: 'Login',
    component: () => import('@/views/login/LoginView.vue'),
    meta: { public: true },
  },
  {
    // 根路径默认进入工作台（子节分工与工作台改版）
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

// 路由守卫：未登录跳转登录页；已登录访问登录页重定向工作台；
// meta.perm 存在时校验功能权限点（后端 403 兜底，此处仅收敛前端入口体验）
router.beforeEach(async (to) => {
  const token = localStorage.getItem('access_token')
  if (to.meta.requiresAuth && !token) {
    // 携带回跳地址，登录成功后返回原页面
    return { name: 'Login', query: { redirect: to.fullPath } }
  }
  if (to.name === 'Login' && token) {
    return { name: 'Workbench' }
  }
  // 权限守卫：刷新页面时权限点可能尚未加载，先 await /auth/me 刷新再判定，避免误拦截
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

export default router
