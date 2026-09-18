/**
 * useSkillsConfig：行为准则（SKILL.md 契约）管理逻辑模型（S4）.
 *
 * 🔴 命名沿革：本文件原名对应「外部工具绑定」逻辑（已更名
 * `useToolBindingsConfig.ts`）。SKILL.md 契约体系落地后，本文件接管
 * 「skill」这个名字 —— 管理的是 `api/skills.ts` 暴露的双源注册表：
 *
 * - 内置层（`backend/skills/<目录名>/SKILL.md`）：只读，可被禁用（回退旧 YAML）；
 * - 用户层（DB）：可增删改 + 启停 + zip 导入导出 + 预览渲染。
 *
 * 交互口径（与后端契约逐条对齐，改动前先读 `app/api/skills.py`）：
 * 1. 写操作（create/update/delete/reset）是**即时提交**，无表单 dirty 语义
 *    → registry entry.save 为 no-op；乐观锁 `optimisticVersion` 由后端返回值
 *    回写本行，409 冲突时提示刷新；
 * 2. `enabled=false` 的用户 skill 等于「不生效」（注册表回退内置层），但仍在
 *    列表中可见（`effective=false`），否则用户无法重新启用；
 * 3. 内置层删除/更新一律 403 —— 前端对 `builtin=true` 的行**不渲染**写按钮。
 *
 * 实现为「依赖注入工厂 + 模块级单例」（单测经 createSkillsConfig 注入）。
 */
import { computed, ref, type ComputedRef, type Ref } from 'vue'
import { message } from 'ant-design-vue'
import {
  createSkill,
  deleteSkill,
  getSkills,
  importSkills,
  previewSkill,
  resetSkill,
  updateSkill,
  type SkillCreatePayload,
  type SkillImportItem,
  type SkillListResult,
  type SkillPreviewResult,
  type SkillUpdatePayload,
  type SkillView,
} from '@/api/skills'
import { getApiErrorMessage } from './apiErrorMessage'

/** 预览渲染的单条结果（导入回执复用同一形状） */
export type { SkillImportItem }

export interface SkillsConfigDeps {
  listSkills: () => Promise<SkillListResult>
  doCreate: (payload: SkillCreatePayload) => Promise<SkillView>
  doUpdate: (name: string, payload: SkillUpdatePayload) => Promise<SkillView>
  doDelete: (name: string) => Promise<void>
  doReset: (name: string) => Promise<string>
  doImport: (file: File) => Promise<{ items: SkillImportItem[]; total: number; created: number }>
  doPreview: (bodyMd: string, name?: string) => Promise<SkillPreviewResult>
  notifyError: (msg: string) => void
  notifySuccess: (msg: string) => void
}

export interface SkillsConfigApi {
  loading: Ref<boolean>
  /** 列表原始数据（含 builtinCount/userCount/bodyMaxChars/stageKeys 元信息） */
  result: Ref<SkillListResult | null>
  /** 视图行（computed，面板直接渲染；内置在前、用户在后由后端排序保证） */
  rows: ComputedRef<SkillView[]>
  /** 合法阶段集合（后端下发，避免前端硬编码漂移） */
  stageKeys: ComputedRef<string[]>
  /** 正文长度上限（后端 SKILL_BODY_MAX_CHARS） */
  bodyMaxChars: ComputedRef<number>
  load: () => Promise<void>
  /** 创建（人工创建 → 后端直接启用） */
  create: (payload: SkillCreatePayload) => Promise<boolean>
  /** 更新（三态 + 乐观锁；version 不匹配 → 409，提示刷新） */
  update: (name: string, payload: SkillUpdatePayload) => Promise<boolean>
  /** 启停（乐观锁自动带当前版本；失败不回滚 UI，由调用方重新 load） */
  toggleEnabled: (row: SkillView, enabled: boolean) => Promise<boolean>
  /** 删除（内置行调用必 403，本层不做拦截——由后端为唯一真源） */
  remove: (row: SkillView) => Promise<boolean>
  /** 恢复内置（删除用户层覆盖行） */
  reset: (row: SkillView) => Promise<boolean>
  /** zip 导入；返回逐条回执（created=false 的条目由面板显式呈现） */
  importZip: (file: File) => Promise<SkillImportItem[] | null>
  /** 预览渲染（不落库） */
  preview: (bodyMd: string, name?: string) => Promise<SkillPreviewResult | null>
}

