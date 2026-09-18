/**
 * useAnnotationView 批注视图模型测试（纯派生计算属性，无 DOM/API）.
 */
import { describe, expect, it } from 'vitest'
import { ref } from 'vue'
import { useAnnotationView } from '@/views/review/composables/useAnnotationView'
import type { AnnotationItem } from '@/types'

function item(id: string, status: 'open' | 'resolved' = 'open', from?: number, to?: number): AnnotationItem {
  return {
    id,
    chapter_no: '1',
    content: `内容${id}`,
    status,
    selection: from != null && to != null ? { from, to, text: '选中文字' } : null,
    created_by: 'u1',
    created_by_name: '用户1',
    created_at: '2026-01-01T00:00:00',
    updated_at: null,
  }
}

function setup() {
  const chapterKeys = ref(['1', '2', '3'])
  const activeChapter = ref('1')
  const filter = ref<'open' | 'resolved' | 'all'>('open')
  const selectionText = ref('')
  const map: Record<string, AnnotationItem[]> = {
    '1': [item('a', 'open', 0, 5), item('b', 'resolved', 10, 20), item('c', 'open')],
    '2': [item('d', 'open')],
  }
  const view = useAnnotationView({
    chapterKeys,
    getActiveChapter: () => activeChapter.value,
    getAnnotationCount: (no) => map[no]?.length ?? 0,
    getAnnotations: (no) => map[no] ?? [],
    getSelectionText: () => selectionText.value,
    filter,
  })
  return { chapterKeys, activeChapter, filter, selectionText, map, view }
}

describe('useAnnotationView', () => {
  it('annotationCounts：各章批注数映射', () => {
    const { view } = setup()
    expect(view.annotationCounts.value).toEqual({ '1': 3, '2': 1, '3': 0 })
  })

  it('annotatedCount：有批注的章节数（进度条）', () => {
    const { view } = setup()
    expect(view.annotatedCount.value).toBe(2)
  })

  it('open/resolved 计数随当前章节切换', () => {
    const { activeChapter, view } = setup()
    expect(view.openAnnotationCount.value).toBe(2) // 1 章：a 未解决 + c 未解决
    expect(view.resolvedAnnotationCount.value).toBe(1)
    activeChapter.value = '2'
    expect(view.openAnnotationCount.value).toBe(1)
    expect(view.resolvedAnnotationCount.value).toBe(0)
  })

  it('filteredAnnotations：open 只留未解决', () => {
    const { view } = setup()
    expect(view.filteredAnnotations.value.map((a) => a.id)).toEqual(['a', 'c'])
  })

  it('filteredAnnotations：resolved 只留已解决', () => {
    const { filter, view } = setup()
    filter.value = 'resolved'
    expect(view.filteredAnnotations.value.map((a) => a.id)).toEqual(['b'])
  })

  it('filteredAnnotations：all 返回全部', () => {
    const { filter, view } = setup()
    filter.value = 'all'
    expect(view.filteredAnnotations.value).toHaveLength(3)
  })

  it('annotationMarks：仅保留有选区定位的批注', () => {
    const { view } = setup()
    expect(view.annotationMarks.value).toEqual([
      { id: 'a', from: 0, to: 5, status: 'open' },
      { id: 'b', from: 10, to: 20, status: 'resolved' },
    ])
  })

  it('currentSelectionText：跟随选区文字', () => {
    const { selectionText, view } = setup()
    expect(view.currentSelectionText.value).toBe('')
    selectionText.value = '已选中文字'
    expect(view.currentSelectionText.value).toBe('已选中文字')
  })

  it('章节键变化驱动计数重算', () => {
    const { chapterKeys, view } = setup()
    chapterKeys.value = ['1', '2', '3', '4']
    expect(view.annotatedCount.value).toBe(2) // 新增空章节不计
    expect(view.annotationCounts.value).toEqual({ '1': 3, '2': 1, '3': 0, '4': 0 })
  })
})
