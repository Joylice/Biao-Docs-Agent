/** 项目列表页共享类型 */
export interface ProjectItem {
  id: string
  name: string
  // 后端字段为 snake_case（ProjectOut.tender_no），与创建请求保持一致
  tender_no?: string
  industry?: string
  status?: string
  created_at?: string
  owner_id?: string
}
