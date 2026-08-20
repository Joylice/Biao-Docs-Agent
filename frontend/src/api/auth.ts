/** 认证相关 API */
import api from './client'
import type { ApiResponse, LoginRequest, LoginResponse, CurrentUser } from '@/types'

/** 登录 */
export const login = (data: LoginRequest) =>
  api.post<ApiResponse<LoginResponse>>('/auth/login', data)

/** 注册 */
export const register = (data: { email: string; password: string; display_name: string }) =>
  api.post<ApiResponse<LoginResponse>>('/auth/register', data)

/** 获取当前用户信息 */
export const fetchCurrentUser = () =>
  api.get<ApiResponse<CurrentUser>>('/auth/me')

/** 刷新 token */
export const refreshToken = (refreshToken: string) =>
  api.post<ApiResponse<{ access_token: string; refresh_token: string }>>('/auth/refresh', {
    refresh_token: refreshToken,
  })

/** 登出 */
export const logout = () => api.post<ApiResponse<void>>('/auth/logout')