export function createSkillsConfig(deps: SkillsConfigDeps): SkillsConfigApi {
  const {
    listSkills,
    doCreate,
    doUpdate,
    doDelete,
    doReset,
    doImport,
    doPreview,
    notifyError,
    notifySuccess,
  } = deps

  const loading = ref(false)
  const result = ref<SkillListResult | null>(null)

  const rows = computed<SkillView[]>(() => result.value?.items ?? [])
  const stageKeys = computed<string[]>(() => result.value?.stageKeys ?? [])
  const bodyMaxChars = computed<number>(() => result.value?.bodyMaxChars ?? 8000)

  async function load(): Promise<void> {
    loading.value = true
    try {
      result.value = await listSkills()
    } catch (error) {
      notifyError(getApiErrorMessage(error, '加载行为准则失败'))
    } finally {
      loading.value = false
    }
  }

  async function create(payload: SkillCreatePayload): Promise<boolean> {
    try {
      await doCreate(payload)
      notifySuccess(`准则「${payload.title}」已创建`)
      await load()
      return true
    } catch (error) {
      notifyError(getApiErrorMessage(error, '创建失败'))
      return false
    }
  }

  async function update(name: string, payload: SkillUpdatePayload): Promise<boolean> {
    try {
      const updated = await doUpdate(name, payload)
      // 乐观锁版本回写：避免「连续两次保存，第二次带着旧版本 409」
      const row = result.value?.items.find((r) => r.name === name)
      if (row) row.optimisticVersion = updated.optimisticVersion
      notifySuccess('准则已更新')
      return true
    } catch (error) {
      notifyError(getApiErrorMessage(error, '更新失败（若提示冲突请刷新后重试）'))
      return false
    }
  }

  async function toggleEnabled(row: SkillView, enabled: boolean): Promise<boolean> {
    return update(row.name, {
      enabled,
      expected_version: row.optimisticVersion ?? undefined,
    })
  }

  async function remove(row: SkillView): Promise<boolean> {
    try {
      await doDelete(row.name)
      notifySuccess(`准则「${row.title}」已删除`)
      await load()
      return true
    } catch (error) {
      notifyError(getApiErrorMessage(error, '删除失败'))
      return false
    }
  }

  async function reset(row: SkillView): Promise<boolean> {
    try {
      const msg = await doReset(row.name)
      notifySuccess(msg)
      await load()
      return true
    } catch (error) {
      notifyError(getApiErrorMessage(error, '重置失败'))
      return false
    }
  }

  async function importZip(file: File): Promise<SkillImportItem[] | null> {
    try {
      const r = await doImport(file)
      notifySuccess(
        r.created === r.total
          ? `导入完成：共 ${r.total} 条`
          : `导入完成：成功 ${r.created} / 共 ${r.total} 条（同名未覆盖）`,
      )
      await load()
      return r.items
    } catch (error) {
      notifyError(getApiErrorMessage(error, '导入失败'))
      return null
    }
  }

  async function preview(bodyMd: string, name?: string): Promise<SkillPreviewResult | null> {
    try {
      return await doPreview(bodyMd, name)
    } catch (error) {
      notifyError(getApiErrorMessage(error, '预览渲染失败'))
      return null
    }
  }

  return {
    loading,
    result,
    rows,
    stageKeys,
    bodyMaxChars,
    load,
    create,
    update,
    toggleEnabled,
    remove,
    reset,
    importZip,
    preview,
  }
}

/* ---------------- 模块级单例 ---------------- */

let singleton: SkillsConfigApi | null = null

export function useSkillsConfig(): SkillsConfigApi {
  if (!singleton) {
    singleton = createSkillsConfig({
      listSkills: getSkills,
      doCreate: createSkill,
      doUpdate: updateSkill,
      doDelete: deleteSkill,
      doReset: resetSkill,
      doImport: importSkills,
      doPreview: (bodyMd, name) => previewSkill({ body_md: bodyMd, name }),
      notifySuccess: (msg) => message.success(msg),
      notifyError: (msg) => message.error(msg),
    })
  }
  return singleton
}
