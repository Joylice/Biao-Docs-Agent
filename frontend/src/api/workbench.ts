/** 工作台相关 API */
import api from './client'
import type { ApiResponse, WorkbenchSummary } from '@/types'

/** 获取工作台汇总数据 */
export const fetchWorkbenchSummary = () =>
  api.get<ApiResponse<WorkbenchSummary>>('/workbench/summary')
