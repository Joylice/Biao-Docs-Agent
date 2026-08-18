import { createRouter, createWebHistory } from 'vue-router'
import type { RouteRecordRaw } from 'vue-router'
import { message } from 'ant-design-vue'
import { currentRole, fetchCurrentUserRole } from '@/stores/currentUser'

const routes: RouteRecordRaw[] = [
  {
    path: '/login',
    name: 'Login',
    component: () => import('@/views/login/LoginView.vue'),
    meta: { public: true },
  },
  {
    path: '/',
    name: 'Projects',
    component: () => import('@/views/projects/ProjectListView.vue'),
    meta: { requiresAuth: true, layout: 'app' },
  },
  {
    // 兼容直接输入 /projects 的场景（守卫未命中不存在的路由会白屏）
    path: '/projects',
    redirect: '/',
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
    meta: { requiresAuth: true, layout: 'app', role: 'admin' },
  },
  {
    path: '/users',
    name: 'Users',
    component: () => import('@/views/users/UsersView.vue'),
    meta: { requiresAuth: true, layout: 'app', role: 'admin' },
  },
  {
    path: '/audit-logs',
    name: 'AuditLogs',
    component: () => import('@/views/audit/AuditLogsView.vue'),
    meta: { requiresAuth: true, layout: 'app', role: 'admin' },
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

// 路由守卫：未登录跳转登录页；已登录访问登录页重定向项目列表；
// meta.role 存在时校验角色（后端 403 兜底，此处仅收敛前端入口体验）
router.beforeEach(async (to) => {
  const token = localStorage.getItem('access_token')
  if (to.meta.requiresAuth && !token) {
    // 携带回跳地址，登录成功后返回原页面
    return { name: 'Login', query: { redirect: to.fullPath } }
  }
  if (to.name === 'Login' && token) {
    return { name: 'Projects' }
  }
  // 角色守卫：模块级角色初始为 member，先刷新再判定，避免误拦截
  if (to.meta.role && currentRole.value !== to.meta.role) {
    await fetchCurrentUserRole()
    if (currentRole.value !== to.meta.role) {
      message.warning('无权访问：该页面仅限管理员')
      return { name: 'Projects' }
    }
  }
  return true
})

export default router
