/**
 * useEditorContextMenu 右键菜单逻辑模型测试（mock Editor + 剪贴板）.
 * 覆盖：默认态 / computeMenuPosition 纯函数边界 / 定位与选区快照 / 命令链转发 /
 *       剪贴板（含异常静默）/ 插入查找 AI 回调 / Esc 与外部点击关闭.
 */
import { describe, expect, it, vi, beforeEach, afterEach } from 'vitest'
import {
  useEditorContextMenu,
  computeMenuPosition,
  type AiAction,
} from '@/composables/useEditorContextMenu'

const CHAIN_METHODS = [
  'setTextAlign', 'setFontFamily', 'setFontSize', 'setColor', 'setLineHeight',
  'insertTable', 'insertContent', 'deleteSelection',
]

function mkEditor(over: Record<string, unknown> = {}) {
  const calls: string[] = []
  let focused: Record<string, ReturnType<typeof vi.fn>> | null = null
  const { state: overState, ...rest } = over
  const sel = (overState as { selection?: { from: number; to: number } } | undefined)?.selection
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const editor: any = {
    isDestroyed: false,
    view: { dom: { addEventListener: vi.fn(), removeEventListener: vi.fn() } },
    state: {
      selection: { from: 0, to: 0, ...(sel ?? {}) },
      doc: { textBetween: vi.fn(() => '选中文字') },
    },
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
    ...rest,
  }
  return { editor, calls, getFocused: () => focused }
}

function setup(over: { editor?: ReturnType<typeof mkEditor>['editor']; editable?: boolean | undefined } = {}) {
  const { editor } = over.editor ? { editor: over.editor } : mkEditor()
  const onInsertLink = vi.fn()
  const onInsertImage = vi.fn()
  const onFind = vi.fn()
  const onAiAction = vi.fn()
  const cm = useEditorContextMenu({
    getEditor: () => editor,
    getEditable: () => over.editable,
    onInsertLink,
    onInsertImage,
    onFind,
    onAiAction,
  })
  return { cm, editor, onInsertLink, onInsertImage, onFind, onAiAction }
}

beforeEach(() => {
  vi.stubGlobal('window', { innerWidth: 1920, innerHeight: 1080 })
  vi.stubGlobal('document', {
    documentElement: { getAttribute: () => null },
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
  })
  vi.stubGlobal('navigator', {
    clipboard: {
      writeText: vi.fn().mockResolvedValue(undefined),
      readText: vi.fn().mockResolvedValue('粘贴内容'),
    },
  })
  vi.spyOn(console, 'warn').mockImplementation(() => {})
})

afterEach(() => {
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
})

describe('computeMenuPosition 纯函数', () => {
  it('视口内坐标原样返回，不靠右', () => {
    expect(computeMenuPosition(300, 200, 1920, 1080)).toEqual({ x: 300, y: 200, onRight: false })
  })

  it('右半屏判定 onRight', () => {
    expect(computeMenuPosition(1000, 200, 1920, 1080).onRight).toBe(true)
    expect(computeMenuPosition(960, 200, 1920, 1080).onRight).toBe(false)
  })

  it('右/下越界时 clamp 到视口内（含负值保护）', () => {
    expect(computeMenuPosition(1900, 1000, 1920, 1080)).toEqual({ x: 1700, y: 660, onRight: true })
    expect(computeMenuPosition(5, 5, 100, 100)).toEqual({ x: 0, y: 0, onRight: false })
  })

  it('自定义菜单尺寸生效', () => {
    expect(computeMenuPosition(100, 100, 200, 200, 150, 150)).toEqual({ x: 50, y: 50, onRight: false })
  })
})

describe('useEditorContextMenu 默认态', () => {
  it('菜单关闭、无 AI 权限（无选区）', () => {
    const { cm } = setup()
    expect(cm.menuVisible.value).toBe(false)
    expect(cm.menuX.value).toBe(0)
    expect(cm.menuY.value).toBe(0)
    expect(cm.menuOnRight.value).toBe(false)
    expect(cm.hasSelection.value).toBe(false)
    expect(cm.canAiAction.value).toBe(false)
  })

  it('只读模式下即使有选区 AI 也禁用', () => {
    const { editor } = mkEditor({ state: { selection: { from: 0, to: 5 } } })
    const { cm } = setup({ editor, editable: false })
    cm.handleContextMenu({ clientX: 10, clientY: 10, preventDefault: vi.fn() } as unknown as MouseEvent)
    expect(cm.hasSelection.value).toBe(true)
    expect(cm.canAiAction.value).toBe(false)
  })

  it('无 editor 时 run/cut/paste 不抛错', async () => {
    const cm = useEditorContextMenu({
      getEditor: () => undefined,
      getEditable: () => undefined,
      onInsertLink: vi.fn(),
      onInsertImage: vi.fn(),
      onFind: vi.fn(),
      onAiAction: vi.fn(),
    })
    expect(() => cm.run(() => undefined as never)).not.toThrow()
    await expect(cm.handleCut()).resolves.toBeUndefined()
    await expect(cm.handlePaste()).resolves.toBeUndefined()
    expect(cm.menuVisible.value).toBe(false)
  })

  it('选项 items 复用扩展预设', () => {
    const { cm } = setup()
    expect(cm.fontFamilyItems.length).toBeGreaterThan(0)
    expect(cm.fontSizeItems.length).toBeGreaterThan(0)
    expect(cm.lineHeightItems.length).toBeGreaterThan(0)
    expect(cm.TEXT_COLOR_PRESETS).toBeInstanceOf(Array)
  })
})

