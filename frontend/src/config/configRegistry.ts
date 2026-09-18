/**
 * 配置中心条目注册表 — 弹窗左侧两级导航与右侧面板的唯一驱动源（静态配置）.
 *
 * 结构（ARCH §1.5）：一级 6 分类，每分类挂 1..n 个条目；每个条目声明
 * component（右侧面板）与 save/isDirty 闭包（底部保存栏按条目粒度调用）。
 *
 * T01 阶段：全部条目 component 挂 PlaceholderPanel 占位、save 为 no-op、
 * isDirty 恒 false。
 * T02 阶段：语言模型分类四条目（llm:routes / llm:custom / llm:deepseek /
 * llm:zhipu）替换为真实面板（StageRoutesPanel / ProviderPanel）并接通
 * useRoutesConfig / useProvidersConfig 的 save/isDirty 闭包。
 * T03 阶段：知识库参数（retrieval:params → RetrievalPanel +
 * useRetrievalConfig）与系统设置（system:runtime → RuntimePanel，mock
 * 即改即存无 dirty 语义）替换真实面板。
 * T04 阶段：概览（overview:summary → OverviewPanel，只读）、网络搜索
 * （websearch:tavily/brave/searxng → WebSearchPanel + useExternalToolsConfig，
 * preset 条目化 + 乐观锁）与技能（skills:list → SkillsPanel，即改即存）
 * 替换真实面板。至此全部占位条目替换完毕（PlaceholderPanel 保留 import
 * 作 component 空位扩展用途）。
 *
 * UI 白名单机制（PRD P0-3）：语言模型分类仅暴露 LLM_UI_WHITELIST 内条目；
 * openai/anthropic/kimi/dashscope 等 provider 数据层保留（后端 GET 仍返回
 * 全量），仅不注册到 registry 实现隐藏——禁止任何"顺手清理"逻辑。
 */
import { markRaw, type Component } from 'vue'
import {
  ApartmentOutlined,
  CloudServerOutlined,
  CodeOutlined,
  ControlOutlined,
  DashboardOutlined,
  GlobalOutlined,
  SearchOutlined,
  SettingOutlined,
} from '@ant-design/icons-vue'
import ProviderPanel from '@/components/configCenter/panels/ProviderPanel.vue'
import StageRoutesPanel from '@/components/configCenter/panels/StageRoutesPanel.vue'
import RetrievalPanel from '@/components/configCenter/panels/RetrievalPanel.vue'
import RuntimePanel from '@/components/configCenter/panels/RuntimePanel.vue'
import OverviewPanel from '@/components/configCenter/panels/OverviewPanel.vue'
import WebSearchPanel from '@/components/configCenter/panels/WebSearchPanel.vue'
import SkillsPanel from '@/components/configCenter/panels/SkillsPanel.vue'
import { useProvidersConfig } from '@/composables/useProvidersConfig'
import { useRoutesConfig } from '@/composables/useRoutesConfig'
import { useRetrievalConfig } from '@/composables/useRetrievalConfig'
import { useExternalToolsConfig } from '@/composables/useExternalToolsConfig'

/* T02/T03/T04：分类条目绑定的 composable 单例（save/isDirty 闭包来源） */
const providersConfig = useProvidersConfig()
const routesConfig = useRoutesConfig()
const retrievalConfig = useRetrievalConfig()
const toolsConfig = useExternalToolsConfig()

/* ---------------- 类型 ---------------- */

export interface ConfigCategory {
  /** 分类 id（store.activeCategoryId 取值域） */
  id: string
  title: string
  desc: string
  icon: Component
}

export interface ConfigEntry {
  /** 条目 id，全局唯一，形如 '<分类>:<条目>' */
  id: string
  /** 所属分类 id */
  categoryId: string
  title: string
  desc: string
  icon: Component
  /** 右侧内容面板；null 表示与分类概览共用（保留扩展位） */
  component: Component | null
  /** 按条目粒度的保存闭包（T02+ 绑定对应 composable） */
  save: () => Promise<void>
  /** 条目是否有未保存改动（T02+ 由 composable 的 dirty 状态驱动） */
  isDirty: () => boolean
}

/* ---------------- 常量 ---------------- */

/** 概览条目 id（弹窗打开时的默认选中项） */
export const OVERVIEW_ITEM_ID = 'overview:summary'

/**
 * 语言模型分类 UI 白名单：仅列内条目注册到导航；
 * openai/anthropic/kimi/dashscope 等 provider 不注册（数据层保留）。
 */
export const LLM_UI_WHITELIST: readonly string[] = [
  'llm:routes',
  'llm:custom',
  'llm:deepseek',
  'llm:zhipu',
]

/* ---------------- T01 占位闭包（T02+ 逐条目替换） ---------------- */

const noopSave = async (): Promise<void> => {}
const notDirty = (): boolean => false

/* ---------------- 一级分类（6 项，PRD 定稿） ---------------- */

const categories: ConfigCategory[] = [
  {
    id: 'overview',
    title: '配置概览',
    desc: '模型与集成状态总览',
    icon: markRaw(DashboardOutlined),
  },
  {
    id: 'llm',
    title: '语言模型',
    desc: '阶段路由与提供方密钥',
    icon: markRaw(CloudServerOutlined),
  },
  {
    id: 'retrieval',
    title: '知识库参数',
    desc: 'Embedding 与检索策略',
    icon: markRaw(SearchOutlined),
  },
  {
    id: 'websearch',
    title: '网络搜索',
    desc: '外部工具与阶段绑定',
    icon: markRaw(GlobalOutlined),
  },
  {
    id: 'skills',
    title: '技能',
    desc: '技能启停与绑定',
    icon: markRaw(CodeOutlined),
  },
  {
    id: 'system',
    title: '系统设置',
    desc: 'Mock 运行控制',
    icon: markRaw(ControlOutlined),
  },
]

