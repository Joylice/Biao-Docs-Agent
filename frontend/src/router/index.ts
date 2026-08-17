import { createRouter, createWebHistory } from 'vue-router'
import type { RouteRecordRaw } from 'vue-router'

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
    meta: { requiresAuth: true, layout: 'app' },
  },
  {
    path: '/users',
    name: 'Users',
    component: () => import('@/views/users/UsersView.vue'),
    meta: { requiresAuth: true, layout: 'app' },
  },
  {
    path: '/audit-logs',
    name: 'AuditLogs',
    component: () => import('@/views/audit/AuditLogsView.vue'),
    meta: { requiresAuth: true, layout: 'app' },
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
    ],
  },
]

const router = createRouter({
  history: createWebHistory(),
  routes,
})

// 路由守卫：未登录跳转登录页；已登录访问登录页重定向项目列表
router.beforeEach((to) => {
  const token = localStorage.getItem('access_token')
  if (to.meta.requiresAuth && !token) {
    // 携带回跳地址，登录成功后返回原页面
    return { name: 'Login', query: { redirect: to.fullPath } }
  }
  if (to.name === 'Login' && token) {
    return { name: 'Projects' }
  }
  return true
})

export default router
