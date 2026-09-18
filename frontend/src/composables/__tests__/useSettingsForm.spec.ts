/**
 * useSettingsForm 模型设置表单逻辑测试（mock API 依赖注入）.
 * 覆盖：fetchSettings 填充与 touched 重置 / placeholder 派生 / llmConfigured 判定 /
 *       handleSave 三态语义 / 保存失败 / handleTest 双目标 / getErrorMessage.
 */
import { describe, expect, it, vi, beforeEach } from 'vitest'
import { useSettingsForm } from '@/composables/useSettingsForm'
import type { LlmSettings, LlmSettingsPayload } from '@/api/settings'

function mkSettings(over: Partial<LlmSettings> = {}): LlmSettings {
  return {
    deepseek_api_key: 'sk-ds-masked',
    dashscope_api_key: '',
    openai_api_key: 'sk-oa-masked',
    anthropic_api_key: '',
    zhipu_api_key: '',
    moonshot_api_key: '',
    llm_model: 'qwen72b',
    llm_api_base: 'http://127.0.0.1:7778/v1',
    llm_api_key: '',
    embedding_api_base: 'http://localhost:11434/v1',
    embedding_model: 'bge-m3',
    embedding_api_key: 'emb-masked',
    llm_mock: false,
    deepseek_configured: true,
    dashscope_configured: false,
    openai_configured: true,
    anthropic_configured: false,
    zhipu_configured: false,
    moonshot_configured: false,
    llm_key_configured: false,
    embedding_configured: true,
    ...over,
  }
}

function setup(over: {
  getSettings?: ReturnType<typeof vi.fn>
  updateSettings?: ReturnType<typeof vi.fn>
  testConnection?: ReturnType<typeof vi.fn>
} = {}) {
  const getSettings = over.getSettings ?? vi.fn().mockResolvedValue(mkSettings())
  const updateSettings = over.updateSettings ?? vi.fn().mockResolvedValue({})
  const testConnection = over.testConnection ?? vi.fn()
  const notifyError = vi.fn()
  const notifySuccess = vi.fn()
  const sf = useSettingsForm({
    getSettings,
    updateSettings,
    testConnection,
    notifyError,
    notifySuccess,
  })
  return { sf, getSettings, updateSettings, testConnection, notifyError, notifySuccess }
}

beforeEach(() => {
  vi.spyOn(console, 'warn').mockImplementation(() => {})
})

describe('fetchSettings', () => {
  it('填充脱敏串/配置态/form，并重置全部 touched', async () => {
    const { sf } = setup()
    expect(sf.fetching.value).toBe(false)
    await sf.fetchSettings()

    expect(sf.form.llmModel).toBe('qwen72b')
    expect(sf.form.llmApiBase).toBe('http://127.0.0.1:7778/v1')
    expect(sf.form.embeddingModel).toBe('bge-m3')
    expect(sf.form.llmMock).toBe(false)
    // 密钥框始终留空
    expect(sf.form.deepseekApiKey).toBe('')
    expect(sf.form.openaiApiKey).toBe('')
    // touched 全部重置
    expect(sf.deepseekTouched.value).toBe(false)
    expect(sf.llmModelTouched.value).toBe(false)
    expect(sf.embeddingTouched.value).toBe(false)
    expect(sf.fetching.value).toBe(false)
  })

  it('placeholder：已配置展示脱敏串，未配置展示提示文案', async () => {
    const { sf } = setup()
    await sf.fetchSettings()
    expect(sf.deepseekPlaceholder.value).toBe('sk-ds-masked')
    expect(sf.openaiPlaceholder.value).toBe('sk-oa-masked')
    expect(sf.embeddingPlaceholder.value).toBe('emb-masked')
    expect(sf.dashscopePlaceholder.value).toBe('未配置')
    expect(sf.anthropicPlaceholder.value).toBe('未配置')
    expect(sf.llmApiKeyPlaceholder.value).toBe('无鉴权端点可留空')
  })

  it('llmConfigured：模型/地址/任一密钥已配置即为已配置', async () => {
    const { sf } = setup()
    await sf.fetchSettings()
    expect(sf.llmConfigured.value).toBe(true)
    expect(sf.embeddingConfigured.value).toBe(true)
  })

  it('fetch 失败：notifyError 展示 fallback，不中断', async () => {
    const { sf, notifyError } = setup({
      getSettings: vi.fn().mockRejectedValue(new Error('network')),
    })
    await sf.fetchSettings()
    expect(notifyError).toHaveBeenCalledWith('获取模型配置失败')
    expect(sf.fetching.value).toBe(false)
  })
})

