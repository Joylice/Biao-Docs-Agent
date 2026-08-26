/**
 * useEditorPanels：编辑器各面板显隐 / 模式 / 弹窗状态管理.
 *
 * 集中管理右侧属性面板、批注面板、版本历史面板、大纲、标尺、查找替换、
 * 缩放、链接弹窗等 UI 状态，避免在页面组件中散落声明。
 */
import { ref, type Ref } from 'vue'

export interface UseEditorPanelsReturn {
  /** 大纲面板显隐（默认 false：P0 用户习惯先看不到，从「视图」选项卡切换） */
  outlineVisible: Ref<boolean>
  /** 水平标尺显隐（默认 true：Word 风格默认显示标尺） */
  rulerVisible: Ref<boolean>
  /** 右侧属性面板显隐（默认 false：需要时打开） */
  propertiesVisible: Ref<boolean>
  /** 批注面板显隐（默认 false） */
  commentsVisible: Ref<boolean>
  /** 版本历史面板显隐（默认 false） */
  versionHistoryVisible: Ref<boolean>
  /** 查找替换面板显隐 */
  searchVisible: Ref<boolean>
  /** 查找替换面板模式 */
  searchMode: Ref<'find' | 'replace'>
  /** 缩放百分比（传给 WordEditor CSS 变量与 StatusBar） */
  zoom: Ref<number>
  /** 链接插入弹窗显隐 */
  linkModalOpen: Ref<boolean>
  /** 链接 URL 输入值 */
  linkUrl: Ref<string>
  /** 隐藏文件选择 input 的 ref */
  fileInputRef: Ref<HTMLInputElement | null>
  /** 搜索查询（右键菜单"查找"选中文字 → 通过 initial-query 传给 SearchPanel） */
  searchQuery: Ref<string>
  /** 互斥切换右侧面板：打开目标面板时关闭其余两个 */
  toggleProperties: () => void
  toggleComments: () => void
  toggleVersionHistory: () => void
}

export function useEditorPanels(): UseEditorPanelsReturn {
  /** 大纲面板显隐（默认 false：P0 用户习惯先看不到，从「视图」选项卡切换） */
  const outlineVisible = ref(false)
  /** 水平标尺显隐（默认 true：Word 风格默认显示标尺） */
  const rulerVisible = ref(true)
  /** 右侧属性面板显隐（默认 false：需要时打开） */
  const propertiesVisible = ref(false)
  /** 批注面板显隐（默认 false） */
  const commentsVisible = ref(false)
  /** 版本历史面板显隐（默认 false） */
  const versionHistoryVisible = ref(false)
  /** 查找替换面板显隐 */
  const searchVisible = ref(false)
  /** 查找替换面板模式 */
  const searchMode = ref<'find' | 'replace'>('find')
  /** 缩放百分比（传给 WordEditor CSS 变量与 StatusBar） */
  const zoom = ref(100)
  /** 链接插入弹窗显隐 */
  const linkModalOpen = ref(false)
  /** 链接 URL 输入值 */
  const linkUrl = ref('')
  /** 隐藏文件选择 input 的 ref */
  const fileInputRef = ref<HTMLInputElement | null>(null)
  /** 搜索查询（右键菜单"查找"选中文字 → 通过 initial-query 传给 SearchPanel） */
  const searchQuery = ref('')

  /** 互斥切换右侧面板：打开目标面板时关闭其余两个 */
  const toggleProperties = () => {
    propertiesVisible.value = !propertiesVisible.value
    commentsVisible.value = false
    versionHistoryVisible.value = false
  }

  const toggleComments = () => {
    commentsVisible.value = !commentsVisible.value
    propertiesVisible.value = false
    versionHistoryVisible.value = false
  }

  const toggleVersionHistory = () => {
    versionHistoryVisible.value = !versionHistoryVisible.value
    propertiesVisible.value = false
    commentsVisible.value = false
  }

  return {
    outlineVisible,
    rulerVisible,
    propertiesVisible,
    commentsVisible,
    versionHistoryVisible,
    searchVisible,
    searchMode,
    zoom,
    linkModalOpen,
    linkUrl,
    fileInputRef,
    searchQuery,
    toggleProperties,
    toggleComments,
    toggleVersionHistory,
  }
}
