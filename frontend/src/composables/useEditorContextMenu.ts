import { computed, ref, watch, onMounted, onBeforeUnmount } from 'vue'
import type { Editor, ChainedCommands } from '@tiptap/core'
import { FONT_FAMILY_OPTIONS } from '@/components/editor/extensions/font-family'
import { FONT_SIZE_OPTIONS } from '@/components/editor/extensions/font-size'
import { LINE_HEIGHT_OPTIONS } from '@/components/editor/extensions/line-height'
import { TEXT_COLOR_PRESETS } from '@/components/editor/extensions/text-color'

export type AiAction = 'polish' | 'translate' | 'expand'

export interface EditorContextMenuDeps {
  /** 编辑器实例（getter 注入，支持响应式换绑） */
  getEditor: () => Editor | undefined
  /** 是否可编辑（只读/无权限时 AI 与编辑菜单保持禁用） */
  getEditable: () => boolean | undefined
  onInsertLink: () => void
  onInsertImage: () => void
  onFind: (text: string) => void
  onAiAction: (action: AiAction) => void
}

/** 计算右键菜单定位：防止超出视口边界；返回是否靠右展开 */
export function computeMenuPosition(
  clientX: number,
  clientY: number,
  viewportW: number,
  viewportH: number,
  menuW = 220,
  menuH = 420,
): { x: number; y: number; onRight: boolean } {
  let x = clientX
  let y = clientY
  const onRight = x > viewportW / 2
  if (x + menuW > viewportW) {
    x = Math.max(0, viewportW - menuW)
  }
  if (y + menuH > viewportH) {
    y = Math.max(0, viewportH - menuH)
  }
  return { x, y, onRight }
}

/**
 * useEditorContextMenu：WordEditorContextMenu 右键菜单的完整逻辑模型
 * - contextmenu 事件绑定在 editor.view.dom 上（watch editor 自动绑定/解绑）
 * - 菜单通过 Teleport + fixed 定位渲染，z-index 1050
 * - 字体/字号/颜色/行距使用 CSS :hover 子菜单（无需 JS 管理显隐）
 * - 剪切/复制/粘贴使用 Clipboard API + editor 命令
 * - 点击菜单项后关闭菜单；点击外部 / Esc 关闭菜单
 */
