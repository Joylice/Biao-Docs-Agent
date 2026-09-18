/**
 * Skill（行为准则）API — /settings/skills（S4）.
 *
 * 与 `externalTools.ts` 的关键差异：**所有端点仅需登录**（无需 admin）。
 * skill 是「我的行为准则」这种用户级资产（产品口径②B「用户层全员共享」）；
 * 外部工具配的是全局密钥，必须 admin。
 *
 * 双来源约定（后端 `services/skills/registry.py`）：
 * - `builtin: true`  → 来自文件系统 `backend/skills/<name>/SKILL.md`，**只读**；
 * - `builtin: false` → 来自 DB 用户层，可改可删。
 *
 * 三处容易踩的语义（与后端实现逐条对齐，改动前请先读 `app/api/skills.py`）：
 * 1. `enabled=false` 的用户 skill **等于不存在**（注册表回退内置层）——
 *    但列表里仍会返回它，否则用户看不到自己禁用过的准则、也就无法重新启用；
 * 2. 列表比其它端点多两个字段：`effective`（是否真的在注册表里生效）与
 *    `editable`（内置层是否允许被覆盖，由 `user-invocable` 决定）；
 * 3. 同名内置**默认不可改**（403），改动需走 `backend/skills/` 文件。
 */
import api from './client'

/** 后端统一响应包装 */
interface ApiResult<T> {
  code: number
  message?: string
  data: T
}

/** skill 视图（列表项与详情共用形状） */
export interface SkillView {
  name: string
  title: string
  description: string
  version: string
  stageKey: string
  agentId: string | null
  bodyMd: string
  metadata: Record<string, unknown>
  /** 用户层启用态；内置层恒为 true */
  enabled: boolean
  /** 'builtin' | 'user' | 'llm'（来源层，展示用） */
  createdBy: string
  /** 乐观锁版本；内置层为 null */
  optimisticVersion: number | null
  /** 是否内置（内置 = 只读） */
  builtin: boolean
  /** 虚拟路径，用于在 UI 上标识来源层 */
  virtualPath: string
  /** 内置层独有：是否允许被用户覆盖（由 SKILL.md 的 user-invocable 决定） */
  editable?: boolean
  /** 用户层独有：是否与某个内置同名（覆盖关系） */
  shadowsBuiltin?: boolean
  /**
   * 是否**实际生效**（在注册表合并结果里）。
   * 用户层为 false 有两种成因：自身 enabled=false，或被 user-invocable=false 的内置挡住。
   */
  effective: boolean
  updatedAt: string | null
}

/** 列表响应 */
export interface SkillListResult {
  items: SkillView[]
  builtinCount: number
  userCount: number
  /** 正文长度上限（后端 SKILL_BODY_MAX_CHARS，供前端校验与字数提示） */
  bodyMaxChars: number
  /** 合法阶段集合（枚举来源，避免前端硬编码漂移） */
  stageKeys: string[]
}

/** 创建请求（created_by 一律服务端固定 'user'，不由前端指定） */
export interface SkillCreatePayload {
  name: string
  title: string
  description: string
  stage_key: string
  body_md: string
  agent_id?: string
  metadata?: Record<string, unknown>
}

/** 更新请求（三态：未传 = 保持原值；expected_version 不匹配 → 409） */
export interface SkillUpdatePayload {
  title?: string
  description?: string
  body_md?: string
  enabled?: boolean
  metadata?: Record<string, unknown>
  expected_version?: number
}

/** 预览请求（不落库） */
export interface SkillPreviewPayload {
  name?: string
  body_md: string
  stage_key?: string
  title?: string
  description?: string
  context?: Record<string, unknown>
}

/** 预览响应 —— 看最终渲染出的 system/user 提示词 */
export interface SkillPreviewResult {
  name: string
  systemPrompt: string
  userPrompt: string
  systemChars: number
  userChars: number
  /** 'registry'（name 命中注册表）| 'draft'（纯草稿） */
  resolvedFrom: 'registry' | 'draft'
}

/** 导入单条结果 */
export interface SkillImportItem {
  name: string
  created: boolean
  message: string
}

/** 导入响应 —— 单条失败不阻断整包，故逐条回报 */
export interface SkillImportResult {
  items: SkillImportItem[]
  total: number
  created: number
}

export const getSkills = async (): Promise<SkillListResult> => {
  const { data } = await api.get<ApiResult<SkillListResult>>('/settings/skills')
  return data.data
}

export const getSkill = async (name: string): Promise<SkillView> => {
  const { data } = await api.get<ApiResult<SkillView>>(`/settings/skills/${name}`)
  return data.data
}

export const createSkill = async (payload: SkillCreatePayload): Promise<SkillView> => {
  const { data } = await api.post<ApiResult<SkillView>>('/settings/skills', payload)
  return data.data
}

export const updateSkill = async (
  name: string,
  payload: SkillUpdatePayload,
): Promise<SkillView> => {
  const { data } = await api.put<ApiResult<SkillView>>(`/settings/skills/${name}`, payload)
  return data.data
}

export const deleteSkill = async (name: string): Promise<void> => {
  await api.delete<ApiResult<null>>(`/settings/skills/${name}`)
}

/** 「恢复内置」= 删除用户层覆盖（无同名内置时等同删除） */
export const resetSkill = async (name: string): Promise<string> => {
  const { data } = await api.post<ApiResult<null>>(`/settings/skills/${name}/reset`)
  return data.message ?? 'ok'
}

/**
 * 导出为 zip（`<name>/SKILL.md` 结构）.
 *
 * ⚠️ `responseType: 'blob'`：本端点返回二进制流（media_type=application/zip），
 * 用默认的 json 解析会把文件内容当文本读坏。
 * ⚠️ 默认**只导用户层**；内置随代码分发、导出无意义。一条都没有时后端 400。
 */
export const exportSkills = async (includeBuiltin = false): Promise<Blob> => {
  const { data } = await api.get<Blob>('/settings/skills/export', {
    params: { include_builtin: includeBuiltin },
    responseType: 'blob',
  })
  return data
}

/**
 * 从 zip 导入（三重防护见后端 `services/skills/zip_io.py`）.
 *
 * ⚠️ 同名已存在时后端**不覆盖**，逐条回报 `created=false` —— 静默覆盖是
 * 危险默认值（用户导入一份旧包会把线上准则冲掉）。UI 必须把这个区别显式呈现。
 */
export const importSkills = async (file: File): Promise<SkillImportResult> => {
  const form = new FormData()
  form.append('file', file)
  const { data } = await api.post<ApiResult<SkillImportResult>>('/settings/skills/import', form)
  return data.data
}

/** 预览渲染（不落库）—— 看这条准则最终长什么样 */
export const previewSkill = async (payload: SkillPreviewPayload): Promise<SkillPreviewResult> => {
  const { data } = await api.post<ApiResult<SkillPreviewResult>>(
    '/settings/skills/preview',
    payload,
  )
  return data.data
}
