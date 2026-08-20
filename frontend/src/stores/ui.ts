/** 全局 UI 状态：主题、加载、通知、侧边栏等 */
import { defineStore } from 'pinia'
import { ref, computed } from 'vue'

export type ThemeMode = 'light' | 'dark'

export interface ToastItem {
  id: string
  type: 'success' | 'error' | 'warning' | 'info'
  message: string
  duration?: number
}

export const useUiStore = defineStore('ui', () => {
  /* ---------------- 主题模式 ---------------- */
  const theme = ref<ThemeMode>((localStorage.getItem('bid.theme') as ThemeMode) || 'dark')
  const isDark = computed(() => theme.value === 'dark')

  const setTheme = (mode: ThemeMode) => {
    theme.value = mode
    localStorage.setItem('bid.theme', mode)
    applyTheme(mode)
  }

  const toggleTheme = () => {
    setTheme(theme.value === 'dark' ? 'light' : 'dark')
  }

  /** 应用主题到 document（供 CSS 变量 [data-theme] 选择器使用） */
  const applyTheme = (mode: ThemeMode) => {
    document.documentElement.setAttribute('data-theme', mode)
  }

  /* ---------------- 全局加载态 ---------------- */
  const globalLoading = ref(false)
  const loadingText = ref('')

  const showLoading = (text = '加载中...') => {
    loadingText.value = text
    globalLoading.value = true
  }

  const hideLoading = () => {
    globalLoading.value = false
    loadingText.value = ''
  }

  /* ---------------- Toast 通知 ---------------- */
  const toasts = ref<ToastItem[]>([])

  const showToast = (type: ToastItem['type'], message: string, duration = 3000) => {
    const id = `toast_${Date.now()}_${Math.random().toString(36).slice(2, 8)}`
    toasts.value.push({ id, type, message, duration })
    if (duration > 0) {
      setTimeout(() => removeToast(id), duration)
    }
    return id
  }

  const removeToast = (id: string) => {
    const idx = toasts.value.findIndex((t) => t.id === id)
    if (idx !== -1) toasts.value.splice(idx, 1)
  }

  const toast = {
    success: (msg: string) => showToast('success', msg),
    error: (msg: string) => showToast('error', msg),
    warning: (msg: string) => showToast('warning', msg),
    info: (msg: string) => showToast('info', msg),
  }

  /* ---------------- 侧边栏状态 ---------------- */
  const siderCollapsed = ref(localStorage.getItem('bid.ui.sider.collapsed') === '1')

  const toggleSider = () => {
    siderCollapsed.value = !siderCollapsed.value
    localStorage.setItem('bid.ui.sider.collapsed', siderCollapsed.value ? '1' : '0')
  }

  /* ---------------- 路由进度条 ---------------- */
  const routeProgress = ref(0)
  const routeLoading = ref(false)

  const startRouteProgress = () => {
    routeLoading.value = true
    routeProgress.value = 10
  }

  const setRouteProgress = (value: number) => {
    routeProgress.value = Math.min(value, 90)
  }

  const finishRouteProgress = () => {
    routeProgress.value = 100
    setTimeout(() => {
      routeLoading.value = false
      routeProgress.value = 0
    }, 200)
  }

  /* ---------------- 初始化 ---------------- */
  const init = () => {
    applyTheme(theme.value)
  }

  return {
    theme,
    isDark,
    setTheme,
    toggleTheme,
    globalLoading,
    loadingText,
    showLoading,
    hideLoading,
    toasts,
    showToast,
    removeToast,
    toast,
    siderCollapsed,
    toggleSider,
    routeProgress,
    routeLoading,
    startRouteProgress,
    setRouteProgress,
    finishRouteProgress,
    init,
  }
})
