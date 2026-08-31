/**
 * useAnnotations 批注域测试.
 *
 * mock @/api 的批注接口与 ant-design-vue message，验证：
 * 懒加载去重 / 增删乐观合并 / 状态切换失败回滚 / 选区设置。
 */
import { beforeEach, describe, expect, it, vi } from 'vitest'

vi.mock('ant-design-vue', () => ({
  message: { error: vi.fn(), success: vi.fn() },
}))

const mocks = vi.hoisted(() => ({
  fetchChapterAnnotations: vi.fn(),
  createChapterAnnotation: vi.fn(),
  deleteChapterAnnotation: vi.fn(),
  updateAnnotationStatus: vi.fn(),
}))

vi.mock('@/api', () => mocks)

const { useAnnotations } = await import('@/views/review/composables/useAnnotations')
const { message } = await import('ant-design-vue')
import type { AnnotationItem } from '@/types'

const PROJECT = 'p1'
const ok = (data: unknown) => ({ data: { code: 0, data } })

function item(id: string, status: 'open' | 'resolved' = 'open'): AnnotationItem {
  return {
    id,
    chapter_no: '1',
    content: `内容${id}`,
    status,
    selection: null,
    created_by: 'u1',
    created_by_name: '用户1',
    created_at: '2026-01-01T00:00:00',
    updated_at: null,
  }
}

describe('useAnnotations', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('loadAnnotations 懒加载：同一章节只拉一次', async () => {
    mocks.fetchChapterAnnotations.mockResolvedValue(ok({ items: [item('a')] }))
    const { loadAnnotations, annotationListOf, annotationLoaded } = useAnnotations(PROJECT)
    await loadAnnotations('1')
    expect(annotationListOf('1')).toHaveLength(1)
    expect(annotationLoaded.value['1']).toBe(true)
    await loadAnnotations('1')
    expect(mocks.fetchChapterAnnotations).toHaveBeenCalledTimes(1)
  })

  it('addAnnotation：空内容不请求', async () => {
    const { addAnnotation, newAnnotation } = useAnnotations(PROJECT)
    await addAnnotation('1')
    expect(mocks.createChapterAnnotation).not.toHaveBeenCalled()
    newAnnotation.value = '   '
    await addAnnotation('1')
    expect(mocks.createChapterAnnotation).not.toHaveBeenCalled()
  })

  it('addAnnotation 成功：清空输入与选区并重载列表', async () => {
    mocks.createChapterAnnotation.mockResolvedValue(ok({ id: 'a' }))
    mocks.fetchChapterAnnotations.mockResolvedValue(ok({ items: [item('a')] }))
    const { addAnnotation, newAnnotation, currentSelection, setSelection, annotationListOf } =
      useAnnotations(PROJECT)
    newAnnotation.value = '新批注'
    setSelection({ from: 0, to: 3, text: 'abc' })
    await addAnnotation('1')
    expect(mocks.createChapterAnnotation).toHaveBeenCalledWith(
      PROJECT, '1', '新批注', { from: 0, to: 3, text: 'abc' },
    )
    expect(newAnnotation.value).toBe('')
    expect(currentSelection.value).toBeNull()
    expect(annotationListOf('1')).toHaveLength(1)
  })

  it('addAnnotation 403 → 无权限提示', async () => {
    mocks.createChapterAnnotation.mockRejectedValue({ response: { status: 403 } })
    const { addAnnotation, newAnnotation } = useAnnotations(PROJECT)
    newAnnotation.value = 'x'
    await addAnnotation('1')
    expect(message.error).toHaveBeenCalledWith('无该章节批注权限')
  })

  it('toggleAnnotationStatus：乐观更新，失败回滚', async () => {
    const { toggleAnnotationStatus, annotationMap } = useAnnotations(PROJECT)
    annotationMap.value['1'] = [item('a')]
    mocks.updateAnnotationStatus.mockResolvedValue(ok(item('a', 'resolved')))
    await toggleAnnotationStatus('1', 'a')
    expect(annotationMap.value['1'][0].status).toBe('resolved')

    mocks.updateAnnotationStatus.mockRejectedValue(new Error('网络错误'))
    await toggleAnnotationStatus('1', 'a')
    expect(annotationMap.value['1'][0].status).toBe('resolved') // 回滚到调用前状态
    expect(message.error).toHaveBeenCalledWith('状态更新失败')
  })

  it('mergeUpdatedAnnotation：patch 合并到本地列表', () => {
    const { annotationMap, mergeUpdatedAnnotation } = useAnnotations(PROJECT)
    annotationMap.value['1'] = [item('a')]
    mergeUpdatedAnnotation('1', 'a', { content: '已编辑' })
    expect(annotationMap.value['1'][0].content).toBe('已编辑')
  })

  it('deleteAnnotation 成功：本地移除 + 成功提示', async () => {
    mocks.deleteChapterAnnotation.mockResolvedValue(ok(null))
    const { annotationMap, deleteAnnotation } = useAnnotations(PROJECT)
    annotationMap.value['1'] = [item('a'), item('b')]
    await deleteAnnotation('1', 'a')
    expect(annotationMap.value['1']).toHaveLength(1)
    expect(annotationMap.value['1'][0].id).toBe('b')
    expect(message.success).toHaveBeenCalled()
  })

  it('annotationCountOf 返回章节批注数', () => {
    const { annotationMap, annotationCountOf } = useAnnotations(PROJECT)
    annotationMap.value['1'] = [item('a'), item('b')]
    expect(annotationCountOf('1')).toBe(2)
    expect(annotationCountOf('9')).toBe(0)
  })
})
