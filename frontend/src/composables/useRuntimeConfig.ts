/**
 * useRuntimeConfig：系统设置分类（P1-4）逻辑模型.
 *
 * 逻辑迁移自旧 views/settings/RuntimeView.vue（该文件 T05 下线，不修改）：
 * - mock 开关：GET /settings/llm 读 llm_mock，切换经 PUT /settings/llm
 *   （embedding_api_base/embedding_model 透传库内当前值，避免旧实现发空串
 *   造成密钥/地址被误清）；确认流 + 失败回滚由 deps 注入；
 * - 用量摘要：GET /usage/summary（近 30 天，前端聚合为卡片口径）；
 * - 用量趋势：GET /usage/trend（各智能体按日 Token 折线图数据源）；
 * - 解析智能体画像：GET /usage/agent-profiles（ADR-0004 A2，按 agent_id 归属）。
 *
 * 审计日志已于本次改造移出本面板（独立页面 views/audit/AuditLogsView.vue 保留），
 * 面板聚焦「运行模式 + 用量」。
 *
 * 实现为「依赖注入工厂 + 模块级单例」（单测经 createRuntimeConfig 注入 mock）。
 */
import { ref, type Ref } from 'vue'
import { Modal, message } from 'ant-design-vue'
import type { LlmSettings, LlmSettingsPayload } from '@/api/settings'
import { getLlmSettings, updateLlmSettings } from '@/api/settings'
import type { AgentProfilesResponse, UsageSummary, UsageTrendResponse } from '@/api/usage'
import { getAgentProfiles, getUsageSummary, getUsageTrend } from '@/api/usage'
import { getApiErrorMessage } from './apiErrorMessage'

/** 用量统计窗口（天） */
export const USAGE_WINDOW_DAYS = 30

/** 趋势图聚合维度：agent=按业务智能体（默认），model=按模型 */
export type TrendDimension = 'agent' | 'model'

export interface RuntimeConfigDeps {
  getSettings: () => Promise<LlmSettings>
  updateLlmSettings: (payload: LlmSettingsPayload) => Promise<unknown>
  getUsage: (days: number) => Promise<UsageSummary | null>
  getUsageTrend: (days: number, dimension: TrendDimension) => Promise<UsageTrendResponse | null>
  getAgentProfiles: (days: number) => Promise<AgentProfilesResponse | null>
  /** mock 切换确认流（resolve false = 取消，不发起请求） */
  confirmMock: (next: boolean) => Promise<boolean>
  notifyError: (msg: string) => void
  notifySuccess: (msg: string) => void
}

export interface RuntimeConfigApi {
  loading: ReturnType<typeof ref<boolean>>
  saving: ReturnType<typeof ref<boolean>>
  mockEnabled: ReturnType<typeof ref<boolean>>
  /** 用量摘要（近 30 天聚合口径） */
  usage: ReturnType<typeof ref<UsageSummary | null>>
  /** 趋势图数据源（按当前维度聚合） */
  usageTrend: ReturnType<typeof ref<UsageTrendResponse | null>>
  /** 解析智能体执行画像（ADR-0004 A2，label 由后端给出） */
  agentProfiles: ReturnType<typeof ref<AgentProfilesResponse | null>>
  /** 当前趋势维度（默认按智能体） */
  trendDimension: Ref<TrendDimension>
  load: () => Promise<void>
  /**
   * 切换 mock 模式：确认 → 保存（embedding 字段透传库内当前值）。
   * 取消/失败返回 false 且 mockEnabled 不变（失败由调用方回滚开关 UI）。
   */
  setMock: (next: boolean) => Promise<boolean>
  /** 切换趋势维度：仅重取趋势数据（不重载设置与摘要） */
  setTrendDimension: (dimension: TrendDimension) => Promise<void>
}

function createRuntimeConfig(deps: RuntimeConfigDeps): RuntimeConfigApi {
  const { getSettings, updateLlmSettings, getUsage, getUsageTrend, getAgentProfiles, confirmMock, notifyError, notifySuccess } = deps

  const loading = ref(false)
  const saving = ref(false)
  const mockEnabled = ref(false)
  const usage = ref<UsageSummary | null>(null)
  const usageTrend = ref<UsageTrendResponse | null>(null)
  const agentProfiles = ref<AgentProfilesResponse | null>(null)
  const trendDimension = ref<TrendDimension>('agent')

  /** 库内 llm_settings 快照（mock 切换时透传 embedding 字段，防止误清） */
  let settingsSnapshot: LlmSettings | null = null

  async function load(): Promise<void> {
    loading.value = true
    try {
      const [settings, usageSummary, trend, profiles] = await Promise.all([
        getSettings(),
        getUsage(USAGE_WINDOW_DAYS),
        getUsageTrend(USAGE_WINDOW_DAYS, trendDimension.value),
        getAgentProfiles(USAGE_WINDOW_DAYS),
      ])
      settingsSnapshot = settings
      mockEnabled.value = settings.llm_mock
      usage.value = usageSummary
      usageTrend.value = trend
      agentProfiles.value = profiles
    } catch (error) {
      notifyError(getApiErrorMessage(error, '加载运行时配置失败'))
    } finally {
      loading.value = false
    }
  }

  async function setTrendDimension(dimension: TrendDimension): Promise<void> {
    if (trendDimension.value === dimension) return
    trendDimension.value = dimension
    try {
      usageTrend.value = await getUsageTrend(USAGE_WINDOW_DAYS, dimension)
    } catch (error) {
      notifyError(getApiErrorMessage(error, '切换用量口径失败'))
    }
  }

  async function setMock(next: boolean): Promise<boolean> {
    if (saving.value) return false
    if (!(await confirmMock(next))) return false
    saving.value = true
    try {
      // embedding_api_base/embedding_model 必填全量：透传库内当前值（旧实现发
      // 空串，依赖后端容忍；R1 后三态语义下空串=清除，必须透传防误清）
      const snapshot = settingsSnapshot
      await updateLlmSettings({
        embedding_api_base: snapshot?.embedding_api_base ?? '',
        embedding_model: snapshot?.embedding_model ?? '',
        llm_mock: next,
      })
      mockEnabled.value = next
      notifySuccess(`Mock 模式已${next ? '开启' : '关闭'}`)
      return true
    } catch (error) {
      notifyError(getApiErrorMessage(error, '切换 Mock 模式失败'))
      return false
    } finally {
      saving.value = false
    }
  }

  return { loading, saving, mockEnabled, usage, usageTrend, agentProfiles, trendDimension, load, setMock, setTrendDimension }
}

export { createRuntimeConfig }

/* ---------------- 模块级单例 ---------------- */

let singleton: RuntimeConfigApi | null = null

export function useRuntimeConfig(): RuntimeConfigApi {
  if (!singleton) {
    singleton = createRuntimeConfig({
      getSettings: getLlmSettings,
      updateLlmSettings,
      getUsage: (days) => getUsageSummary(days),
      getUsageTrend: (days, dimension) => getUsageTrend(days, dimension),
      getAgentProfiles: (days) => getAgentProfiles(days),
      confirmMock: (next) =>
        new Promise<boolean>((resolve) => {
          Modal.confirm({
            title: next ? '开启 Mock 模式' : '关闭 Mock 模式',
            content: next
              ? '开启后所有 LLM 调用返回预设数据，不会产生真实输出，解析/生成结果均为模拟数据。确认开启？'
              : '关闭后将调用真实 LLM 服务，产生真实用量与费用。确认关闭？',
            okText: '确认',
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
