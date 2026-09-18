/**
 * useProvidersConfig：语言模型分类（P0-3/P0-4）提供方条目表单逻辑模型.
 *
 * 条目映射（registry LLM_UI_WHITELIST）：
 * - llm:deepseek / llm:zhipu → providers 表同 prefix 行：key 三态 + api_base，
 *   保存走 PUT /settings/providers/{id}；
 * - llm:custom → 端点专用密钥走 providers 'custom' 行（R1 后端已统一真源），
 *   主模型/服务地址走 llm_settings（llm_model/llm_api_base），保存走
 *   PUT /settings/llm（embedding_api_base/embedding_model/llm_mock 为必填
 *   全量字段，透传库内当前值）。
 *
 * 密钥三态语义（最高回归风险点）：
 * - 输入框留空 = 省略 = 保持原值（payload 不携带该字段）；
 * - 显式点击"清除" → 保存时携带空串（后端清除已存密钥）；
 * - 输入非空 → 携带新值；疑似脱敏串（含连续 4 星号）前端拒传（与后端 S-1 对齐）。
 * - GET 返回的 sk-****xxxx 掩码串只作 placeholder 回显，永不出现在表单值中。
 *
 * 实现为「依赖注入工厂 + 模块级单例」：面板经 useProvidersConfig() 取共享实例
 * （面板切换/弹窗关闭不丢编辑态，ARCH 风险点 3）；单测经 createProvidersConfig
 * 注入 mock API。
 */
import { reactive, ref, type Ref } from 'vue'
import { message } from 'ant-design-vue'
import type { Provider, ProviderUpdatePayload } from '@/api/providers'
import {
  getLlmSettings,
  testLlmConnection,
  updateLlmSettings,
  type ConnectionTestOverrides,
  type ConnectionTestResult,
  type LlmSettings,
  type LlmSettingsPayload,
} from '@/api/settings'
import { getProviders, updateProvider } from '@/api/providers'
import { getApiErrorMessage } from './apiErrorMessage'

/* ---------------- 条目常量 ---------------- */

export const PROVIDER_ENTRY_IDS = ['llm:custom', 'llm:deepseek', 'llm:zhipu'] as const
export type ProviderEntryId = (typeof PROVIDER_ENTRY_IDS)[number]
/** 云端提供方条目（key/api_base 存 providers 行） */
export type CloudProviderEntryId = Exclude<ProviderEntryId, 'llm:custom'>

const ENTRY_TO_PREFIX: Record<CloudProviderEntryId, string> = {
  'llm:deepseek': 'deepseek',
  'llm:zhipu': 'zhipu',
}

/** S-1 对齐：疑似脱敏串（前缀仅含密钥常见字符 + 连续 4 星号） */
export function isMaskedKey(value: string): boolean {
  return /^[A-Za-z0-9_-]*\*{4}.*$/.test(value)
}

/* ---------------- 表单状态 ---------------- */

/** 云端提供方条目表单（key 三态输入 + 自定义端点） */
export interface ProviderKeyForm {
  /** 新密钥输入（空串 = 未输入；输入框恒不以掩码串填充） */
  keyInput: string
  /** 显式清除标记：点击"清除"后置 true，保存时携带 api_key='' */
  keyCleared: boolean
  /** 自定义请求地址输入（placeholder 回显厂商默认端点） */
  apiBase: string
  /** 用户是否触碰过地址框（未触碰则保存时不携带 api_base） */
  apiBaseTouched: boolean
}

function freshKeyForm(): ProviderKeyForm {
  return { keyInput: '', keyCleared: false, apiBase: '', apiBaseTouched: false }
}

export interface ProvidersConfigDeps {
  getProviders: () => Promise<Provider[]>
  getLlmSettings: () => Promise<LlmSettings>
  updateProvider: (id: string, payload: ProviderUpdatePayload) => Promise<unknown>
  updateLlmSettings: (payload: LlmSettingsPayload) => Promise<unknown>
  testConnection: (target: 'llm', overrides?: ConnectionTestOverrides) => Promise<ConnectionTestResult>
  notifyError: (msg: string) => void
}