describe('handleSave 三态语义', () => {
  it('touched 字段进入 payload，未 touched 省略；成功重置并刷新', async () => {
    const { sf, updateSettings, notifySuccess, getSettings } = setup()
    await sf.fetchSettings()
    sf.deepseekTouched.value = true
    sf.form.deepseekApiKey = 'sk-new'
    sf.llmModelTouched.value = true
    sf.form.llmModel = 'deepseek/deepseek-chat'
    sf.embeddingTouched.value = true
    sf.form.embeddingApiKey = '' // 清空=删除密钥

    await sf.handleSave()

    const payload = updateSettings.mock.calls[0][0] as LlmSettingsPayload
    expect(payload.deepseek_api_key).toBe('sk-new')
    expect(payload.llm_model).toBe('deepseek/deepseek-chat')
    expect(payload.embedding_api_key).toBe('')
    // 未 touched 的字段必须省略（保持原值语义）
    expect(payload).not.toHaveProperty('openai_api_key')
    expect(payload).not.toHaveProperty('zhipu_api_key')
    // 必填全量字段
    expect(payload.embedding_api_base).toBe('http://localhost:11434/v1')
    expect(payload.embedding_model).toBe('bge-m3')
    expect(payload.llm_mock).toBe(false)

    expect(notifySuccess).toHaveBeenCalledWith('模型配置已保存')
    expect(sf.deepseekTouched.value).toBe(false)
    expect(getSettings).toHaveBeenCalledTimes(2) // 初始 fetch + 保存后刷新
  })

  it('全部未 touched：payload 仅含必填全量字段', async () => {
    const { sf, updateSettings } = setup()
    await sf.fetchSettings()
    await sf.handleSave()
    const payload = updateSettings.mock.calls[0][0] as LlmSettingsPayload
    expect(Object.keys(payload).sort()).toEqual(
      ['embedding_api_base', 'embedding_model', 'llm_mock'].sort(),
    )
  })

  it('保存失败：notifyError 使用业务 message', async () => {
    const { sf, notifyError } = setup({
      updateSettings: vi.fn().mockRejectedValue({
        response: { data: { code: 4000, message: 'embedding_api_base 不允许指向私网' } },
      }),
    })
    await sf.handleSave()
    expect(notifyError).toHaveBeenCalledWith('embedding_api_base 不允许指向私网')
    expect(sf.saving.value).toBe(false)
  })
})

describe('handleTest 连通性测试', () => {
  it('LLM 成功：文本含模型与耗时', async () => {
    const { sf, testConnection } = setup({
      testConnection: vi.fn().mockResolvedValue({ ok: true, model: 'qwen72b', latency_ms: 320 }),
    })
    await sf.handleTest('llm')
    expect(testConnection).toHaveBeenCalledWith('llm')
    expect(sf.testResult.value).toEqual({
      ok: true,
      text: '连通性测试成功，模型：qwen72b，耗时：320ms',
    })
    expect(sf.testingLlm.value).toBe(false)
  })

  it('Embedding 成功：额外含维度', async () => {
    const { sf } = setup({
      testConnection: vi.fn().mockResolvedValue({ ok: true, model: 'bge-m3', dimension: 1024, latency_ms: 88 }),
    })
    await sf.handleTest('embedding')
    expect(sf.testResult.value?.text).toContain('维度：1024')
    expect(sf.testingEmbedding.value).toBe(false)
  })

  it('接口返回 ok:false：展示目标标签与后端错误', async () => {
    const { sf } = setup({
      testConnection: vi.fn().mockResolvedValue({ ok: false, error: '连接超时' }),
    })
    await sf.handleTest('embedding')
    expect(sf.testResult.value).toEqual({
      ok: false,
      text: 'Embedding 连通性测试失败：连接超时',
    })
  })

  it('请求异常：4003 映射为需要管理员权限', async () => {
    const { sf } = setup({
      testConnection: vi.fn().mockRejectedValue({
        response: { data: { code: 4003, message: 'forbidden' } },
      }),
    })
    await sf.handleTest('llm')
    expect(sf.testResult.value).toEqual({
      ok: false,
      text: 'LLM 连通性测试失败：需要管理员权限',
    })
  })
})

describe('getErrorMessage', () => {
  it('4003 → 需要管理员权限；业务 message 优先；否则 fallback', () => {
    const { sf } = setup()
    expect(sf.getErrorMessage({ response: { data: { code: 4003 } } }, 'x')).toBe('需要管理员权限')
    expect(sf.getErrorMessage({ response: { data: { code: 4000, message: '私网' } } }, 'x')).toBe('私网')
    expect(sf.getErrorMessage(new Error('boom'), '兜底文案')).toBe('兜底文案')
  })
})
