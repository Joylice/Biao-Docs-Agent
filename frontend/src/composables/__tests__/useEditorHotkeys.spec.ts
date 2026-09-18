/**
 * useEditorHotkeys 快捷键映射测试.
 *
 * mock useHotkeys 捕获绑定表，验证：
 * 1) 组合键 → 动作的映射完整（保存/查找/对齐/行高/字号/格式刷/标题级别/分页符/Escape）
 * 2) 各 handler 在给定编辑器/状态下的行为符合预期
 */
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { ref } from 'vue'

const captured = vi.hoisted(() => ({ bindings: [] as Array<{ combo: string; handler: (e?: unknown) => void }> }))

vi.mock('@/composables/useHotkeys', () => ({
  useHotkeys: (bindings: Array<{ combo: string; handler: (e?: unknown) => void }>) => {
    captured.bindings = bindings
  },
}))

const { useEditorHotkeys } = await import('@/composables/useEditorHotkeys')

/** 构建 Tiptap chain 链式 mock：chain().focus().setX(v).run() */
function mkEditor() {
  const run = vi.fn()
  const focus = {
    setTextAlign: vi.fn(() => ({ run })),
    setLineHeight: vi.fn(() => ({ run })),
    setHeading: vi.fn(() => ({ run })),
    setParagraph: vi.fn(() => ({ run })),
    setPageBreak: vi.fn(() => ({ run })),
  }
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const editor: any = {
    chain: vi.fn(() => ({ focus: () => focus })),
    isActive: vi.fn(),
    getAttributes: vi.fn(),
  }
  return { editor, focus, run }
}

function setup() {
  const { editor, focus, run } = mkEditor()
  const saveNow = vi.fn()
  const searchMode = ref<'find' | 'replace'>('find')
  const searchVisible = ref(false)
  const increaseFontSize = vi.fn()
  const decreaseFontSize = vi.fn()
  const brushActive = ref(false)
  const copyFormat = vi.fn()
  const applyFormat = vi.fn()
  const cancelBrush = vi.fn()

  useEditorHotkeys({
    getEditor: () => editor,
    saveNow,
    getSearch: () => ({ mode: searchMode, visible: searchVisible }),
    increaseFontSize,
    decreaseFontSize,
    getFormatBrush: () => ({ copyFormat, applyFormat, cancelBrush, brushActive }),
  })

  const byCombo = (combo: string) => {
    const b = captured.bindings.find((x) => x.combo === combo)
    if (!b) throw new Error(`binding not found: ${combo}`)
    return b
  }

  return {
    editor, focus, run, saveNow, searchMode, searchVisible,
    increaseFontSize, decreaseFontSize, brushActive, copyFormat, applyFormat, cancelBrush, byCombo,
  }
}

