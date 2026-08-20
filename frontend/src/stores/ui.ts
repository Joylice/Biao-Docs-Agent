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

/* ---------------- 持久化键位 ---------------- */
/** 新持久化键（pinia-plugin-persistedstate 写入，JSON） */
const PERSIST_KEY = 'bid.ui'
/** 旧版手写键：仅做一次性迁移 */
const LEGACY_THEME_KEY = 'bid.theme'
const LEGACY_SIDER_KEY = 'bid.ui.sider.collapsed'

export const useUiStore = defineStore(
  'ui',
  () => {
    /* ---------------- 主题模式（深色为默认） ---------------- */
    const theme = ref<ThemeMode>('dark')
    const isDark = computed(() => theme.value === 'dark')

    const setTheme = (mode: ThemeMode) => {
      theme.value = mode
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
    const siderCollapsed = ref(false)

    const toggleSider = () => {
      siderCollapsed.value = !siderCollapsed.value
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

    /**
     * 旧键一次性迁移：插件持久化键（bid.ui）尚不存在、而旧手写键存在时，
     * 将旧值写入 store（赋值会触发插件订阅写入新键），随后删除旧键。
     * 注：插件注水发生在 store 创建时且不触发写入，故此处可安全判定新键缺失。
     */
    const migrateLegacyStorage = () => {
      try {
        if (localStorage.getItem(PERSIST_KEY) !== null) return
        const legacyTheme = localStorage.getItem(LEGACY_THEME_KEY)
        const legacyCollapsed = localStorage.getItem(LEGACY_SIDER_KEY)
        if (legacyTheme === null && legacyCollapsed === null) return
        if (legacyTheme === 'light' || legacyTheme === 'dark') {
          theme.value = legacyTheme
        }
        if (legacyCollapsed !== null) {
          siderCollapsed.value = legacyCollapsed === '1'
        }
        localStorage.removeItem(LEGACY_THEME_KEY)
        localStorage.removeItem(LEGACY_SIDER_KEY)
      } catch {
        // localStorage 不可用（隐私模式等）：静默降级，仅影响持久化迁移
      }
    }

    const init = () => {
      migrateLegacyStorage()
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
  },
  {
    /** pinia-plugin-persistedstate：仅持久化主题与侧边栏折叠态 */
    persist: {
      key: PERSIST_KEY,
      storage: window.localStorage,
      pick: ['theme', 'siderCollapsed'],
    },
  },
)
