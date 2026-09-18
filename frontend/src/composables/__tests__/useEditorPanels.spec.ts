/**
 * useEditorPanels 面板状态测试（纯 ref 派生，无 DOM/API）.
 */
import { describe, expect, it } from 'vitest'
import { useEditorPanels } from '@/composables/useEditorPanels'

describe('useEditorPanels', () => {
  it('默认状态：大纲关 / 标尺开 / 缩放 100 / 查找模式 find', () => {
    const panels = useEditorPanels()
    expect(panels.outlineVisible.value).toBe(false)
    expect(panels.rulerVisible.value).toBe(true)
    expect(panels.propertiesVisible.value).toBe(false)
    expect(panels.commentsVisible.value).toBe(false)
    expect(panels.versionHistoryVisible.value).toBe(false)
    expect(panels.searchVisible.value).toBe(false)
    expect(panels.searchMode.value).toBe('find')
    expect(panels.zoom.value).toBe(100)
    expect(panels.linkModalOpen.value).toBe(false)
    expect(panels.linkUrl.value).toBe('')
    expect(panels.searchQuery.value).toBe('')
  })

  it('toggleProperties：打开属性时互斥关闭批注与版本面板', () => {
    const panels = useEditorPanels()
    panels.toggleProperties()
    expect(panels.propertiesVisible.value).toBe(true)
    expect(panels.commentsVisible.value).toBe(false)
    expect(panels.versionHistoryVisible.value).toBe(false)
    // 再开批注后切换属性：批注被关闭
    panels.toggleComments()
    expect(panels.commentsVisible.value).toBe(true)
    panels.toggleProperties()
    expect(panels.propertiesVisible.value).toBe(true)
    expect(panels.commentsVisible.value).toBe(false)
  })

  it('toggleComments：打开批注时互斥关闭属性与版本面板', () => {
    const panels = useEditorPanels()
    panels.toggleComments()
    expect(panels.commentsVisible.value).toBe(true)
    expect(panels.propertiesVisible.value).toBe(false)
    expect(panels.versionHistoryVisible.value).toBe(false)
  })

  it('toggleVersionHistory：打开版本时互斥关闭属性与批注面板', () => {
    const panels = useEditorPanels()
    panels.toggleVersionHistory()
    expect(panels.versionHistoryVisible.value).toBe(true)
    expect(panels.propertiesVisible.value).toBe(false)
    expect(panels.commentsVisible.value).toBe(false)
  })

  it('同一面板二次切换关闭，其余保持关闭', () => {
    const panels = useEditorPanels()
    panels.toggleProperties()
    panels.toggleProperties()
    expect(panels.propertiesVisible.value).toBe(false)
    expect(panels.commentsVisible.value).toBe(false)
    expect(panels.versionHistoryVisible.value).toBe(false)
  })
})
