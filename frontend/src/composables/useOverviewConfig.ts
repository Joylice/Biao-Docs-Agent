/**
 * useOverviewConfig：配置概览分类（P1-1）逻辑模型.
 *
 * 只读汇总：3 个白名单 LLM 提供方 key 配置态（configured + 掩码尾串）、
 * 8 阶段路由目标模型、embedding/rerank 启用态、外部工具（tavily/brave/
 * searxng）配置与启停态。连通性口径 = 各 composable 单例内存中"最近一次
 * 测试结果"（用户已拍板：不做实时探测）。
 *
 * 数据新鲜度：watch store.overviewVersion（任一条目保存成功后 ++）重取；
 * 打开弹窗时 load 一次。
 *
 * buildOverviewSnapshot 为纯函数（导出供单测直接覆盖数据映射）。
 */
import { ref, type Ref } from 'vue'
import { message } from 'ant-design-vue'
import type { ExternalTool } from '@/api/externalTools'
import { getExternalTools } from '@/api/externalTools'
import type { ModelRoute } from '@/api/providers'
import { getProviders, getRoutes } from '@/api/providers'
import type { RetrievalParamsDB } from '@/api/retrieval'
import { getRetrievalSettings } from '@/api/retrieval'
import type { LlmSettings } from '@/api/settings'
import { getLlmSettings } from '@/api/settings'
import { getApiErrorMessage } from './apiErrorMessage'
import {
  PRESET_DEFAULT_NAMES,
  WEBSEARCH_PRESETS,
  type WebsearchPreset,
} from './useExternalToolsConfig'

/** 概览快照（纯数据，OverviewPanel 渲染源；单测覆盖映射） */
export interface OverviewSnapshot {
  providers: Array<{
    /** registry 条目 id（点击跳转） */
    entryId: string
    title: string
    preset: string
    configured: boolean
    apiKeyMasked: string
    /** 最近一次测试结果：true=成功 / false=失败 / null=未测试（composable 内存态） */
    lastTestOk: boolean | null
  }>
  routes: Array<{ stageKey: string; stageName: string; model: string; enabled: boolean }>
  retrieval: {
    embeddingModel: string
    embeddingConfigured: boolean
    rerankEnabled: boolean
    rerankConfigured: boolean
  }
  tools: Array<{
    preset: WebsearchPreset
    name: string
    configured: boolean
    enabled: boolean
    exists: boolean
  }>
}

/** 纯函数：原始数据 → 概览快照（白名单口径与 registry/LLM_UI_WHITELIST 一致） */
export function buildOverviewSnapshot(input: {
  providers: Array<{ prefix: string; configured: boolean; apiKeyMasked: string }>
  routes: ModelRoute[]
  llm: Pick<LlmSettings, 'embedding_model' | 'embedding_configured'>
  retrieval: Pick<RetrievalParamsDB, 'rerank_enabled' | 'rerank_configured'>
  tools: ExternalTool[]
}): OverviewSnapshot {
  const providerEntryMap: Array<{ preset: string; entryId: string; title: string }> = [
    { preset: 'custom', entryId: 'llm:custom', title: '自定义端点' },
    { preset: 'deepseek', entryId: 'llm:deepseek', title: 'DeepSeek' },
    { preset: 'zhipu', entryId: 'llm:zhipu', title: '智谱 GLM' },
  ]
  return {
    providers: providerEntryMap.map(({ preset, entryId, title }) => {
      const row = input.providers.find((p) => p.prefix === preset)
      return {
        entryId,
        title,
        preset,
        configured: row?.configured ?? false,
        apiKeyMasked: row?.apiKeyMasked ?? '',
        lastTestOk: null,
      }
    }),
    routes: input.routes.map((r) => ({
      stageKey: r.stageKey,
      stageName: r.stageName,
      model: r.model,
      enabled: r.enabled,
    })),
    retrieval: {
      embeddingModel: input.llm.embedding_model,
      embeddingConfigured: input.llm.embedding_configured,
      rerankEnabled: input.retrieval.rerank_enabled,
      rerankConfigured: input.retrieval.rerank_configured,
    },
    tools: WEBSEARCH_PRESETS.map((preset) => {
      const row = input.tools.find((t) => t.preset === preset)
      return {
        preset,
        name: row?.name ?? PRESET_DEFAULT_NAMES[preset],
        configured: row?.configured ?? false,
        enabled: row?.enabled ?? false,
        exists: row !== undefined,
      }
    }),
  }
}

export interface OverviewConfigDeps {
  getProviders: () => Promise<Array<{ prefix: string; configured: boolean; apiKeyMasked: string }>>
  getRoutes: () => Promise<ModelRoute[]>
  getLlm: () => Promise<LlmSettings>
  getRetrieval: () => Promise<RetrievalParamsDB>
  getTools: () => Promise<ExternalTool[]>
  notifyError: (msg: string) => void
}

export interface OverviewConfigApi {
  loading: Ref<boolean>
  snapshot: Ref<OverviewSnapshot | null>
  load: () => Promise<void>
}

export function createOverviewConfig(deps: OverviewConfigDeps): OverviewConfigApi {
  const { getProviders, getRoutes, getLlm, getRetrieval, getTools, notifyError } = deps

  const loading = ref(false)
  const snapshot = ref<OverviewSnapshot | null>(null)

  async function load(): Promise<void> {
    loading.value = true
    try {
      const [providers, routes, llm, retrieval, tools] = await Promise.all([
        getProviders(),
        getRoutes(),
        getLlm(),
        getRetrieval(),
        getTools(),
      ])
      snapshot.value = buildOverviewSnapshot({ providers, routes, llm, retrieval, tools })
    } catch (error) {
      notifyError(getApiErrorMessage(error, '加载配置概览失败'))
    } finally {
      loading.value = false
    }
  }

  return { loading, snapshot, load }
}

/* ---------------- 模块级单例 ---------------- */

let singleton: OverviewConfigApi | null = null

export function useOverviewConfig(): OverviewConfigApi {
  if (!singleton) {
    singleton = createOverviewConfig({
      getProviders,
      getRoutes,
      getLlm: getLlmSettings,
      getRetrieval: getRetrievalSettings,
      getTools: getExternalTools,
      notifyError: (msg) => message.error(msg),
    })
  }
  return singleton
}