describe('useEditorHotkeys', () => {
  beforeEach(() => {
    captured.bindings = []
  })

  it('绑定表包含全部快捷键', () => {
    setup()
    const combos = captured.bindings.map((b) => b.combo).sort()
    expect(combos).toEqual([
      'alt+shift+arrowleft', 'alt+shift+arrowright',
      'ctrl+1', 'ctrl+2', 'ctrl+3', 'ctrl+e', 'ctrl+enter', 'ctrl+f', 'ctrl+h',
      'ctrl+j', 'ctrl+l', 'ctrl+r', 'ctrl+s', 'ctrl+shift+<', 'ctrl+shift+>',
      'ctrl+shift+c', 'ctrl+shift+v', 'escape',
    ])
  })

  it('ctrl+s 触发保存', () => {
    const { byCombo, saveNow } = setup()
    byCombo('ctrl+s').handler()
    expect(saveNow).toHaveBeenCalledTimes(1)
  })

  it('ctrl+f / ctrl+h 打开查找替换并切模式', () => {
    const { byCombo, searchMode, searchVisible } = setup()
    byCombo('ctrl+f').handler()
    expect(searchMode.value).toBe('find')
    expect(searchVisible.value).toBe(true)
    searchVisible.value = false
    byCombo('ctrl+h').handler()
    expect(searchMode.value).toBe('replace')
    expect(searchVisible.value).toBe(true)
  })

  it('ctrl+l/e/r/j 对齐', () => {
    const { byCombo, focus, run } = setup()
    const expects: Array<[string, string]> = [
      ['ctrl+l', 'left'], ['ctrl+e', 'center'], ['ctrl+r', 'right'], ['ctrl+j', 'justify'],
    ]
    for (const [combo, align] of expects) {
      byCombo(combo).handler()
      expect(focus.setTextAlign).toHaveBeenCalledWith(align)
    }
    expect(run).toHaveBeenCalledTimes(4)
  })

  it('ctrl+1/2/3 行高', () => {
    const { byCombo, focus, run } = setup()
    const expects: Array<[string, string]> = [
      ['ctrl+1', '1'], ['ctrl+2', '1.5'], ['ctrl+3', '2'],
    ]
    for (const [combo, height] of expects) {
      byCombo(combo).handler()
      expect(focus.setLineHeight).toHaveBeenCalledWith(height)
    }
    expect(run).toHaveBeenCalledTimes(3)
  })

  it('ctrl+shift+> / < 字号增减', () => {
    const { byCombo, increaseFontSize, decreaseFontSize } = setup()
    byCombo('ctrl+shift+>').handler()
    expect(increaseFontSize).toHaveBeenCalledTimes(1)
    byCombo('ctrl+shift+<').handler()
    expect(decreaseFontSize).toHaveBeenCalledTimes(1)
  })

  it('ctrl+shift+c 连续格式刷 / ctrl+shift+v 应用', () => {
    const { byCombo, copyFormat, applyFormat } = setup()
    byCombo('ctrl+shift+c').handler()
    expect(copyFormat).toHaveBeenCalledWith('continuous')
    byCombo('ctrl+shift+v').handler()
    expect(applyFormat).toHaveBeenCalledTimes(1)
  })

  it('alt+shift+←：正文 → H1；H2 → H3；H4 → 段落', () => {
    const { editor, byCombo, focus } = setup()
    // 正文：heading 检查均 false → setHeading level 1
    editor.isActive.mockReturnValue(false)
    byCombo('alt+shift+arrowleft').handler()
    expect(focus.setHeading).toHaveBeenLastCalledWith({ level: 1 })

    // H2：level4 检查 false，heading 检查 true，level=2 → setHeading 3
    editor.isActive.mockReset().mockReturnValueOnce(false).mockReturnValue(true)
    editor.getAttributes.mockReturnValue({ level: 2 })
    byCombo('alt+shift+arrowleft').handler()
    expect(focus.setHeading).toHaveBeenLastCalledWith({ level: 3 })

    // H4：level4 检查 true → setParagraph
    editor.isActive.mockReset().mockReturnValue(true)
    byCombo('alt+shift+arrowleft').handler()
    expect(focus.setParagraph).toHaveBeenCalledTimes(1)
  })

  it('alt+shift+→：H1 → 段落；H2 → H1；正文 → H4', () => {
    const { editor, byCombo, focus } = setup()
    // H1：level1 检查 true → setParagraph
    editor.isActive.mockReturnValue(true)
    byCombo('alt+shift+arrowright').handler()
    expect(focus.setParagraph).toHaveBeenCalledTimes(1)

    // H2：level1 检查 false，heading 检查 true，level=2 → setHeading 1
    editor.isActive.mockReset().mockReturnValueOnce(false).mockReturnValue(true)
    editor.getAttributes.mockReturnValue({ level: 2 })
    byCombo('alt+shift+arrowright').handler()
    expect(focus.setHeading).toHaveBeenLastCalledWith({ level: 1 })

    // 正文：heading 检查均 false → setHeading level 4
    editor.isActive.mockReset().mockReturnValue(false)
    byCombo('alt+shift+arrowright').handler()
    expect(focus.setHeading).toHaveBeenLastCalledWith({ level: 4 })
  })

  it('ctrl+enter：contenteditable 内跳过，编辑器外插入分页符', () => {
    const { byCombo, focus, run } = setup()
    byCombo('ctrl+enter').handler({ target: { isContentEditable: true } })
    expect(focus.setPageBreak).not.toHaveBeenCalled()
    byCombo('ctrl+enter').handler({ target: { isContentEditable: false } })
    expect(focus.setPageBreak).toHaveBeenCalledTimes(1)
    expect(run).toHaveBeenCalledTimes(1)
  })

  it('escape：优先关闭搜索面板，其次取消格式刷，均无则空操作', () => {
    const { byCombo, searchVisible, brushActive, cancelBrush } = setup()
    searchVisible.value = true
    brushActive.value = true
    byCombo('escape').handler()
    expect(searchVisible.value).toBe(false)
    expect(cancelBrush).not.toHaveBeenCalled()

    searchVisible.value = false
    brushActive.value = true
    byCombo('escape').handler()
    expect(cancelBrush).toHaveBeenCalledTimes(1)

    searchVisible.value = false
    brushActive.value = false
    byCombo('escape').handler()
    expect(cancelBrush).toHaveBeenCalledTimes(1) // 无新增调用
  })
})