describe('定位与选区快照', () => {
  it('contextmenu 打开菜单：preventDefault + 选区快照 + 坐标写入', () => {
    const { editor } = mkEditor({ state: { selection: { from: 2, to: 8 } } })
    const { cm } = setup({ editor })
    const preventDefault = vi.fn()
    cm.handleContextMenu({ clientX: 300, clientY: 200, preventDefault } as unknown as MouseEvent)
    expect(preventDefault).toHaveBeenCalled()
    expect(cm.hasSelection.value).toBe(true)
    expect(cm.menuVisible.value).toBe(true)
    expect(cm.menuX.value).toBe(300)
    expect(cm.menuY.value).toBe(200)
    expect(cm.menuOnRight.value).toBe(false)
    expect(cm.canAiAction.value).toBe(true)
  })

  it('无选区快照为 false；右半屏置 menuOnRight', () => {
    const { cm } = setup()
    cm.handleContextMenu({ clientX: 1200, clientY: 300, preventDefault: vi.fn() } as unknown as MouseEvent)
    expect(cm.hasSelection.value).toBe(false)
    expect(cm.menuOnRight.value).toBe(true)
  })

  it('editor 已销毁时不打开菜单', () => {
    const { editor } = mkEditor({ isDestroyed: true })
    const { cm } = setup({ editor })
    const preventDefault = vi.fn()
    cm.handleContextMenu({ clientX: 100, clientY: 100, preventDefault } as unknown as MouseEvent)
    expect(preventDefault).not.toHaveBeenCalled()
    expect(cm.menuVisible.value).toBe(false)
  })
})

describe('命令链执行', () => {
  it('run 执行链并关闭菜单', () => {
    const { editor, calls } = mkEditor()
    const { cm } = setup({ editor })
    cm.handleContextMenu({ clientX: 10, clientY: 10, preventDefault: vi.fn() } as unknown as MouseEvent)
    cm.run((chain) => chain.setTextAlign('center'))
    expect(calls).toContain('setTextAlign(["center"])')
    expect(calls).toContain('run')
    expect(cm.menuVisible.value).toBe(false)
  })

  it('对齐/字体/字号/颜色/行距/表格 全部链转发', () => {
    const { editor, calls } = mkEditor()
    const { cm } = setup({ editor })
    cm.runAlign('right')
    cm.handleFontFamily('宋体')
    cm.handleFontSize('16pt')
    cm.handleTextColor('#ff0000')
    cm.handleLineHeight('2')
    cm.handleInsertTable()
    expect(calls).toContain('setTextAlign(["right"])')
    expect(calls).toContain('setFontFamily(["宋体"])')
    expect(calls).toContain('setFontSize(["16pt"])')
    expect(calls).toContain('setColor(["#ff0000"])')
    expect(calls).toContain('setLineHeight(["2"])')
    expect(calls).toContain('insertTable([{"rows":3,"cols":3,"withHeaderRow":true}])')
    expect(calls.filter((c) => c === 'run').length).toBe(6)
  })
})

