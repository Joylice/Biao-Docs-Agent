import { createRouter, createWebHistory } from 'vue-router'
import type { RouteRecordRaw } from 'vue-router'

const routes: RouteRecordRaw[] = [
  {
    path: '/login',
    name: 'Login',
    component: () => import('@/views/login/LoginView.vue'),
  },
  {
    path: '/',
    name: 'Projects',
    component: () => import('@/views/projects/ProjectListView.vue'),
    meta: { requiresAuth: true },
  },
  {
    path: '/projects/:projectId',
    name: 'Workspace',
    component: () => import('@/views/workspace/WorkspaceView.vue'),
    meta: { requiresAuth: true },
    children: [
      {
        path: 'kb',
        name: 'KnowledgeBase',
        component: () => import('@/views/kb/KnowledgeBaseView.vue'),
      },
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

// 路由守卫：未登录跳转登录页
router.beforeEach((to, _from, next) => {
  const token = localStorage.getItem('access_token')
  if (to.meta.requiresAuth && !token) {
    next({ name: 'Login' })
  } else {
    next()
  }
})

export default router
