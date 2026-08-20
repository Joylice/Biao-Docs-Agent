/** 项目、项目成员相关类型 */
import type { UserRole } from './user'

/** 项目信息 */
export interface Project {
  id: string
  name: string
  owner_id: string
  tender_no?: string
  industry?: string
  status?: string
  description?: string
  created_at?: string
  updated_at?: string
}

/** 创建项目请求 */
export interface CreateProjectRequest {
  name: string
  tender_no?: string
  industry?: string
  description?: string
  member_ids?: string[]
}

/** 项目成员 */
export interface ProjectMember {
  user_id: string
  email: string
  display_name: string
  is_owner: boolean
  role?: UserRole
  joined_at?: string
}

/** 项目状态中文映射 */
export const PROJECT_STATUS_META: Record<string, { text: string; color: string }> = {
  created: { text: '已创建', color: 'default' },
  parsing: { text: '解析中', color: 'processing' },
  parsed: { text: '已解析', color: 'blue' },
  generating: { text: '生成中', color: 'processing' },
  generated: { text: '已生成', color: 'success' },
  reviewed: { text: '已审阅', color: 'success' },
}

/** 项目状态 → 进度百分比（前端推算，待后端补充真实进度字段） */
export const STATUS_PROGRESS_MAP: Record<string, number> = {
  created: 0,
  parsing: 10,
  parsed: 30,
  generating: 60,
  generated: 85,
  reviewed: 100,
}

/** 行业标签颜色 */
export const INDUSTRY_TAG_COLORS: Record<string, string> = {
  政务: 'blue',
  金融: 'gold',
  能源: 'orange',
  交通: 'purple',
  医疗: 'red',
  教育: 'green',
}
