/**
 * useRetrievalConfig：知识库参数分类（P0-5）逻辑模型.
 *
 * 逻辑迁移自旧 views/settings/RetrievalView.vue（该文件 T05 下线，不修改），
 * 并按 R1 后端契约补齐：
 * - embedding 配置走 GET/PUT /settings/llm（embedding_api_key 三态：
 *   留空=保持 / 显式清除=空串 / 新值=更新；掩码串仅作 placeholder 回显）；
 * - 检索参数 + rerank 走 GET/PUT /settings/retrieval（rerank_api_key 三态，
 *   与后端 RetrievalConfigUpdate 契约一致）；DB 优先/localStorage 回退语义
 *   保留在 api/retrieval.ts，本层不做 localStorage 读写；
 * - 测试连接 POST /settings/llm/test target=embedding；
 * - 重建索引 POST /settings/retrieval/reindex（确认流 + loading 态）。
 *
 * 表单校验（P1-6 提前落地）：api_base URL 格式、数值范围
 * （recallTopK 1~50 / threshold 0~1 / weight 0~1 / rerankTopK 1~20），
 * 非法时禁止保存并透出错误消息（validateAll 汇总）。
 *
 * 实现为「依赖注入工厂 + 模块级单例」（同 useProvidersConfig，面板切换
 * 不丢编辑态；单测经 createRetrievalConfig 注入 mock API）。
 */
import { reactive, ref, type Ref } from 'vue'
import { Modal, message } from 'ant-design-vue'
import type { LlmSettings, LlmSettingsPayload } from '@/api/settings'
import {
  getLlmSettings,
  updateLlmSettings,
} from '@/api/settings'
import {
  getRetrievalSettings,
  reindexAll,
  testRetrievalConnection,
  updateRetrievalParams,
  type RetrievalParamsDB,
  type RetrievalParamsUpdate,
} from '@/api/retrieval'
import { getApiErrorMessage } from './apiErrorMessage'
import { RETRIEVAL_RANGE_RULES, validateApiUrl, validateRange } from './useFormRules'
import { isMaskedKey } from './useProvidersConfig'

/** Embedding 连通性测试结果（对齐 testRetrievalConnection 返回） */
export interface EmbeddingTestResult {
  ok: boolean
  dimension?: number
  error?: string
}

export interface RetrievalConfigDeps {
  getSettings: () => Promise<LlmSettings>
  getRetrievalSettings: () => Promise<RetrievalParamsDB>
  updateLlmSettings: (payload: LlmSettingsPayload) => Promise<unknown>
  updateRetrievalParams: (payload: RetrievalParamsUpdate) => Promise<unknown>
  testConnection: () => Promise<EmbeddingTestResult>
  reindex: () => Promise<{ enqueued: boolean; message: string }>
  /** 重建索引确认流（面板/单测注入；resolve false = 取消） */
  confirmReindex: () => Promise<boolean>
  notifyError: (msg: string) => void
  notifySuccess: (msg: string) => void
}

export interface RetrievalConfigApi {
  loading: ReturnType<typeof ref<boolean>>
  saving: ReturnType<typeof ref<boolean>>
  testing: ReturnType<typeof ref<boolean>>
  testResult: ReturnType<typeof ref<EmbeddingTestResult | null>>
  reindexing: ReturnType<typeof ref<boolean>>
  /** embedding 配置编辑态（keyInput 留空=保持原值） */
  embed: {
    model: string
    apiBase: string
    keyInput: string
    keyCleared: boolean
    configured: boolean
    apiKeyMasked: string
  }
  /** 检索参数编辑态（undefined = 未填写/清空，payload 不携带） */
  params: { recallTopK?: number; similarityThreshold?: number; hybridWeight?: number }
  /** rerank 配置编辑态（keyInput 留空=保持原值） */
  rerank: {
    enabled: boolean
    model: string
    topK?: number
    keyInput: string
    keyCleared: boolean
    configured: boolean
    apiKeyMasked: string
  }
  /** 库内 llm_mock 当前值（embedding 保存经 PUT /settings/llm 必填透传） */
  llmMock: Ref<boolean>
  load: () => Promise<void>
  isDirtyEmbed: () => boolean
  isDirtyParams: () => boolean
  isDirtyRerank: () => boolean
  isDirty: () => boolean
  /** P1-6：全表单校验，返回全部错误消息（空数组 = 通过） */
  validateAll: () => string[]
  save: () => Promise<void>
  clearEmbedKey: () => void
  resetEmbedKeyClear: () => void
  clearRerankKey: () => void
  resetRerankKeyClear: () => void
  testEmbedding: () => Promise<EmbeddingTestResult | null>
  /** 重建索引：确认流通过才触发；返回是否成功入队 */
  runReindex: () => Promise<boolean>
}

