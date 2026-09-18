import { computed, onMounted, reactive, ref, toRef } from 'vue'
import type { AxiosError } from 'axios'
import type {
  ConnectionTestResult,
  ConnectionTestTarget,
  LlmSettings,
  LlmSettingsPayload,
} from '@/api/settings'

interface ApiErrorBody {
  code?: number
  message?: string
}

export interface SettingsFormDeps {
  getSettings: () => Promise<LlmSettings>
  updateSettings: (payload: LlmSettingsPayload) => Promise<unknown>
  testConnection: (target: ConnectionTestTarget) => Promise<ConnectionTestResult>
  notifyError: (msg: string) => void
  notifySuccess: (msg: string) => void
}

/** 密钥/自定义模型输入框 touched 跟踪的字段清单 */
const KEY_FIELDS = [
  'deepseek', 'dashscope', 'openai', 'anthropic', 'zhipu', 'moonshot',
  'embedding', 'llmModel', 'llmApiBase', 'llmApiKey',
] as const

type KeyField = (typeof KEY_FIELDS)[number]

/**
 * useSettingsForm：模型设置页表单逻辑模型
 * - form reactive 三态提交：touched 字段才进入 payload（省略=保持原值，空串=清除）
 * - 密钥脱敏：placeholder 展示脱敏串，输入框始终留空，避免脱敏串被当原值回传
 * - 连通性测试：LLM / Embedding 双目标，成功/失败路径统一写入 testResult
 * - 依赖注入 API 函数与消息回调，便于单测
 */
