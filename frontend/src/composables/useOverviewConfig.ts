/**
 * useOverviewConfig：配置概览分类（P1-1）逻辑模型.
 *
 * 只读汇总：3 个白名单 LLM 提供方 key 配置态（configured + 掩码尾串）、
 * 5 个投标编制节点的目标模型（8 个 stage_key 经 @/config/stageNodes 归并）、
 * embedding/rerank 启用态、外部工具（tavily/brave/searxng）配置与启停态。
 * 连通性口径 = 各 composable 单例内存中"最近一次测试结果"（用户已拍板：
 * 不做实时探测）。
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
import { groupRoutesByNode } from '@/config/stageNodes'
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

/** 概览快照中单个投标编制节点（5 个，展示层归并产物） */
export interface OverviewRouteNode {
  /** 节点 id（展示层分组键，非后端字段） */
  key: string
  /** 节点序号 1..5 */
  index: number
  /** 节点中文名（← 归并表 label，非组内 stage_name） */
  label: string
  /** 归并到本节点的 stage_key（顺序 = 流水线顺序） */
  stageKeys: readonly string[]
  /** 节点级目标模型：组内首条非空 model；组内全空 → ''（展示为回退全局） */
  model: string
  /** 组内实际命中路由行的阶段数（后端缺行时 < stageKeys.length） */
  stageCount: number
  /** 组内 enabled=false 的阶段数（0 = 全部启用） */
  disabledCount: number
}

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
  /** 阶段路由：8 个 stage_key 归并为 5 个投标编制节点 */
  routeNodes: OverviewRouteNode[]
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
    routeNodes: groupRoutesByNode(input.routes).map((g) => ({
      key: g.key,
      index: g.index,
      label: g.label,
      stageKeys: g.stageKeys,
      model: g.routes.find((r) => r.model)?.model ?? '',
      stageCount: g.routes.length,
      disabledCount: g.routes.filter((r) => !r.enabled).length,
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
