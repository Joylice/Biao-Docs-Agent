/**
 * useExternalToolsConfig：网络搜索分类（P1-2）逻辑模型.
 *
 * 逻辑迁移自旧 views/settings/SkillsView.vue 外部工具部分（该文件 T05 下线，
 * 不修改），并按 registry 条目化改造：tavily / brave / searxng 各一个条目
 * （websearch:<preset>），面板按 preset 编辑对应工具行；无行时保存走创建
 * （POST），有行走更新（PUT 带 expected_version 乐观锁，409 → 提示刷新）。
 *
 * 密钥三态语义（与 T02 一致，对齐后端 ToolUpdate）：输入框留空 = 省略 =
 * 保持原值；显式"清除" → 保存携带空串；输入非空 → 携带新值；疑似脱敏串
 * （isMaskedKey，S-1 对齐）拒传。GET 返回的 apiKeyMasked 仅作 placeholder。
 *
 * 阶段绑定：后端 GET /settings/external-tools 已回传 boundStages（工具 → stage_key[]），
 * load() 据此初始化 bindings（首屏即可见已绑关系）；bind/unbind 即时生效并本地同步。
 * 对外以「编制节点」为粒度（stageNodes.STAGE_NODE_GROUPS），落库仍是 stage_key 行；
 * 可绑节点取 stageNodes.BINDABLE_STAGE_NODE_KEYS（「方案导出」无模型调用点，不进绑定）。
 *
 * 实现为「依赖注入工厂 + 模块级单例」（单测经 createExternalToolsConfig 注入）。
 */
import { reactive, ref, type Ref } from 'vue'
import { Modal, message } from 'ant-design-vue'
import {
  bindExternalTool,
  createExternalTool,
  deleteExternalTool,
  getExternalTools,
  testExternalTool,
  unbindExternalTool,
  updateExternalTool,
  type BindPayload,
  type ExternalTool,
} from '@/api/externalTools'
import { BINDABLE_STAGE_NODE_KEYS, STAGE_NODE_GROUPS } from '@/config/stageNodes'
import { getApiErrorMessage } from './apiErrorMessage'
import { isMaskedKey } from './useProvidersConfig'

/** registry 网络搜索条目（preset 白名单；custom 工具不在弹窗 UI 暴露） */
export const WEBSEARCH_PRESETS = ['tavily', 'brave', 'searxng'] as const
export type WebsearchPreset = (typeof WEBSEARCH_PRESETS)[number]

/** 各 preset 默认工具名（创建时预填，用户可改） */
export const PRESET_DEFAULT_NAMES: Record<WebsearchPreset, string> = {
  tavily: 'Tavily Search',
  brave: 'Brave Search',
  searxng: 'SearXNG',
}

/** axios 错误是否为 409 乐观锁冲突 */
export function isConflictError(error: unknown): boolean {
  return (error as { response?: { status?: number } } | null)?.response?.status === 409
}

/** 单 preset 工具表单（keyInput 留空=保持原值） */
export interface ToolPresetForm {
  name: string
  keyInput: string
  keyCleared: boolean
  baseUrl: string
  timeoutMs: number
  maxQueryChars: number
  /** 库内是否已有该 preset 工具行（决定 create/update 分流） */
  exists: boolean
  /** 库内行快照（脏检查基准；exists=false 时为 null） */
  snapshot: {
    name: string
    baseUrl: string
    timeoutMs: number
    maxQueryChars: number
  } | null
  /** 库内行 id/version（update 分流用） */
  rowId: string | null
  version: number
  configured: boolean
  apiKeyMasked: string
}

function freshForm(preset: WebsearchPreset): ToolPresetForm {
  return {
    name: PRESET_DEFAULT_NAMES[preset],
    keyInput: '',
    keyCleared: false,
    baseUrl: '',
    timeoutMs: 10000,
    maxQueryChars: 400,
    exists: false,
    snapshot: null,
    rowId: null,
    version: 0,
    configured: false,
    apiKeyMasked: '',
  }
}

export interface ExternalToolsConfigDeps {
  getTools: () => Promise<ExternalTool[]>
  createTool: (payload: Parameters<typeof createExternalTool>[0]) => Promise<ExternalTool>
  updateTool: (id: string, payload: Parameters<typeof updateExternalTool>[1]) => Promise<ExternalTool>
  deleteTool: (id: string) => Promise<void>
  testTool: (id: string) => Promise<unknown[]>
  bindTool: (id: string, payload: BindPayload) => Promise<unknown>
  unbindTool: (id: string, stageKey: string) => Promise<void>
  /** 删除确认流（resolve false = 取消） */
  confirmDelete: (toolName: string) => Promise<boolean>
  notifyError: (msg: string) => void
  notifySuccess: (msg: string) => void
}