export interface ProvidersConfigApi {
  loading: Ref<boolean>
  providers: Ref<Provider[]>
  llmSettings: Ref<LlmSettings | null>
  /** 各条目表单（key: llm:deepseek / llm:zhipu / llm:custom） */
  entries: Record<ProviderEntryId, { provider: Provider | null; form: ProviderKeyForm }>
  /** custom 条目的全局配置字段（存 llm_settings） */
  customGlobal: { llmModel: string; llmApiBase: string }
  testing: Ref<boolean>
  testResult: Ref<ConnectionTestResult | null>
  load: () => Promise<void>
  isDirtyProvider: (entryId: CloudProviderEntryId) => boolean
  isDirtyCustom: () => boolean
  clearKey: (entryId: ProviderEntryId) => void
  resetKeyClear: (entryId: ProviderEntryId) => void
  saveProvider: (entryId: CloudProviderEntryId) => Promise<void>
  saveCustom: () => Promise<void>
  runTest: (overrides?: ConnectionTestOverrides) => Promise<ConnectionTestResult | null>
}

export function createProvidersConfig(deps: ProvidersConfigDeps): ProvidersConfigApi {
  const { getProviders, getLlmSettings, updateProvider, updateLlmSettings, testConnection, notifyError } = deps

  const loading = ref(false)
  const providers = ref<Provider[]>([])
  const llmSettings = ref<LlmSettings | null>(null)

  const entries = reactive<Record<ProviderEntryId, { provider: Provider | null; form: ProviderKeyForm }>>({
    'llm:custom': { provider: null, form: freshKeyForm() },
    'llm:deepseek': { provider: null, form: freshKeyForm() },
    'llm:zhipu': { provider: null, form: freshKeyForm() },
  })
  const customGlobal = reactive({ llmModel: '', llmApiBase: '' })

  const testing = ref(false)
  const testResult = ref<ConnectionTestResult | null>(null)

  /** 拉取 providers + llm_settings，填充条目视图与表单快照（重置编辑态） */
  async function load(): Promise<void> {
    loading.value = true
    try {
      const [rows, settings] = await Promise.all([getProviders(), getLlmSettings()])
      providers.value = rows
      llmSettings.value = settings
      for (const entryId of PROVIDER_ENTRY_IDS) {
        const prefix = entryId === 'llm:custom' ? 'custom' : ENTRY_TO_PREFIX[entryId]
        const row = rows.find((p) => p.prefix === prefix) ?? null
        entries[entryId].provider = row
        entries[entryId].form = freshKeyForm()
        if (row) {
          entries[entryId].form.apiBase = row.apiBase
        }
      }
      customGlobal.llmModel = settings.llm_model
      customGlobal.llmApiBase = settings.llm_api_base
    } catch (error) {
      notifyError(getApiErrorMessage(error, '加载模型服务商配置失败'))
    } finally {
      loading.value = false
    }
  }

  /** 云端提供方条目脏检查：key 三态动作 或 地址触碰且与库内值不一致 */
  function isDirtyProvider(entryId: CloudProviderEntryId): boolean {
    const form = entries[entryId].form
    if (form.keyCleared) return true
    if (form.keyInput.trim() !== '') return true
    if (form.apiBaseTouched && form.apiBase.trim() !== (entries[entryId].provider?.apiBase ?? '')) {
      return true
    }
    return false
  }

  /** custom 条目脏检查：key 三态动作 或 llm_model/llm_api_base 与库内值不一致 */
  function isDirtyCustom(): boolean {
    const form = entries['llm:custom'].form
    if (form.keyCleared) return true
    if (form.keyInput.trim() !== '') return true
    if (customGlobal.llmModel.trim() !== (llmSettings.value?.llm_model ?? '')) return true
    if (customGlobal.llmApiBase.trim() !== (llmSettings.value?.llm_api_base ?? '')) return true
    return false
  }

  /** 显式清除：保存时携带空串（后端清空已存密钥） */
  function clearKey(entryId: ProviderEntryId): void {
    entries[entryId].form.keyInput = ''
    entries[entryId].form.keyCleared = true
  }

  /** 撤销清除（恢复"保持原值"态） */
  function resetKeyClear(entryId: ProviderEntryId): void {
    entries[entryId].form.keyCleared = false
  }

  /** 构造云端提供方三态 payload；无任何改动返回 null（调用方跳过请求） */
  function buildProviderPayload(entryId: CloudProviderEntryId): ProviderUpdatePayload | null {
    const form = entries[entryId].form
    const payload: ProviderUpdatePayload = {}
    const key = form.keyInput.trim()
    if (form.keyCleared) {
      payload.api_key = ''
    } else if (key !== '') {
      if (isMaskedKey(key)) {
        throw new Error('API Key 疑似脱敏串，请填写真实密钥')
      }
      payload.api_key = key
    }
    if (form.apiBaseTouched) {
      payload.api_base = form.apiBase.trim()
    }
    return Object.keys(payload).length > 0 ? payload : null
  }

  /**
   * 保存云端提供方条目。失败抛 Error（store 保留脏状态并透出消息）；
   * 无改动直接返回（视为保存成功）。
   */
  async function saveProvider(entryId: CloudProviderEntryId): Promise<void> {
    const provider = entries[entryId].provider
    if (!provider) {
      throw new Error('未找到对应服务商，请刷新后重试')
    }
    const payload = buildProviderPayload(entryId)
    if (!payload) return
    await updateProvider(provider.id, payload)
    await load()
  }

  /**
   * 保存 custom 条目：llm_model/llm_api_base（有变更才携带）+ llm_api_key 三态
   * 经 PUT /settings/llm（后端 R1 将 llm_api_key 写 providers 'custom' 行）。
   * embedding_api_base/embedding_model/llm_mock 必填全量，透传库内当前值。
   */
  async function saveCustom(): Promise<void> {
    const settings = llmSettings.value
    if (!settings) {
      throw new Error('全局模型配置未加载，请刷新后重试')
    }
    const form = entries['llm:custom'].form
    const payload: LlmSettingsPayload = {
      embedding_api_base: settings.embedding_api_base,
      embedding_model: settings.embedding_model,
      llm_mock: settings.llm_mock,
    }
    const model = customGlobal.llmModel.trim()
    const base = customGlobal.llmApiBase.trim()
    const key = form.keyInput.trim()
    if (model !== settings.llm_model) {
      payload.llm_model = model
    }
    if (base !== settings.llm_api_base) {
      payload.llm_api_base = base
    }
    let changed = payload.llm_model !== undefined || payload.llm_api_base !== undefined
    if (form.keyCleared) {
      payload.llm_api_key = ''
      changed = true
    } else if (key !== '') {
      if (isMaskedKey(key)) {
        throw new Error('API Key 疑似脱敏串，请填写真实密钥')
      }
      payload.llm_api_key = key
      changed = true
    }
    if (!changed) return

    // 先测后存：连接相关字段有变更时，先按表单值做连通性测试（key 留空由
    // 后端回退已存密钥），失败则中止保存——避免把不可用的端点写进配置。
    const test = await runTest({
      model,
      api_base: base,
      api_key: form.keyCleared || isMaskedKey(key) ? '' : key,
    })
    if (!test || !test.ok) {
      throw new Error(`连通性测试未通过，已中止保存：${test?.error || '未知错误'}`)
    }
    await updateLlmSettings(payload)
    await load()
  }

  /** 连通性测试（POST /settings/llm/test target=llm）；结果内联展示，异常归一为 ok:false。
   * overrides 携带表单未保存值时按覆盖模式测试（先测后存；key 缺省由后端回退已存密钥） */
  async function runTest(
    overrides?: ConnectionTestOverrides,
  ): Promise<ConnectionTestResult | null> {
    testing.value = true
    testResult.value = null
    try {
      const result = await testConnection('llm', overrides)
      testResult.value = result
      return result
    } catch (error) {
      const failed: ConnectionTestResult = { ok: false, error: getApiErrorMessage(error, '请求失败') }
      testResult.value = failed
      return failed
    } finally {
      testing.value = false
    }
  }

  return {
    loading,
    providers,
    llmSettings,
    entries,
    customGlobal,
    testing,
    testResult,
    load,
    isDirtyProvider,
    isDirtyCustom,
    clearKey,
    resetKeyClear,
    saveProvider,
    saveCustom,
    runTest,
  }
}

/* ---------------- 模块级单例（面板共享编辑态，弹窗关闭不丢） ---------------- */

let singleton: ProvidersConfigApi | null = null

export function useProvidersConfig(): ProvidersConfigApi {
  if (!singleton) {
    singleton = createProvidersConfig({
      getProviders,
      getLlmSettings,
      updateProvider,
      updateLlmSettings,
      testConnection: testLlmConnection,
      notifyError: (msg) => message.error(msg),
    })
  }
  return singleton
}
