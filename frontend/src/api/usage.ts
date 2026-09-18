/**
 * LLM 用量 API — /usage/summary、/usage/trend.
 *
 * 后端 /usage/summary 返回按 (stage_key, model) 聚合的明细数组，
 * 前端卡片需要的总量/成功率/总 Token 由 summarizeUsage 在前端聚合
 * （历史实现直接按扁平字段读取 → 显示 NaN%，此处为修正后的真源）。
 * /usage/trend 提供各智能体按日 token 时序，供折线图使用；
 * 后端已按「智能体类别」归并（parse+score → 招标解析，write+validate+consistency →
 * 方案生成），前端直接消费 category/label，不再自行贴中文名（避免同名图例重复）。
 */
import api from './client'

/** 单条用量明细（stage_key = 流水线阶段；category = 归并后的智能体类别） */
export interface UsageSummaryItem {
  stage_key: string | null
  category: string
  category_label: string
  model: string | null
  calls: number
  ok_calls: number
  success_rate: number
  total_tokens: number
  avg_latency_ms: number
}

/** /usage/summary 原始响应 */
export interface UsageSummaryResponse {
  items: UsageSummaryItem[]
  days: number
}

/** 用量摘要卡展示口径（由明细聚合而来） */
export interface UsageSummary {
  total_calls: number
  success_rate: number
  total_tokens: number
  avg_latency_ms: number
}

/** 类别下钻明细：子阶段（招标解析含 parse/score，方案生成含 write/validate/consistency） */
export interface UsageTrendStage {
  stage_key: string
  label: string
  calls: number
  ok_calls: number
  tokens: number
}

/** 类别下钻明细：模型（同一智能体可能跨多个模型，如历史路由变更） */
export interface UsageTrendModel {
  model: string
  calls: number
  tokens: number
}

/**
 * 单个智能体折线（points 与 UsageTrendResponse.dates 等长对齐）.
 *
 * category/label 由后端按业务口径归并给出（≠ stage_key）：一个智能体类别
 * 可能由多个流水线 stage_key 合并而来，故同名图例不会重复。
 */
export interface UsageTrendSeries {
  category: string
  label: string
  calls: number
  ok_calls: number
  /** 失败调用数（失败行无 token 计量，用于解释「有调用但 token 为 0」） */
  failed_calls: number
  total_tokens: number
  points: number[]
  stages: UsageTrendStage[]
  models: UsageTrendModel[]
}

/** /usage/trend 响应 */
export interface UsageTrendResponse {
  days: number
  dates: string[]
  /** 聚合维度：agent=按智能体（默认），model=按模型 */
  dimension: 'agent' | 'model'
  series: UsageTrendSeries[]
}

interface ApiResult<T> {
  code: number
  message?: string
  data: T
}

/** 将明细数组聚合为摘要卡口径（延迟按调用次数加权平均） */
export const summarizeUsage = (items: UsageSummaryItem[]): UsageSummary => {
  const total_calls = items.reduce((sum, item) => sum + (item.calls || 0), 0)
  const ok_calls = items.reduce((sum, item) => sum + (item.ok_calls || 0), 0)
  const total_tokens = items.reduce((sum, item) => sum + (item.total_tokens || 0), 0)
  const weighted_latency = items.reduce(
    (sum, item) => sum + (item.avg_latency_ms || 0) * (item.calls || 0),
    0,
  )
  return {
    total_calls,
    success_rate: total_calls ? ok_calls / total_calls : 0,
    total_tokens,
    avg_latency_ms: total_calls ? Math.round(weighted_latency / total_calls) : 0,
  }
}

/** 获取用量摘要（近 N 天，失败静默返回 null 不阻塞面板） */
export const getUsageSummary = async (days = 30): Promise<UsageSummary | null> => {
  try {
    const { data } = await api.get<ApiResult<UsageSummaryResponse>>('/usage/summary', {
      params: { days },
    })
    return summarizeUsage(data.data?.items ?? [])
  } catch {
    return null
  }
}

/** 获取 token 用量按日趋势（失败静默返回 null；dimension 切换智能体/模型口径） */
export const getUsageTrend = async (
  days = 30,
  dimension: 'agent' | 'model' = 'agent',
): Promise<UsageTrendResponse | null> => {
  try {
    const { data } = await api.get<ApiResult<UsageTrendResponse>>('/usage/trend', {
      params: { days, dimension },
    })
    return data.data ?? null
  } catch {
    return null
  }
}

/**
 * 解析智能体执行画像单行（ADR-0004 A2）.
 *
 * label 由**后端**按解析 Agent 注册表给出，前端禁止自贴中文名
 * （与 category_label 同因：曾致图例出现重复名称）。
 */
export interface AgentProfileItem {
  agent_id: string
  label: string
  calls: number
  ok_calls: number
  /** 失败调用数：失败行无 token 计量，必须与 token 分开看 */
  failed_calls: number
  success_rate: number
  avg_latency_ms: number
  total_tokens: number
  /** 带工具调用留痕的调用次数（tool_calls IS NOT NULL） */
  tool_rows: number
  /** 工具调用总次数 */
  tool_calls_total: number
}

/** /usage/agent-profiles 响应 */
export interface AgentProfilesResponse {
  days: number
  items: AgentProfileItem[]
}

/** 获取解析智能体执行画像（失败静默返回 null，不阻塞面板） */
export const getAgentProfiles = async (days = 30): Promise<AgentProfilesResponse | null> => {
  try {
    const { data } = await api.get<ApiResult<AgentProfilesResponse>>('/usage/agent-profiles', {
      params: { days },
    })
    return data.data ?? null
  } catch {
    return null
  }
}

/**
 * 画像是否「有数据但全无工具留痕」—— 用于提示工具默认关闭.
 *
 * 解析工具受双重开关控制（`parse_tools_enabled` 与注册表 per-agent `tools_enabled`
 * 默认均关闭），此时工具维度天然为空；空列表返回 false（走空状态而非该提示）。
 */
export const hasNoToolTrace = (items: AgentProfileItem[]): boolean =>
  items.length > 0 && items.every((item) => item.tool_rows === 0)
