/** 审计日志相关 API */
import api from './client'
import type { ApiResponse, PaginatedResponse, PaginationParams } from '@/types'

/** 审计日志项 */
export interface AuditLogItem {
  id: string
  user_id: string
  user_name: string
  action: string
  resource_type: string
  resource_id: string
  details: Record<string, unknown>
  ip_address: string
  user_agent: string
  created_at: string
}

/** 获取审计日志列表 */
export const fetchAuditLogs = (
  params?: PaginationParams & {
    user_id?: string
    action?: string
    resource_type?: string
    start_date?: string
    end_date?: string
  },
) => api.get<ApiResponse<PaginatedResponse<AuditLogItem>>>('/audit-logs', { params })

/** 获取审计日志详情 */
export const fetchAuditLog = (logId: string) =>
  api.get<ApiResponse<AuditLogItem>>(`/audit-logs/${logId}`)

/** 导出审计日志 */
export const exportAuditLogs = (params?: Record<string, unknown>) =>
  api.get('/audit-logs/export', { params, responseType: 'blob' })