export function useSettingsForm(deps: SettingsFormDeps) {
  const { getSettings, updateSettings, testConnection, notifyError, notifySuccess } = deps

  const fetching = ref(false)
  const saving = ref(false)
  const testingLlm = ref(false)
  const testingEmbedding = ref(false)

  const masked = ref<Record<string, string>>({})
  const configured = ref<Record<string, boolean>>({})

  /** 用户键入过（含清空）才算修改，提交时决定字段是否进入 payload */
  const touched = ref<Record<KeyField, boolean>>({
    deepseek: false,
    dashscope: false,
    openai: false,
    anthropic: false,
    zhipu: false,
    moonshot: false,
    embedding: false,
    llmModel: false,
    llmApiBase: false,
    llmApiKey: false,
  })

  const form = reactive({
    deepseekApiKey: '',
    dashscopeApiKey: '',
    openaiApiKey: '',
    anthropicApiKey: '',
    zhipuApiKey: '',
    moonshotApiKey: '',
    llmModel: '',
    llmApiBase: '',
    llmApiKey: '',
    embeddingModel: '',
    embeddingApiBase: '',
    embeddingApiKey: '',
    llmMock: false,
  })

  const testResult = ref<{ ok: boolean; text: string } | null>(null)

  const placeholderOf = (key: string, emptyText: string) => computed(() =>
    configured.value[key] ? (masked.value[key] ?? '') : emptyText,
  )

  const deepseekPlaceholder = placeholderOf('deepseek', '未配置')
  const dashscopePlaceholder = placeholderOf('dashscope', '未配置')
  const openaiPlaceholder = placeholderOf('openai', '未配置')
  const anthropicPlaceholder = placeholderOf('anthropic', '未配置')
  const zhipuPlaceholder = placeholderOf('zhipu', '未配置')
  const moonshotPlaceholder = placeholderOf('moonshot', '未配置')
  const llmApiKeyPlaceholder = placeholderOf('llmApiKey', '无鉴权端点可留空')
  const embeddingPlaceholder = placeholderOf('embedding', '留空则按模型前缀回退 LLM 密钥')

  // LLM 配置状态：主模型/服务地址/任一密钥已配置即为已配置
  const llmConfigured = computed(
    () =>
      !!form.llmModel ||
      !!form.llmApiBase ||
      configured.value.deepseek ||
      configured.value.dashscope ||
      configured.value.openai ||
      configured.value.anthropic ||
      configured.value.zhipu ||
      configured.value.moonshot ||
      configured.value.llmApiKey,
  )

  const getErrorMessage = (error: unknown, fallback: string): string => {
    const body = (error as AxiosError<ApiErrorBody>)?.response?.data
    // code 4003：非管理员访问设置接口
    if (body?.code === 4003) {
      return '需要管理员权限'
    }
    // 其余业务错误（如 embedding_api_base 私网校验 4000）展示后端 message
    return body?.message || fallback
  }

  const applySettings = (settings: LlmSettings) => {
    masked.value = {
      deepseek: settings.deepseek_api_key,
      dashscope: settings.dashscope_api_key,
      openai: settings.openai_api_key,
      anthropic: settings.anthropic_api_key,
      zhipu: settings.zhipu_api_key,
      moonshot: settings.moonshot_api_key,
      embedding: settings.embedding_api_key,
      llmApiKey: settings.llm_api_key,
    }
    configured.value = {
      deepseek: settings.deepseek_configured,
      dashscope: settings.dashscope_configured,
      openai: settings.openai_configured,
      anthropic: settings.anthropic_configured,
      zhipu: settings.zhipu_configured,
      moonshot: settings.moonshot_configured,
      llmApiKey: settings.llm_key_configured,
      embedding: settings.embedding_configured,
    }
    // 密钥框始终留空，placeholder 展示脱敏串，避免脱敏串被当原值回传
    form.deepseekApiKey = ''
    form.dashscopeApiKey = ''
    form.openaiApiKey = ''
    form.anthropicApiKey = ''
    form.zhipuApiKey = ''
    form.moonshotApiKey = ''
    form.llmApiKey = ''
    form.embeddingApiKey = ''
    form.llmModel = settings.llm_model
    form.llmApiBase = settings.llm_api_base
    form.embeddingModel = settings.embedding_model
    form.embeddingApiBase = settings.embedding_api_base
    form.llmMock = settings.llm_mock
    for (const key of KEY_FIELDS) {
      touched.value[key] = false
    }
  }

  const fetchSettings = async () => {
    fetching.value = true
    try {
      const settings = await getSettings()
      applySettings(settings)
    } catch (error) {
      notifyError(getErrorMessage(error, '获取模型配置失败'))
    } finally {
      fetching.value = false
    }
  }

  const handleSave = async () => {
    saving.value = true
    try {
      const payload: LlmSettingsPayload = {
        embedding_api_base: form.embeddingApiBase,
        embedding_model: form.embeddingModel,
        llm_mock: form.llmMock,
      }
      // 三态语义：未修改的密钥/自定义模型字段省略（保持原值）；已修改则传输入值（空串=清除）
      const keyMap: Array<[KeyField, keyof LlmSettingsPayload]> = [
        ['deepseek', 'deepseek_api_key'],
        ['dashscope', 'dashscope_api_key'],
        ['openai', 'openai_api_key'],
        ['anthropic', 'anthropic_api_key'],
        ['zhipu', 'zhipu_api_key'],
        ['moonshot', 'moonshot_api_key'],
        ['llmModel', 'llm_model'],
        ['llmApiBase', 'llm_api_base'],
        ['llmApiKey', 'llm_api_key'],
        ['embedding', 'embedding_api_key'],
      ]
      const formKeyMap: Record<KeyField, keyof typeof form> = {
        deepseek: 'deepseekApiKey',
        dashscope: 'dashscopeApiKey',
        openai: 'openaiApiKey',
        anthropic: 'anthropicApiKey',
        zhipu: 'zhipuApiKey',
        moonshot: 'moonshotApiKey',
        llmModel: 'llmModel',
        llmApiBase: 'llmApiBase',
        llmApiKey: 'llmApiKey',
        embedding: 'embeddingApiKey',
      }
      for (const [field, payloadKey] of keyMap) {
        if (touched.value[field]) {
          // payloadKey 为联合 key，经 unknown 中转后按 string 字段写入
          ;(payload as unknown as Record<string, string>)[payloadKey] = form[formKeyMap[field]] as string
        }
      }
      await updateSettings(payload)
      notifySuccess('模型配置已保存')
      for (const key of KEY_FIELDS) {
        touched.value[key] = false
      }
      await fetchSettings()
    } catch (error) {
      notifyError(getErrorMessage(error, '保存模型配置失败'))
    } finally {
      saving.value = false
    }
  }

  const buildSuccessText = (target: ConnectionTestTarget, result: {
    model?: string
    latency_ms?: number
    dimension?: number
  }): string => {
    const parts: string[] = ['连通性测试成功']
    if (result.model) {
      parts.push(`模型：${result.model}`)
    }
    if (target === 'embedding' && typeof result.dimension === 'number') {
      parts.push(`维度：${result.dimension}`)
    }
    if (typeof result.latency_ms === 'number') {
      parts.push(`耗时：${result.latency_ms}ms`)
    }
    return parts.join('，')
  }

  const handleTest = async (target: ConnectionTestTarget) => {
    const loadingRef = target === 'llm' ? testingLlm : testingEmbedding
    const label = target === 'llm' ? 'LLM' : 'Embedding'
    loadingRef.value = true
    testResult.value = null
    try {
      const result = await testConnection(target)
      if (result.ok) {
        testResult.value = { ok: true, text: buildSuccessText(target, result) }
      } else {
        testResult.value = { ok: false, text: `${label} 连通性测试失败：${result.error || '未知错误'}` }
      }
    } catch (error) {
      testResult.value = {
        ok: false,
        text: `${label} 连通性测试失败：${getErrorMessage(error, '请求失败')}`,
      }
    } finally {
      loadingRef.value = false
    }
  }

  onMounted(fetchSettings)

  return {
    fetching,
    saving,
    testingLlm,
    testingEmbedding,
    testResult,
    form,
    deepseekPlaceholder,
    dashscopePlaceholder,
    openaiPlaceholder,
    anthropicPlaceholder,
    zhipuPlaceholder,
    moonshotPlaceholder,
    llmApiKeyPlaceholder,
    embeddingPlaceholder,
    llmConfigured,
    embeddingConfigured: computed(() => configured.value.embedding),
    deepseekTouched: toRef(touched.value, 'deepseek'),
    dashscopeTouched: toRef(touched.value, 'dashscope'),
    openaiTouched: toRef(touched.value, 'openai'),
    anthropicTouched: toRef(touched.value, 'anthropic'),
    zhipuTouched: toRef(touched.value, 'zhipu'),
    moonshotTouched: toRef(touched.value, 'moonshot'),
    embeddingTouched: toRef(touched.value, 'embedding'),
    llmModelTouched: toRef(touched.value, 'llmModel'),
    llmApiBaseTouched: toRef(touched.value, 'llmApiBase'),
    llmApiKeyTouched: toRef(touched.value, 'llmApiKey'),
    getErrorMessage,
    fetchSettings,
    handleSave,
    handleTest,
  }
}
