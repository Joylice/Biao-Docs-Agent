/**
 * useEditorProperties 属性面板模型测试（mock Editor，无真实 Tiptap 实例）.
 * 覆盖：默认态 / 选区与段落派生 / 标题优先 / 字体 / 样式开关 / 表格 / 图片 /
 *       action 转发（chain 链）/ null 防护 / bump 强制重算.
 */
import { describe, expect, it, vi, beforeEach, afterEach } from 'vitest'
import { useEditorProperties } from '@/composables/useEditorProperties'

/* 最小 document 存根：composable 生命周期可能访问，直接调用不会触发
   onMounted（无组件实例），保留 stub 避免意外访问抛错 */
beforeEach(() => {
  vi.stubGlobal('document', {
    documentElement: { getAttribute: () => null },
  })
  // 静默 lifecycle 警告（onMounted/onBeforeUnmount 在 setup 外调用）
  vi.spyOn(console, 'warn').mockImplementation(() => {})
})

afterEach(() => {
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
})

interface MockEditorState {
  selectionEmpty: boolean
  active: Record<string, boolean>
  attrs: Record<string, Record<string, unknown>>
}

const CHAIN_METHODS = [
  'setTextAlign', 'setLineHeight', 'setIndent', 'setFontFamily', 'setFontSize',
  'setColor', 'toggleBold', 'toggleItalic', 'toggleUnderline', 'toggleStrike',
  'updateAttributes',
]

function mkEditor(init: Partial<MockEditorState> = {}) {
  const state: MockEditorState = {
    selectionEmpty: init.selectionEmpty ?? true,
    active: init.active ?? {},
    attrs: init.attrs ?? {},
  }
  const calls: string[] = []
  let focused: Record<string, ReturnType<typeof vi.fn>> | null = null

  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const editor: any = {
    state: { selection: { get empty() { return state.selectionEmpty } } },
    isActive: vi.fn((type: string) => Boolean(state.active[type])),
    getAttributes: vi.fn((type: string) => state.attrs[type] ?? {}),
    on: vi.fn(),
    off: vi.fn(),
    chain: vi.fn(() => {
      focused = {}
      for (const name of CHAIN_METHODS) {
        focused[name] = vi.fn((...args: unknown[]) => {
          calls.push(`${name}(${JSON.stringify(args)})`)
          return { run: vi.fn(() => { calls.push('run') }) }
        })
      }
      return { focus: () => focused! }
    }),
  }

  return { editor, state, calls, getFocused: () => focused }
}

describe('useEditorProperties 默认态（无 editor）', () => {
  it('状态默认值：无选区/无段落/无表格/无图片', () => {
    const p = useEditorProperties(() => undefined)
    expect(p.hasSelection.value).toBe(false)
    expect(p.isInParagraph.value).toBe(false)
    expect(p.isInTable.value).toBe(false)
    expect(p.isInImage.value).toBe(false)
  })

  it('属性默认值：左对齐 / 行高1.5 / 无缩进 / 图片 300x200', () => {
    const p = useEditorProperties(() => undefined)
    expect(p.textAlign.value).toBe('left')
    expect(p.lineHeight.value).toBe('1.5')
    expect(p.firstLineIndent.value).toBe(0)
    expect(p.imageWidth.value).toBe(300)
    expect(p.imageHeight.value).toBe(200)
    expect(p.imageAlign.value).toBe('left')
    expect(p.tableCellAlign.value).toBe('left')
  })

  it('无 editor 时操作不抛错', () => {
    const p = useEditorProperties(() => undefined)
    expect(() => {
      p.setTextAlign('right')
      p.setLineHeight('2')
      p.toggleBold()
      p.setTableCellAlign('center')
      p.setImageWidth(400)
    }).not.toThrow()
  })
})

