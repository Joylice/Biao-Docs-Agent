/** 资料库页共享类型与常量（原 MaterialsView 内定义，拆分后各子组件共用） */

export interface Material {
  id: string
  title: string
  doc_type: string
  status: string
  created_at: string
  category?: string | null
  tags?: string[]
  uploader_name?: string
  uploader_id?: string | null
}

export interface SearchItem {
  title: string
  content: string
  score?: number
}

export interface KbBase {
  id: string
  name: string
  description?: string | null
  scope: 'personal' | 'project' | 'company'
  project_id?: string | null
  project_name?: string | null
  owner_id?: string | null
  material_count: number
}

export interface ProjectLite {
  id: string
  name: string
  owner_id: string
}

// 三期 S2：素材分类枚举（与后端 schemas/document.py MATERIAL_CATEGORIES 对齐）
export const categoryOptions = [
  { value: 'product_material', label: '产品资料' },
  { value: 'history_proposal', label: '历史方案' },
  { value: 'qualification', label: '资质证书' },
  { value: 'other', label: '其他' },
]

export const categoryLabel = (value?: string | null) =>
  categoryOptions.find((o) => o.value === value)?.label ?? value ?? ''