export interface ExternalToolsConfigApi {
  loading: Ref<boolean>
  tools: Ref<ExternalTool[]>
  /** toolId → 绑定的 stage_key[]（load 时由后端 boundStages 初始化） */
  bindings: Ref<Record<string, string[]>>
  /** 各 preset 编辑态表单（key: tavily / brave / searxng） */
  forms: Record<WebsearchPreset, ToolPresetForm>
  load: () => Promise<void>
  getToolByPreset: (preset: WebsearchPreset) => ExternalTool | null
  isDirtyPreset: (preset: WebsearchPreset) => boolean
  savePreset: (preset: WebsearchPreset) => Promise<void>
  clearKey: (preset: WebsearchPreset) => void
  resetKeyClear: (preset: WebsearchPreset) => void
  /** 启停（即时保存，带 expected_version）；成功后本地同步 */
  toggleEnable: (tool: ExternalTool, checked: boolean) => Promise<boolean>
  /** 删除（确认流）；成功后 reload */
  remove: (preset: WebsearchPreset) => Promise<boolean>
  /** 连通性测试；结果经 notify 透出 */
  runTest: (preset: WebsearchPreset) => Promise<boolean>
  /** 绑定/解绑阶段（本地 bindings 记录 + API 调用） */
  bindStage: (tool: ExternalTool, stageKey: string) => Promise<boolean>
  unbindStage: (tool: ExternalTool, stageKey: string) => Promise<boolean>
  /** 绑定/解绑整个编制节点（= 组内全部 stage_key；仅一次成功通知） */
  bindNode: (tool: ExternalTool, nodeKey: string) => Promise<boolean>
  unbindNode: (tool: ExternalTool, nodeKey: string) => Promise<boolean>
}

/** 绑定以「编制节点」为对外粒度；可绑 stage_key 集合由 @/config/stageNodes 的 5 节点决定 */