describe('useEditorProperties 状态派生', () => {
  it('有选区 + 段落属性：对齐/行距/首行缩进', () => {
    const { editor, state } = mkEditor({
      selectionEmpty: false,
      active: { paragraph: true },
      attrs: { paragraph: { textAlign: 'center', lineHeight: '2', textIndent: '2em' } },
    })
    const p = useEditorProperties(() => editor)
    expect(p.hasSelection.value).toBe(true)
    expect(p.isInParagraph.value).toBe(true)
    expect(p.textAlign.value).toBe('center')
    expect(p.lineHeight.value).toBe('2')
    expect(p.firstLineIndent.value).toBe(2)

    state.attrs.paragraph = { textIndent: '0.5em' }
    p.bump()
    expect(p.firstLineIndent.value).toBe(0.5)
  })

  it('标题优先取 heading 属性（行高/缩进）', () => {
    const { editor } = mkEditor({
      active: { heading: true },
      attrs: { heading: { lineHeight: '1.2', textIndent: '1.5em' } },
    })
    const p = useEditorProperties(() => editor)
    expect(p.lineHeight.value).toBe('1.2')
    expect(p.firstLineIndent.value).toBe(1.5)
  })

  it('非 em 缩进值回退为 0', () => {
    const { editor } = mkEditor({
      active: { paragraph: true },
      attrs: { paragraph: { textIndent: '12px' } },
    })
    const p = useEditorProperties(() => editor)
    expect(p.firstLineIndent.value).toBe(0)
  })

  it('字体属性：family/size/color 从 textStyle 派生', () => {
    const { editor } = mkEditor({
      attrs: { textStyle: { fontFamily: '宋体', fontSize: '14pt', color: '#ff0000' } },
    })
    const p = useEditorProperties(() => editor)
    expect(p.fontFamily.value).toBe('宋体')
    expect(p.fontSize.value).toBe('14pt')
    expect(p.textColor.value).toBe('#ff0000')
  })

  it('样式开关：bold/italic/underline/strike', () => {
    const { editor } = mkEditor({
      active: { bold: true, italic: false, underline: true, strike: false },
    })
    const p = useEditorProperties(() => editor)
    expect(p.isBold.value).toBe(true)
    expect(p.isItalic.value).toBe(false)
    expect(p.isUnderline.value).toBe(true)
    expect(p.isStrike.value).toBe(false)
  })

  it('表格：isInTable + 单元格对齐', () => {
    const { editor } = mkEditor({
      active: { table: true },
      attrs: { tableCell: { textAlign: 'center' } },
    })
    const p = useEditorProperties(() => editor)
    expect(p.isInTable.value).toBe(true)
    expect(p.tableCellAlign.value).toBe('center')
  })

  it('图片：isInImage + 宽高/对齐', () => {
    const { editor } = mkEditor({
      active: { image: true },
      attrs: { image: { width: 640, height: 480, align: 'center' } },
    })
    const p = useEditorProperties(() => editor)
    expect(p.isInImage.value).toBe(true)
    expect(p.imageWidth.value).toBe(640)
    expect(p.imageHeight.value).toBe(480)
    expect(p.imageAlign.value).toBe('center')
  })

  it('选项常量导出：调色板/缩进/对齐', () => {
    const p = useEditorProperties(() => undefined)
    expect(p.TEXT_COLOR_PRESETS).toBeInstanceOf(Array)
    expect(p.BORDER_COLOR_PRESETS).toHaveLength(9)
    expect(p.BG_COLOR_PRESETS).toHaveLength(8)
    expect(p.indentOptions.map((o) => o.value)).toEqual(['0', '2', '4', '6'])
    expect(p.tableCellAligns.map((a) => a.value)).toEqual(['left', 'center', 'right'])
  })
})

describe('useEditorProperties action 转发', () => {
  it('段落操作走 chain().focus().xxx().run()', () => {
    const { editor, calls } = mkEditor()
    const p = useEditorProperties(() => editor)
    p.setTextAlign('right')
    expect(calls).toContain('setTextAlign(["right"])')
    expect(calls).toContain('run')

    p.setLineHeight('2')
    expect(calls).toContain('setLineHeight(["2"])')
    p.setFirstLineIndent(2)
    expect(calls).toContain('setIndent([2])')
  })

  it('字体操作：family/size/color 与四个 toggle', () => {
    const { editor, calls } = mkEditor()
    const p = useEditorProperties(() => editor)
    p.setFontFamily('黑体')
    p.setFontSize('16pt')
    p.setTextColor('#00ff00')
    expect(calls).toContain('setFontFamily(["黑体"])')
    expect(calls).toContain('setFontSize(["16pt"])')
    expect(calls).toContain('setColor(["#00ff00"])')

    p.toggleBold()
    p.toggleItalic()
    p.toggleUnderline()
    p.toggleStrike()
    expect(calls).toContain('toggleBold([])')
    expect(calls).toContain('toggleItalic([])')
    expect(calls).toContain('toggleUnderline([])')
    expect(calls).toContain('toggleStrike([])')
  })

  it('表格操作：updateAttributes 单元格对齐/底纹（空串→null）', () => {
    const { editor, calls } = mkEditor()
    const p = useEditorProperties(() => editor)
    p.setTableCellAlign('center')
    expect(calls).toContain('updateAttributes(["tableCell",{"textAlign":"center"}])')

    p.setTableBgColor('#f5f5f5')
    expect(calls).toContain('updateAttributes(["tableCell",{"backgroundColor":"#f5f5f5"}])')

    p.setTableBgColor('')
    expect(calls).toContain('updateAttributes(["tableCell",{"backgroundColor":null}])')

    p.setTableBorderColor('#000000') // 预留空实现，不产生链调用
    expect(calls.filter((c) => c.startsWith('updateAttributes')).length).toBe(3)
  })

  it('图片操作：宽/高/对齐 updateAttributes', () => {
    const { editor, calls } = mkEditor()
    const p = useEditorProperties(() => editor)
    p.setImageWidth(640)
    expect(calls).toContain('updateAttributes(["image",{"width":640}])')
    p.setImageHeight('480')
    expect(calls).toContain('updateAttributes(["image",{"height":480}])')
    p.setImageAlign('right')
    expect(calls).toContain('updateAttributes(["image",{"align":"right"}])')
  })

  it('null 防护：图片宽高传 null 不触发链调用', () => {
    const { editor, calls } = mkEditor()
    const p = useEditorProperties(() => editor)
    p.setImageWidth(null)
    p.setImageHeight(null)
    expect(editor.chain).not.toHaveBeenCalled()
    expect(calls).toHaveLength(0)
  })
})

describe('useEditorProperties bump 重算', () => {
  it('editor 状态变化后需 bump 才刷新派生值（模拟 transaction）', () => {
    const { editor, state } = mkEditor({
      active: { bold: true },
      attrs: { textStyle: { color: '#000000' } },
    })
    const p = useEditorProperties(() => editor)
    expect(p.isBold.value).toBe(true)
    expect(p.textColor.value).toBe('#000000')

    state.active.bold = false
    state.attrs.textStyle = { color: '#ff0000' }
    // 缓存未失效
    expect(p.isBold.value).toBe(true)
    expect(p.textColor.value).toBe('#000000')

    p.bump()
    expect(p.isBold.value).toBe(false)
    expect(p.textColor.value).toBe('#ff0000')
  })
})