/* ---------------- 条目注册（T01 占位版） ---------------- */

const entries: ConfigEntry[] = [
  // 配置概览（T04：只读汇总 + 条目跳转，watch overviewVersion 自动刷新）
  {
    id: OVERVIEW_ITEM_ID,
    categoryId: 'overview',
    title: '状态总览',
    desc: '提供方 / 路由 / 检索 / 工具汇总',
    icon: markRaw(DashboardOutlined),
    component: markRaw(OverviewPanel),
    save: noopSave,
    isDirty: notDirty,
  },
  // 语言模型（严格按白名单注册；T02 起挂真实面板与保存闭包）
  {
    id: 'llm:routes',
    categoryId: 'llm',
    title: '阶段路由',
    desc: '5 个编制节点的模型分配',
    icon: markRaw(ApartmentOutlined),
    component: markRaw(StageRoutesPanel),
    save: () => routesConfig.save(),
    isDirty: () => routesConfig.isDirty.value,
  },
  {
    id: 'llm:custom',
    categoryId: 'llm',
    title: '自定义端点',
    desc: 'OpenAI 兼容私有化端点',
    icon: markRaw(SettingOutlined),
    component: markRaw(ProviderPanel),
    save: () => providersConfig.saveCustom(),
    isDirty: () => providersConfig.isDirtyCustom(),
  },
  {
    id: 'llm:deepseek',
    categoryId: 'llm',
    title: 'DeepSeek',
    desc: '密钥与端点配置',
    icon: markRaw(CloudServerOutlined),
    component: markRaw(ProviderPanel),
    save: () => providersConfig.saveProvider('llm:deepseek'),
    isDirty: () => providersConfig.isDirtyProvider('llm:deepseek'),
  },
  {
    id: 'llm:zhipu',
    categoryId: 'llm',
    title: '智谱 GLM',
    desc: '密钥与端点配置',
    icon: markRaw(CloudServerOutlined),
    component: markRaw(ProviderPanel),
    save: () => providersConfig.saveProvider('llm:zhipu'),
    isDirty: () => providersConfig.isDirtyProvider('llm:zhipu'),
  },
  // 知识库参数（T03：embedding + 检索参数 + rerank + 重建索引，单面板）
  {
    id: 'retrieval:params',
    categoryId: 'retrieval',
    title: '检索参数',
    desc: 'Embedding / 检索参数 / Rerank',
    icon: markRaw(SearchOutlined),
    component: markRaw(RetrievalPanel),
    save: () => retrievalConfig.save(),
    isDirty: () => retrievalConfig.isDirty(),
  },
  // 网络搜索（T04：按 preset 条目化，乐观锁保存；custom 工具不在 UI 暴露）
  {
    id: 'websearch:tavily',
    categoryId: 'websearch',
    title: 'Tavily',
    desc: '密钥注入 JSON body',
    icon: markRaw(GlobalOutlined),
    component: markRaw(WebSearchPanel),
    save: () => toolsConfig.savePreset('tavily'),
    isDirty: () => toolsConfig.isDirtyPreset('tavily'),
  },
  {
    id: 'websearch:brave',
    categoryId: 'websearch',
    title: 'Brave',
    desc: '密钥注入请求头',
    icon: markRaw(GlobalOutlined),
    component: markRaw(WebSearchPanel),
    save: () => toolsConfig.savePreset('brave'),
    isDirty: () => toolsConfig.isDirtyPreset('brave'),
  },
  {
    id: 'websearch:searxng',
    categoryId: 'websearch',
    title: 'SearXNG',
    desc: '无鉴权自建实例',
    icon: markRaw(GlobalOutlined),
    component: markRaw(WebSearchPanel),
    save: () => toolsConfig.savePreset('searxng'),
    isDirty: () => toolsConfig.isDirtyPreset('searxng'),
  },
  // 技能（T04：阶段启停/绑定均为即时操作，无表单保存语义 → save no-op）
  {
    id: 'skills:list',
    categoryId: 'skills',
    title: '技能列表',
    desc: '启停与阶段绑定',
    icon: markRaw(CodeOutlined),
    component: markRaw(SkillsPanel),
    save: noopSave,
    isDirty: notDirty,
  },
  // 系统设置（T03：mock 开关即改即存（含确认流），无表单保存语义 → save no-op）
  {
    id: 'system:runtime',
    categoryId: 'system',
    title: '运行控制',
    desc: 'Mock 开关 / 用量趋势',
    icon: markRaw(ControlOutlined),
    component: markRaw(RuntimePanel),
    save: noopSave,
    isDirty: notDirty,
  },
]

/* ---------------- 查询 API ---------------- */

/** 全部一级分类（导航一级渲染顺序） */
export function getConfigCategories(): readonly ConfigCategory[] {
  return categories
}

/** 指定分类下的条目（导航二级渲染顺序） */
export function getEntriesByCategory(categoryId: string): readonly ConfigEntry[] {
  return entries.filter((e) => e.categoryId === categoryId)
}

/** 按条目 id 解析条目；不存在返回 undefined（未注册 = UI 隐藏） */
export function resolveEntry(itemId: string | null | undefined): ConfigEntry | undefined {
  if (!itemId) return undefined
  return entries.find((e) => e.id === itemId)
}

/** 按条目 id 解析所属分类 id；不存在返回 null */
export function findCategoryOfEntry(itemId: string): string | null {
  return entries.find((e) => e.id === itemId)?.categoryId ?? null
}
