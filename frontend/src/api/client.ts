import axios from 'axios'
import { message } from 'ant-design-vue'
import router from '@/router'

const api = axios.create({
  baseURL: '/api/v1',
  timeout: 30000,
})

// 请求拦截器：自动附加 JWT
api.interceptors.request.use((config) => {
  const token = localStorage.getItem('access_token')
  if (token) {
    config.headers.Authorization = `Bearer ${token}`
  }
  return config
})

// 401 跳转防抖：并发请求失败时只触发一次清理与跳转
let redirecting = false

// 响应拦截器：401 统一清理 token 并跳转登录
api.interceptors.response.use(
  (response) => response,
  (error) => {
    if (error.response?.status === 401) {
      const url = error.config?.url || ''
      // 登录/注册接口自身的 401 表示凭证错误，由页面提示，不触发全局跳转
      const isAuthRequest = url.includes('/auth/login') || url.includes('/auth/register')
      if (!isAuthRequest && !redirecting) {
        redirecting = true
        localStorage.removeItem('access_token')
        localStorage.removeItem('refresh_token')
        if (router.currentRoute.value.name !== 'Login') {
          message.warning('登录已过期，请重新登录')
          router
            .push({ name: 'Login' })
            .finally(() => {
              redirecting = false
            })
        } else {
          redirecting = false
        }
      }
    }
    return Promise.reject(error)
  },
)

export default api
