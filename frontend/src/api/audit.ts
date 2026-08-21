/** 审计日志相关 API */
import api from './client'
import type { ApiResponse, PaginatedResponse, PaginationParams } from '@/types'

/** 审计日志项（对齐后端 audit_service 输出） */
export interface AuditLogItem {
  id: string
  user_id: string
  user_name: string
  action: string
  project_id: string | null
  target_type: string | null
  target_id: string | null
  detail: Record<string, unknown> | null
  created_at: string
}

/** 获取审计日志列表（仅管理员；action 前缀匹配） */
export const fetchAuditLogs = (
  params?: PaginationParams & {
    action?: string
    user_id?: string
    project_id?: string
    target_type?: string
    start?: string
    end?: string
  },
) => api.get<ApiResponse<PaginatedResponse<AuditLogItem>>>('/audit-logs', { params })
