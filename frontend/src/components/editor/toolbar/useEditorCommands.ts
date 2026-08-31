/**
 * useEditorCommands：编辑器命令与状态查询 composable
 *
 * 从 WordEditorToolbar 抽离，供各 Ribbon 选项卡子组件复用：
 * - 事务版本号同步（version/bump）
 * - 命令执行（run）
 * - 激活态判断（isActive/canUndo/canRedo）
 * - 段落/字体/颜色/格式刷等常用操作
 */
import { computed, ref, watch, inject, onBeforeUnmount } from 'vue'
import type { Editor, ChainedCommands } from '@tiptap/core'
import { FONT_FAMILY_OPTIONS } from '../extensions/font-family'
import { FONT_SIZE_OPTIONS } from '../extensions/font-size'
import { LINE_HEIGHT_OPTIONS } from '../extensions/line-height'
import type { UseFormatBrushReturn } from '@/composables/useFormatBrush'

export function useEditorCommands(editor: () => Editor | undefined) {
  /* ---------------- 事务版本号同步 ---------------- */
  const version = ref(0)
  const bump = () => { version.value++ }

  watch(
    editor,
    (ed, _old, onCleanup) => {
      if (!ed) return
      ed.on('transaction', bump)
      onCleanup(() => ed.off('transaction', bump))
    },
    { immediate: true },
  )

  /* ---------------- 命令执行 ---------------- */
  const run = (apply: (chain: ChainedCommands) => ChainedCommands) => {
    const ed = editor()
    if (!ed) return
    apply(ed.chain().focus()).run()
  }

  const isActive = (nameOrAttrs: string | Record<string, unknown>): boolean => {
    void version.value
    const ed = editor()
    if (!ed) return false
    return typeof nameOrAttrs === 'string'
      ? ed.isActive(nameOrAttrs)
      : ed.isActive(nameOrAttrs)
  }

  const canUndo = computed(() => {
    void version.value
    return editor()?.can().undo() ?? false
  })
  const canRedo = computed(() => {
    void version.value
    return editor()?.can().redo() ?? false
  })

  /* ---------------- 段落格式 ---------------- */
  const paragraphOptions = [
    { label: '正文', value: 'paragraph' },
    { label: '标题 1', value: 'heading-1' },
    { label: '标题 2', value: 'heading-2' },
    { label: '标题 3', value: 'heading-3' },
    { label: '标题 4', value: 'heading-4' },
  ]

  const paragraphValue = computed(() => {
    void version.value
    const ed = editor()
    if (!ed) return 'paragraph'
    for (const level of [1, 2, 3, 4]) {
      if (ed.isActive('heading', { level })) return `heading-${level}`
    }
    return 'paragraph'
  })

  const handleParagraphChange = (value: unknown) => {
    if (value === 'paragraph') {
      run((chain) => chain.setParagraph())
    } else {
      const level = Number(String(value).split('-')[1]) as 1 | 2 | 3 | 4
      run((chain) => chain.setHeading({ level }))
    }
  }

  /* ---------------- 字体 / 字号 / 行高 ---------------- */
  const fontFamilyOptions = FONT_FAMILY_OPTIONS.map((o) => ({ label: o.label, value: o.value }))
  const fontSizeOptions = FONT_SIZE_OPTIONS.map((o) => ({ label: `${o.label} · ${o.value}`, value: o.value }))
  const lineHeightOptions = LINE_HEIGHT_OPTIONS.map((v) => ({ label: `行高 ${v}`, value: String(v) }))

  const textStyleAttrs = computed<Record<string, unknown>>(() => {
    void version.value
    return editor()?.getAttributes('textStyle') ?? {}
  })

  const currentFontFamily = computed(() => (textStyleAttrs.value.fontFamily as string) ?? undefined)
  const currentFontSize = computed(() => (textStyleAttrs.value.fontSize as string) ?? undefined)

  const currentLineHeight = computed(() => {
    void version.value
    const ed = editor()
    if (!ed) return undefined
    const attrs = ed.isActive('heading')
      ? ed.getAttributes('heading')
      : ed.getAttributes('paragraph')
    return (attrs.lineHeight as string | undefined) ?? undefined
  })

  const handleFontFamilyChange = (value: unknown) => {
    run((chain) => chain.setFontFamily(String(value)))
  }
  const handleFontSizeChange = (value: unknown) => {
    run((chain) => chain.setFontSize(String(value)))
  }
  const handleLineHeightChange = (value: unknown) => {
    run((chain) => chain.setLineHeight(String(value)))
  }

  /* ---------------- 颜色 / 高亮 ---------------- */
  const handleTextColor = (color: string) => {
    run((chain) => chain.setColor(color))
  }
  const handleHighlight = (color: string) => {
    run((chain) => chain.setHighlight({ color }))
  }

  /* ---------------- 清除格式 ---------------- */
  const handleClearFormat = () => {
    run((chain) => chain.clearNodes().unsetAllMarks())
  }

  /* ---------------- 格式刷 ---------------- */
  const formatBrush = inject<UseFormatBrushReturn | null>('formatBrush', null)
  const brushActive = formatBrush?.brushActive ?? ref(false)
  const copyFormat = formatBrush?.copyFormat ?? (() => {})

  let brushClickTimer: ReturnType<typeof setTimeout> | null = null

  const handleBrushClick = () => {
    brushClickTimer = setTimeout(() => {
      copyFormat('single')
      brushClickTimer = null
    }, 220)
  }

  const handleBrushDblClick = () => {
    if (brushClickTimer) {
      clearTimeout(brushClickTimer)
      brushClickTimer = null
    }
    copyFormat('continuous')
  }

  onBeforeUnmount(() => {
    if (brushClickTimer) clearTimeout(brushClickTimer)
  })

  return {
    version,
    run,
    isActive,
    canUndo,
    canRedo,
    paragraphOptions,
    paragraphValue,
    handleParagraphChange,
    fontFamilyOptions,
    fontSizeOptions,
    lineHeightOptions,
    currentFontFamily,
    currentFontSize,
    currentLineHeight,
    handleFontFamilyChange,
    handleFontSizeChange,
    handleLineHeightChange,
    handleTextColor,
    handleHighlight,
    handleClearFormat,
    brushActive,
    handleBrushClick,
    handleBrushDblClick,
  }
}