export function createExternalToolsConfig(deps: ExternalToolsConfigDeps): ExternalToolsConfigApi {
  const {
    getTools,
    createTool,
    updateTool,
    deleteTool,
    testTool,
    bindTool,
    unbindTool,
    confirmDelete,
    notifyError,
    notifySuccess,
  } = deps

  const loading = ref(false)
  const tools = ref<ExternalTool[]>([])
  const bindings = ref<Record<string, string[]>>({})

  const forms = reactive<Record<WebsearchPreset, ToolPresetForm>>({
    tavily: freshForm('tavily'),
    brave: freshForm('brave'),
    searxng: freshForm('searxng'),
  })

  /** 拉取工具列表并按 preset 填充表单（无行 preset 保持 freshForm） */
  async function load(): Promise<void> {
    loading.value = true
    try {
      const rows = await getTools()
      tools.value = rows
      // 首屏即展示已绑关系：由后端 boundStages 初始化（无该字段时为空）
      bindings.value = Object.fromEntries(rows.map((t) => [t.id, [...(t.boundStages ?? [])]]))
      for (const preset of WEBSEARCH_PRESETS) {
        const form = freshForm(preset)
        const row = rows.find((t) => t.preset === preset)
        if (row) {
          form.name = row.name
          form.baseUrl = row.baseUrl
          form.timeoutMs = row.timeoutMs
          form.maxQueryChars = row.maxQueryChars
          form.exists = true
          form.snapshot = { name: row.name, baseUrl: row.baseUrl, timeoutMs: row.timeoutMs, maxQueryChars: row.maxQueryChars }
          form.rowId = row.id
          form.version = row.version
          form.configured = row.configured
          form.apiKeyMasked = row.apiKeyMasked
        }
        forms[preset] = form
      }
    } catch (error) {
      notifyError(getApiErrorMessage(error, '加载外部工具失败'))
    } finally {
      loading.value = false
    }
  }

  function getToolByPreset(preset: WebsearchPreset): ExternalTool | null {
    return tools.value.find((t) => t.preset === preset) ?? null
  }

  function isDirtyPreset(preset: WebsearchPreset): boolean {
    const form = forms[preset]
    if (form.keyCleared) return true
    if (form.keyInput.trim() !== '') return true
    if (!form.exists) {
      // 无行：任何非默认输入即视为改动
      return (
        form.name !== PRESET_DEFAULT_NAMES[preset] ||
        form.baseUrl.trim() !== '' ||
        form.timeoutMs !== 10000 ||
        form.maxQueryChars !== 400
      )
    }
    const snap = form.snapshot
    return (
      form.name !== snap!.name ||
      form.baseUrl !== snap!.baseUrl ||
      form.timeoutMs !== snap!.timeoutMs ||
      form.maxQueryChars !== snap!.maxQueryChars
    )
  }

  /** 保存单 preset 条目：无行 → 创建；有行 → 更新（expected_version 乐观锁） */
  async function savePreset(preset: WebsearchPreset): Promise<void> {
    const form = forms[preset]
    let keyPayload: string | undefined
    if (form.keyCleared) {
      keyPayload = ''
    } else if (form.keyInput.trim() !== '') {
      const key = form.keyInput.trim()
      if (isMaskedKey(key)) {
        throw new Error('API Key 疑似脱敏串，请填写真实密钥')
      }
      keyPayload = key
    }
    if (form.exists) {
      try {
        const updated = await updateTool(form.rowId!, {
          name: form.name.trim(),
          base_url: form.baseUrl.trim(),
          timeout_ms: form.timeoutMs,
          max_query_chars: form.maxQueryChars,
          expected_version: form.version,
          ...(keyPayload !== undefined ? { api_key: keyPayload } : {}),
        })
        // 同步版本号（乐观锁推进），避免连续保存 409
        form.version = updated.version
      } catch (error) {
        if (isConflictError(error)) {
          throw new Error('配置已被他人修改，请刷新后重试')
        }
        throw new Error(getApiErrorMessage(error, '保存外部工具失败'))
      }
    } else {
      try {
        await createTool({
          name: form.name.trim() || PRESET_DEFAULT_NAMES[preset],
          preset,
          base_url: form.baseUrl.trim() || undefined,
          timeout_ms: form.timeoutMs,
          max_query_chars: form.maxQueryChars,
          ...(keyPayload !== undefined && keyPayload !== '' ? { api_key: keyPayload } : {}),
        })
      } catch (error) {
        throw new Error(getApiErrorMessage(error, '创建外部工具失败'))
      }
    }
    await load()
  }

  function clearKey(preset: WebsearchPreset): void {
    forms[preset].keyInput = ''
    forms[preset].keyCleared = true
  }

  function resetKeyClear(preset: WebsearchPreset): void {
    forms[preset].keyCleared = false
  }

  /** 启停（即时保存，带 expected_version）；失败返回 false（开关 UI 由调用方回滚） */
  async function toggleEnable(tool: ExternalTool, checked: boolean): Promise<boolean> {
    try {
      const updated = await updateTool(tool.id, { enabled: checked, expected_version: tool.version })
      tool.enabled = updated.enabled
      tool.version = updated.version
      notifySuccess(checked ? '工具已启用' : '工具已禁用')
      return true
    } catch (error) {
      notifyError(
        isConflictError(error) ? '配置已被他人修改，请刷新后重试' : getApiErrorMessage(error, '更新失败'),
      )
      return false
    }
  }

  /** 删除（确认流）；成功后 reload（绑定关系 CASCADE 由后端处理） */
  async function remove(preset: WebsearchPreset): Promise<boolean> {
    const tool = getToolByPreset(preset)
    if (!tool) return false
    if (!(await confirmDelete(tool.name))) return false
    try {
      await deleteTool(tool.id)
      notifySuccess('工具已删除')
      await load()
      return true
    } catch (error) {
      notifyError(getApiErrorMessage(error, '删除失败'))
      return false
    }
  }

  /** 连通性测试；结果数组首项含 error 视为失败（沿用旧 view 口径） */
  async function runTest(preset: WebsearchPreset): Promise<boolean> {
    const tool = getToolByPreset(preset)
    if (!tool) {
      notifyError('尚未创建该工具，请先保存')
      return false
    }
    try {
      const result = await testTool(tool.id)
      const first = Array.isArray(result) ? (result[0] as Record<string, unknown> | undefined) : undefined
      if (first && typeof first === 'object' && 'error' in first) {
        notifyError(`测试失败：${String(first.error)}`)
        return false
      }
      notifySuccess(`${tool.name} 测试成功`)
      return true
    } catch (error) {
      notifyError(getApiErrorMessage(error, '测试请求失败'))
      return false
    }
  }

  async function bindStage(tool: ExternalTool, stageKey: string): Promise<boolean> {
    try {
      await bindTool(tool.id, { stage_key: stageKey })
      const list = bindings.value[tool.id] ?? []
      if (!list.includes(stageKey)) {
        bindings.value = { ...bindings.value, [tool.id]: [...list, stageKey] }
      }
      notifySuccess(`已绑定到阶段「${stageKey}」`)
      return true
    } catch (error) {
      notifyError(getApiErrorMessage(error, '绑定失败'))
      return false
    }
  }

  async function unbindStage(tool: ExternalTool, stageKey: string): Promise<boolean> {
    try {
      await unbindTool(tool.id, stageKey)
      bindings.value = {
        ...bindings.value,
        [tool.id]: (bindings.value[tool.id] ?? []).filter((s) => s !== stageKey),
      }
      notifySuccess('已从阶段解绑')
      return true
    } catch (error) {
      notifyError(getApiErrorMessage(error, '解绑失败'))
      return false
    }
  }

  /**
   * 绑定整个编制节点（= 组内全部 stage_key，差集批量绑定，仅一次成功通知）.
   *
   * 仅接受 BINDABLE_STAGE_NODE_KEYS：UI 下拉已过滤「方案导出」，此处再兜一道 ——
   * 绑定一旦落库就是「假绑定」（该节点无模型调用点，永不触发），只能靠人工解绑
   * 清理，故不允许经代码路径写入。
   */
  async function bindNode(tool: ExternalTool, nodeKey: string): Promise<boolean> {
    if (!BINDABLE_STAGE_NODE_KEYS.includes(nodeKey)) return false
    const node = STAGE_NODE_GROUPS.find((n) => n.key === nodeKey)
    if (!node) return false
    const current = bindings.value[tool.id] ?? []
    const toBind = node.stageKeys.filter((k) => !current.includes(k))
    if (toBind.length === 0) return true
    try {
      for (const stageKey of toBind) {
        await bindTool(tool.id, { stage_key: stageKey })
      }
      bindings.value = { ...bindings.value, [tool.id]: [...current, ...toBind] }
      notifySuccess(`已绑定到「${node.label}」`)
      return true
    } catch (error) {
      notifyError(getApiErrorMessage(error, '绑定失败'))
      return false
    }
  }

  /**
   * 解绑整个编制节点（= 组内全部 stage_key）.
   *
   * 这里**刻意用全量 STAGE_NODE_GROUPS**（而非 BINDABLE 子集）：历史存量可能已绑
   * 过「方案导出」，必须保留解绑通道才能清理假绑定。
   */
  async function unbindNode(tool: ExternalTool, nodeKey: string): Promise<boolean> {
    const node = STAGE_NODE_GROUPS.find((n) => n.key === nodeKey)
    if (!node) return false
    const current = bindings.value[tool.id] ?? []
    const toUnbind = node.stageKeys.filter((k) => current.includes(k))
    if (toUnbind.length === 0) return true
    try {
      for (const stageKey of toUnbind) {
        await unbindTool(tool.id, stageKey)
      }
      bindings.value = {
        ...bindings.value,
        [tool.id]: current.filter((k) => !node.stageKeys.includes(k)),
      }
      notifySuccess(`已从「${node.label}」解绑`)
      return true
    } catch (error) {
      notifyError(getApiErrorMessage(error, '解绑失败'))
      return false
    }
  }

  return {
    loading,
    tools,
    bindings,
    forms,
    load,
    getToolByPreset,
    isDirtyPreset,
    savePreset,
    clearKey,
    resetKeyClear,
    toggleEnable,
    remove,
    runTest,
    bindStage,
    unbindStage,
    bindNode,
    unbindNode,
  }
}

/* ---------------- 模块级单例 ---------------- */

let singleton: ExternalToolsConfigApi | null = null

export function useExternalToolsConfig(): ExternalToolsConfigApi {
  if (!singleton) {
    singleton = createExternalToolsConfig({
      getTools: getExternalTools,
      createTool: createExternalTool,
      updateTool: updateExternalTool,
      deleteTool: deleteExternalTool,
      testTool: testExternalTool,
      bindTool: bindExternalTool,
      unbindTool: unbindExternalTool,
      confirmDelete: (toolName) =>
        new Promise<boolean>((resolve) => {
          Modal.confirm({
            title: '确认删除',
            content: `确定要删除工具「${toolName}」吗？绑定关系将一并删除。`,
            okText: '删除',
            okType: 'danger',
            cancelText: '取消',
            onOk: () => resolve(true),
            onCancel: () => resolve(false),
          })
        }),
      notifySuccess: (msg) => message.success(msg),
      notifyError: (msg) => message.error(msg),
    })
  }
  return singleton
}