export function useEditorContextMenu(deps: EditorContextMenuDeps) {
  const { getEditor, getEditable, onInsertLink, onInsertImage, onFind, onAiAction } = deps

  /* ---------------- 菜单状态 ---------------- */
  const menuVisible = ref(false)
  const menuX = ref(0)
  const menuY = ref(0)
  const menuOnRight = ref(false)
  const hasSelection = ref(false)

  /** AI 操作是否可用：编辑器可编辑且有选中文字 */
  const canAiAction = computed(() => getEditable() !== false && hasSelection.value)

  /* ---------------- 下拉选项（复用扩展预设） ---------------- */
  const fontFamilyItems = FONT_FAMILY_OPTIONS.map((o) => ({ label: o.label, value: o.value }))
  const fontSizeItems = FONT_SIZE_OPTIONS.map((o) => ({ label: `${o.label} · ${o.value}`, value: o.value }))
  const lineHeightItems = LINE_HEIGHT_OPTIONS.map((v) => ({ label: `行高 ${v}`, value: String(v) }))

  /* ---------------- 菜单显隐控制 ---------------- */
  const closeMenu = () => {
    menuVisible.value = false
  }

  /** 执行链式命令并关闭菜单 */
  const run = (apply: (chain: ChainedCommands) => ChainedCommands) => {
    const inst = getEditor()
    if (!inst) return
    apply(inst.chain().focus()).run()
    closeMenu()
  }

  const runAlign = (align: string) => {
    run((chain) => chain.setTextAlign(align))
  }

  const handleFontFamily = (value: string) => {
    run((chain) => chain.setFontFamily(value))
  }

  const handleFontSize = (value: string) => {
    run((chain) => chain.setFontSize(value))
  }

  const handleTextColor = (color: string) => {
    run((chain) => chain.setColor(color))
  }

  const handleLineHeight = (value: string) => {
    run((chain) => chain.setLineHeight(value))
  }

  /* ---------------- 剪贴板操作 ---------------- */
  /** 获取当前选中文本（无选区时返回空串） */
  const getSelectedText = (): string => {
    const inst = getEditor()
    if (!inst) return ''
    const { from, to } = inst.state.selection
    if (from === to) return ''
    return inst.state.doc.textBetween(from, to, ' ', ' ')
  }

  const handleCut = async () => {
    if (!hasSelection.value) return
    closeMenu()
    const inst = getEditor()
    if (!inst) return
    const text = getSelectedText()
    try {
      await navigator.clipboard.writeText(text)
      inst.chain().focus().deleteSelection().run()
    } catch {
      // 剪贴板写入失败（非安全上下文或权限不足）
    }
  }

  const handleCopy = async () => {
    if (!hasSelection.value) return
    closeMenu()
    const text = getSelectedText()
    try {
      await navigator.clipboard.writeText(text)
    } catch {
      // 剪贴板写入失败
    }
  }

  const handlePaste = async () => {
    closeMenu()
    const inst = getEditor()
    if (!inst) return
    try {
      const text = await navigator.clipboard.readText()
      if (text) {
        inst.chain().focus().insertContent(text).run()
      }
    } catch {
      // 剪贴板读取失败
    }
  }

  /** 粘贴为纯文本：与普通粘贴一致（readText 仅返回纯文本） */
  const handlePastePlain = handlePaste

  /* ---------------- 插入 / 查找 / AI 操作 ---------------- */
  const handleInsertLink = () => {
    closeMenu()
    onInsertLink()
  }

  const handleInsertImage = () => {
    closeMenu()
    onInsertImage()
  }

  const handleInsertTable = () => {
    run((chain) => chain.insertTable({ rows: 3, cols: 3, withHeaderRow: true }))
  }

  const handleFind = () => {
    if (!hasSelection.value) return
    const text = getSelectedText()
    closeMenu()
    if (text) {
      onFind(text)
    }
  }

  const handleAi = (action: AiAction) => {
    if (!canAiAction.value) return
    onAiAction(action)
    menuVisible.value = false
  }

  /* ---------------- contextmenu 事件处理：定位菜单 + 读取选区状态 ---------------- */
  const handleContextMenu = (e: MouseEvent) => {
    const inst = getEditor()
    if (!inst || inst.isDestroyed) return
    e.preventDefault()

    // 读取选区状态（在打开菜单时快照）
    const { from, to } = inst.state.selection
    hasSelection.value = from !== to

    // 菜单定位：防止超出视口边界
    const { x, y, onRight } = computeMenuPosition(
      e.clientX,
      e.clientY,
      window.innerWidth,
      window.innerHeight,
    )
    menuOnRight.value = onRight
    menuX.value = x
    menuY.value = y
    menuVisible.value = true
  }

  /** 点击菜单外部关闭菜单 */
  const handleDocumentClick = (e: MouseEvent) => {
    if (!menuVisible.value) return
    const target = e.target as HTMLElement
    if (!target.closest('.ctx-menu')) {
      closeMenu()
    }
  }

  /** Esc 关闭菜单 */
  const handleKeydown = (e: KeyboardEvent) => {
    if (e.key === 'Escape' && menuVisible.value) {
      e.preventDefault()
      closeMenu()
    }
  }

  /* ---------------- editor contextmenu 监听绑定 ---------------- */
  watch(
    () => getEditor(),
    (inst, oldInst) => {
      if (oldInst && !oldInst.isDestroyed) {
        oldInst.view.dom.removeEventListener('contextmenu', handleContextMenu)
      }
      if (inst && !inst.isDestroyed) {
        inst.view.dom.addEventListener('contextmenu', handleContextMenu)
      }
    },
    { immediate: true },
  )

  /* ---------------- 生命周期 ---------------- */
  onMounted(() => {
    document.addEventListener('click', handleDocumentClick)
    document.addEventListener('keydown', handleKeydown)
  })

  onBeforeUnmount(() => {
    document.removeEventListener('click', handleDocumentClick)
    document.removeEventListener('keydown', handleKeydown)
    const inst = getEditor()
    if (inst && !inst.isDestroyed) {
      inst.view.dom.removeEventListener('contextmenu', handleContextMenu)
    }
  })

  return {
    menuVisible,
    menuX,
    menuY,
    menuOnRight,
    hasSelection,
    canAiAction,
    fontFamilyItems,
    fontSizeItems,
    lineHeightItems,
    TEXT_COLOR_PRESETS,
    run,
    runAlign,
    handleFontFamily,
    handleFontSize,
    handleTextColor,
    handleLineHeight,
    handleCut,
    handleCopy,
    handlePaste,
    handlePastePlain,
    handleInsertLink,
    handleInsertImage,
    handleInsertTable,
    handleFind,
    handleAi,
    handleContextMenu,
    handleDocumentClick,
    handleKeydown,
  }
}