function createRetrievalConfig(deps: RetrievalConfigDeps): RetrievalConfigApi {
  const {
    getSettings,
    getRetrievalSettings,
    updateLlmSettings,
    updateRetrievalParams,
    testConnection,
    reindex,
    confirmReindex,
    notifyError,
    notifySuccess,
  } = deps

  const loading = ref(false)
  const saving = ref(false)
  const testing = ref(false)
  const testResult = ref<EmbeddingTestResult | null>(null)
  const reindexing = ref(false)

  const embed = reactive({
    model: '',
    apiBase: '',
    keyInput: '',
    keyCleared: false,
    configured: false,
    apiKeyMasked: '',
  })
  const params = reactive<{ recallTopK?: number; similarityThreshold?: number; hybridWeight?: number }>({
    recallTopK: undefined,
    similarityThreshold: undefined,
    hybridWeight: undefined,
  })
  const rerank = reactive({
    enabled: false,
    model: '',
    topK: undefined as number | undefined,
    keyInput: '',
    keyCleared: false,
    configured: false,
    apiKeyMasked: '',
  })
  const llmMock = ref(false)

  /* 库内快照（load 时固化，脏检查基准） */
  const snapshot = {
    embedModel: '',
    embedApiBase: '',
    recallTopK: undefined as number | undefined,
    similarityThreshold: undefined as number | undefined,
    hybridWeight: undefined as number | undefined,
    rerankEnabled: false,
    rerankModel: '',
    rerankTopK: undefined as number | undefined,
  }

  /** 拉取 llm_settings + retrieval 设置，填充编辑态并固化快照 */
  async function load(): Promise<void> {
    loading.value = true
    try {
      const [settings, retrieval] = await Promise.all([getSettings(), getRetrievalSettings()])
      llmMock.value = settings.llm_mock
      embed.model = settings.embedding_model
      embed.apiBase = settings.embedding_api_base
      embed.configured = settings.embedding_configured
      embed.apiKeyMasked = settings.embedding_api_key
      embed.keyInput = ''
      embed.keyCleared = false
      params.recallTopK = retrieval.recall_top_k
      params.similarityThreshold = retrieval.similarity_threshold
      params.hybridWeight = retrieval.hybrid_weight
      rerank.enabled = retrieval.rerank_enabled
      rerank.model = retrieval.rerank_model
      rerank.topK = retrieval.rerank_top_k
      rerank.configured = retrieval.rerank_configured
      rerank.apiKeyMasked = retrieval.rerank_api_key
      rerank.keyInput = ''
      rerank.keyCleared = false
      snapshot.embedModel = settings.embedding_model
      snapshot.embedApiBase = settings.embedding_api_base
      snapshot.recallTopK = retrieval.recall_top_k
      snapshot.similarityThreshold = retrieval.similarity_threshold
      snapshot.hybridWeight = retrieval.hybrid_weight
      snapshot.rerankEnabled = retrieval.rerank_enabled
      snapshot.rerankModel = retrieval.rerank_model
      snapshot.rerankTopK = retrieval.rerank_top_k
    } catch (error) {
      notifyError(getApiErrorMessage(error, '加载检索配置失败'))
    } finally {
      loading.value = false
    }
  }

  function isDirtyEmbed(): boolean {
    if (embed.keyCleared) return true
    if (embed.keyInput.trim() !== '') return true
    if (embed.model.trim() !== snapshot.embedModel) return true
    if (embed.apiBase.trim() !== snapshot.embedApiBase) return true
    return false
  }

  function isDirtyParams(): boolean {
    return (
      params.recallTopK !== snapshot.recallTopK ||
      params.similarityThreshold !== snapshot.similarityThreshold ||
      params.hybridWeight !== snapshot.hybridWeight ||
      rerank.enabled !== snapshot.rerankEnabled ||
      rerank.model.trim() !== snapshot.rerankModel ||
      rerank.topK !== snapshot.rerankTopK ||
      rerank.keyCleared ||
      rerank.keyInput.trim() !== ''
    )
  }

  /** rerank 无独立条目，归入检索参数脏检查（isDirtyParams 已含）；恒 false 占位语义保留 */
  function isDirtyRerank(): boolean {
    return isDirtyParams()
  }

  function isDirty(): boolean {
    return isDirtyEmbed() || isDirtyParams()
  }

  /** P1-6：校验全部表单值，返回错误消息列表（空 = 通过） */
  function validateAll(): string[] {
    const errors: string[] = []
    const urlError = validateApiUrl(embed.apiBase, 'Embedding 服务地址')
    if (urlError) errors.push(urlError)
    const recallError = validateRange(params.recallTopK, RETRIEVAL_RANGE_RULES.recallTopK)
    if (recallError) errors.push(recallError)
    const thresholdError = validateRange(params.similarityThreshold, RETRIEVAL_RANGE_RULES.similarityThreshold)
    if (thresholdError) errors.push(thresholdError)
    const weightError = validateRange(params.hybridWeight, RETRIEVAL_RANGE_RULES.hybridWeight)
    if (weightError) errors.push(weightError)
    if (rerank.enabled) {
      const topKError = validateRange(rerank.topK, RETRIEVAL_RANGE_RULES.rerankTopK)
      if (topKError) errors.push(topKError)
    }
    return errors
  }

  /**
   * 构造 embedding 配置 payload（PUT /settings/llm，全量必填字段透传 + key 三态）；
   * 无任何改动返回 null（调用方跳过请求）。疑似脱敏串抛错拒传（S-1 对齐）。
   */
  function buildEmbeddingPayload(): LlmSettingsPayload | null {
    const payload: LlmSettingsPayload = {
      embedding_api_base: embed.apiBase.trim(),
      embedding_model: embed.model.trim(),
      llm_mock: llmMock.value,
    }
    const key = embed.keyInput.trim()
    if (embed.keyCleared) {
      payload.embedding_api_key = ''
    } else if (key !== '') {
      if (isMaskedKey(key)) {
        throw new Error('Embedding API Key 疑似脱敏串，请填写真实密钥')
      }
      payload.embedding_api_key = key
    }
    const changed =
      payload.embedding_api_base !== snapshot.embedApiBase ||
      payload.embedding_model !== snapshot.embedModel ||
      payload.embedding_api_key !== undefined
    return changed ? payload : null
  }

  /**
   * 构造检索参数 + rerank payload（PUT /settings/retrieval，变更字段才携带，
   * rerank_api_key 三态）；无任何改动返回 null。
   */
  function buildParamsPayload(): RetrievalParamsUpdate | null {
    const payload: RetrievalParamsUpdate = {}
    if (params.recallTopK !== snapshot.recallTopK && params.recallTopK !== undefined) {
      payload.recall_top_k = params.recallTopK
    }
    if (params.similarityThreshold !== snapshot.similarityThreshold && params.similarityThreshold !== undefined) {
      payload.similarity_threshold = params.similarityThreshold
    }
    if (params.hybridWeight !== snapshot.hybridWeight && params.hybridWeight !== undefined) {
      payload.hybrid_weight = params.hybridWeight
    }
    if (rerank.enabled !== snapshot.rerankEnabled) {
      payload.rerank_enabled = rerank.enabled
    }
    if (rerank.model.trim() !== snapshot.rerankModel) {
      payload.rerank_model = rerank.model.trim()
    }
    if (rerank.topK !== snapshot.rerankTopK && rerank.topK !== undefined) {
      payload.rerank_top_k = rerank.topK
    }
    const key = rerank.keyInput.trim()
    if (rerank.keyCleared) {
      payload.rerank_api_key = ''
    } else if (key !== '') {
      if (isMaskedKey(key)) {
        throw new Error('Rerank API Key 疑似脱敏串，请填写真实密钥')
      }
      payload.rerank_api_key = key
    }
    return Object.keys(payload).length > 0 ? payload : null
  }

  /**
   * 保存当前条目全部表单（P0-6）：校验 → embedding（有改动）→ 检索参数+rerank
   * （有改动）→ reload。校验失败/请求失败抛 Error（store 保留脏状态并透出消息）；
   * 无任何改动直接返回（视为保存成功）。
   */
  async function save(): Promise<void> {
    const errors = validateAll()
    if (errors.length > 0) {
      notifyError(errors[0])
      throw new Error(errors.join('；'))
    }
    const embeddingPayload = buildEmbeddingPayload()
    const paramsPayload = buildParamsPayload()
    if (!embeddingPayload && !paramsPayload) return
    if (embeddingPayload) {
      await updateLlmSettings(embeddingPayload)
    }
    if (paramsPayload) {
      await updateRetrievalParams(paramsPayload)
    }
    await load()
  }

  /** 显式清除 Embedding 密钥（保存时携带空串） */
  function clearEmbedKey(): void {
    embed.keyInput = ''
    embed.keyCleared = true
  }

  function resetEmbedKeyClear(): void {
    embed.keyCleared = false
  }

  /** 显式清除 Rerank 密钥（保存时携带空串） */
  function clearRerankKey(): void {
    rerank.keyInput = ''
    rerank.keyCleared = true
  }

  function resetRerankKeyClear(): void {
    rerank.keyCleared = false
  }

  /** Embedding 连通性测试；请求异常归一为 ok:false，不抛出 */
  async function testEmbedding(): Promise<EmbeddingTestResult | null> {
    testing.value = true
    testResult.value = null
    try {
      const result = await testConnection()
      testResult.value = result
      return result
    } catch (error) {
      const failed: EmbeddingTestResult = { ok: false, error: getApiErrorMessage(error, '请求失败') }
      testResult.value = failed
      return failed
    } finally {
      testing.value = false
    }
  }

  /** 重建索引：确认流通过才触发；结果经 notify 透出，返回是否成功入队 */
  async function runReindex(): Promise<boolean> {
    if (reindexing.value) return false
    if (!(await confirmReindex())) return false
    reindexing.value = true
    try {
      const result = await reindex()
      if (result.enqueued) {
        notifySuccess(result.message)
      } else {
        notifyError(result.message)
      }
      return result.enqueued
    } catch (error) {
      notifyError(getApiErrorMessage(error, '触发重建索引失败'))
      return false
    } finally {
      reindexing.value = false
    }
  }

  return {
    loading,
    saving,
    testing,
    testResult,
    reindexing,
    embed,
    params,
    rerank,
    llmMock,
    load,
    isDirtyEmbed,
    isDirtyParams,
    isDirtyRerank,
    isDirty,
    validateAll,
    save,
    clearEmbedKey,
    resetEmbedKeyClear,
    clearRerankKey,
    resetRerankKeyClear,
    testEmbedding,
    runReindex,
  }
}

export { createRetrievalConfig }

/* ---------------- 模块级单例（面板共享编辑态，弹窗关闭不丢） ---------------- */

let singleton: RetrievalConfigApi | null = null

export function useRetrievalConfig(): RetrievalConfigApi {
  if (!singleton) {
    singleton = createRetrievalConfig({
      getSettings: getLlmSettings,
      getRetrievalSettings,
      updateLlmSettings,
      updateRetrievalParams,
      testConnection: testRetrievalConnection,
      reindex: reindexAll,
      confirmReindex: () =>
        new Promise<boolean>((resolve) => {
          Modal.confirm({
            title: '重建全部索引',
            content: '将对所有项目文档重建向量索引，耗时较长且期间检索质量可能波动。确认执行？',
            okText: '重建',
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