describe('剪贴板操作', () => {
  it('无选区时 cut/copy 不触碰剪贴板与编辑器', async () => {
    const { editor, calls } = mkEditor()
    const { cm } = setup({ editor })
    await cm.handleCut()
    await cm.handleCopy()
    expect(editor.chain).not.toHaveBeenCalled()
    expect(calls).toHaveLength(0)
  })

  it('cut：写入剪贴板 + deleteSelection', async () => {
    const { editor, calls } = mkEditor({ state: { selection: { from: 0, to: 5 } } })
    const { cm } = setup({ editor })
    cm.handleContextMenu({ clientX: 10, clientY: 10, preventDefault: vi.fn() } as unknown as MouseEvent)
    await cm.handleCut()
    const clipboard = (navigator as unknown as { clipboard: { writeText: ReturnType<typeof vi.fn> } }).clipboard
    expect(clipboard.writeText).toHaveBeenCalledWith('选中文字')
    expect(calls).toContain('deleteSelection([])')
    expect(cm.menuVisible.value).toBe(false)
  })

  it('copy：仅写入剪贴板，不删除选区', async () => {
    const { editor, calls } = mkEditor({ state: { selection: { from: 0, to: 5 } } })
    const { cm } = setup({ editor })
    cm.handleContextMenu({ clientX: 10, clientY: 10, preventDefault: vi.fn() } as unknown as MouseEvent)
    await cm.handleCopy()
    const clipboard = (navigator as unknown as { clipboard: { writeText: ReturnType<typeof vi.fn> } }).clipboard
    expect(clipboard.writeText).toHaveBeenCalledWith('选中文字')
    expect(calls).not.toContain('deleteSelection([])')
  })

  it('paste：读取剪贴板并 insertContent', async () => {
    const { editor, calls } = mkEditor()
    const { cm } = setup({ editor })
    await cm.handlePaste()
    expect(calls).toContain('insertContent(["粘贴内容"])')
    expect(cm.menuVisible.value).toBe(false)
  })

  it('剪贴板写入/读取失败时静默（不抛错不崩溃）', async () => {
    const clipboard = {
      writeText: vi.fn().mockRejectedValue(new Error('denied')),
      readText: vi.fn().mockRejectedValue(new Error('denied')),
    }
    vi.stubGlobal('navigator', { clipboard })
    const { editor } = mkEditor({ state: { selection: { from: 0, to: 5 } } })
    const { cm } = setup({ editor })
    await expect(cm.handleCut()).resolves.toBeUndefined()
    await expect(cm.handlePaste()).resolves.toBeUndefined()
    expect(editor.chain).not.toHaveBeenCalled()
  })
})

describe('插入 / 查找 / AI 回调', () => {
  it('插入链接/图片：关闭菜单并上抛回调', () => {
    const { cm, onInsertLink, onInsertImage } = setup()
    cm.handleInsertLink()
    expect(onInsertLink).toHaveBeenCalledTimes(1)
    expect(cm.menuVisible.value).toBe(false)
    cm.handleInsertImage()
    expect(onInsertImage).toHaveBeenCalledTimes(1)
  })

  it('查找：无选区忽略，有选区回调选中文本', () => {
    const { cm, onFind } = setup()
    cm.handleFind()
    expect(onFind).not.toHaveBeenCalled()

    const { editor } = mkEditor({ state: { selection: { from: 0, to: 5 } } })
    const { cm: cm2, onFind: onFind2 } = setup({ editor })
    cm2.handleContextMenu({ clientX: 10, clientY: 10, preventDefault: vi.fn() } as unknown as MouseEvent)
    cm2.handleFind()
    expect(onFind2).toHaveBeenCalledWith('选中文字')
    expect(cm2.menuVisible.value).toBe(false)
  })

  it('AI：可编辑+有选区时上抛并关闭菜单', () => {
    const { editor } = mkEditor({ state: { selection: { from: 0, to: 5 } } })
    const { cm, onAiAction } = setup({ editor })
    cm.handleContextMenu({ clientX: 10, clientY: 10, preventDefault: vi.fn() } as unknown as MouseEvent)
    const actions: AiAction[] = ['polish', 'translate', 'expand']
    for (const a of actions) {
      cm.handleAi(a)
      expect(onAiAction).toHaveBeenCalledWith(a)
    }
    expect(cm.menuVisible.value).toBe(false)
  })

  it('AI：无选区时忽略回调', () => {
    const { cm, onAiAction } = setup()
    cm.handleAi('polish')
    expect(onAiAction).not.toHaveBeenCalled()
  })
})

describe('Esc 与外部点击关闭', () => {
  it('Escape 关闭菜单并 preventDefault', () => {
    const { cm } = setup()
    cm.handleContextMenu({ clientX: 10, clientY: 10, preventDefault: vi.fn() } as unknown as MouseEvent)
    const preventDefault = vi.fn()
    cm.handleKeydown({ key: 'Escape', preventDefault } as unknown as KeyboardEvent)
    expect(preventDefault).toHaveBeenCalled()
    expect(cm.menuVisible.value).toBe(false)
  })

  it('非 Escape 键不动作', () => {
    const { cm } = setup()
    cm.handleContextMenu({ clientX: 10, clientY: 10, preventDefault: vi.fn() } as unknown as MouseEvent)
    const preventDefault = vi.fn()
    cm.handleKeydown({ key: 'Enter', preventDefault } as unknown as KeyboardEvent)
    expect(preventDefault).not.toHaveBeenCalled()
    expect(cm.menuVisible.value).toBe(true)
  })

  it('点击菜单外部关闭，点击菜单内部不关闭', () => {
    const { cm } = setup()
    cm.handleContextMenu({ clientX: 10, clientY: 10, preventDefault: vi.fn() } as unknown as MouseEvent)
    cm.handleDocumentClick({ target: { closest: () => null } } as unknown as MouseEvent)
    expect(cm.menuVisible.value).toBe(false)

    cm.handleContextMenu({ clientX: 10, clientY: 10, preventDefault: vi.fn() } as unknown as MouseEvent)
    cm.handleDocumentClick({ target: { closest: () => ({}) } } as unknown as MouseEvent)
    expect(cm.menuVisible.value).toBe(true)
  })
})
