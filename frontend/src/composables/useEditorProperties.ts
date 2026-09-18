import { ref, computed, watch, onMounted, onBeforeUnmount } from 'vue'
import type { ChainedCommands, Editor } from '@tiptap/core'
import { FONT_FAMILY_OPTIONS } from '@/components/editor/extensions/font-family'
import { FONT_SIZE_OPTIONS } from '@/components/editor/extensions/font-size'
import { LINE_HEIGHT_OPTIONS } from '@/components/editor/extensions/line-height'
import { TEXT_COLOR_PRESETS } from '@/components/editor/extensions/text-color'

/**
 * useEditorProperties：WordEditorProperties 右侧属性面板的状态与操作模型
 * - 依赖注入 getEditor，组件仅持有数据源（editor prop）
 * - transaction bump 机制：Tiptap 事务触发 version 自增，强制派生 computed 重新求值
 * - 操作全部走 chain().focus().xxx().run()，与编辑器扩展一一对应
 * - 暗色模式监听：跟随 documentElement data-theme 变化
 */
export function useEditorProperties(getEditor: () => Editor | undefined) {
  /* 深色模式 */
  const isDark = ref(false)
  let darkObserver: MutationObserver | null = null
  const checkDarkMode = () => {
    isDark.value = document.documentElement.getAttribute('data-theme') === 'dark'
  }

  /* 事务版本号：强制 computed 重新求值 */
  const version = ref(0)
  const bump = () => { version.value++ }

  /* 编辑器状态 */
  const hasSelection = computed(() => {
    void version.value
    const ed = getEditor()
    if (!ed) return false
    return !ed.state.selection.empty
  })

  const isInParagraph = computed(() => {
    void version.value
    return getEditor()?.isActive('paragraph') ?? false
  })

  const isInTable = computed(() => {
    void version.value
    return getEditor()?.isActive('table') ?? false
  })

  const isInImage = computed(() => {
    void version.value
    return getEditor()?.isActive('image') ?? false
  })

  /* 段落属性 */
  const textAlign = computed(() => {
    void version.value
    const attrs = getEditor()?.getAttributes('paragraph')
    return (attrs?.textAlign as string) || 'left'
  })

  const lineHeight = computed(() => {
    void version.value
    const ed = getEditor()
    const attrs = ed?.isActive('heading')
      ? ed?.getAttributes('heading')
      : ed?.getAttributes('paragraph')
    return (attrs?.lineHeight as string) || '1.5'
  })

  const firstLineIndent = computed(() => {
    void version.value
    const ed = getEditor()
    const attrs = ed?.isActive('heading')
      ? ed?.getAttributes('heading')
      : ed?.getAttributes('paragraph')
    const indent = attrs?.textIndent as string | undefined
    if (indent && indent.endsWith('em')) {
      return parseFloat(indent)
    }
    return 0
  })

  const paragraphSpacing = ref({ before: 0, after: 0 })

  /* 字体属性 */
  const textStyleAttrs = computed(() => {
    void version.value
    return getEditor()?.getAttributes('textStyle') ?? {}
  })

  const fontFamily = computed(() => (textStyleAttrs.value.fontFamily as string) || undefined)
  const fontSize = computed(() => (textStyleAttrs.value.fontSize as string) || undefined)
  const textColor = computed(() => (textStyleAttrs.value.color as string) || undefined)

  const isBold = computed(() => { void version.value; return getEditor()?.isActive('bold') ?? false })
  const isItalic = computed(() => { void version.value; return getEditor()?.isActive('italic') ?? false })
  const isUnderline = computed(() => { void version.value; return getEditor()?.isActive('underline') ?? false })
  const isStrike = computed(() => { void version.value; return getEditor()?.isActive('strike') ?? false })

  /* 表格属性 */
  const tableCellAlign = computed(() => {
    void version.value
    const attrs = getEditor()?.getAttributes('tableCell')
    return (attrs?.textAlign as string) || 'left'
  })

  /* 图片属性 */
  const imageAttrs = computed(() => {
    void version.value
    return getEditor()?.getAttributes('image') ?? {}
  })

  const imageWidth = computed(() => Number(imageAttrs.value.width) || 300)
  const imageHeight = computed(() => Number(imageAttrs.value.height) || 200)
  const imageAlign = computed(() => (imageAttrs.value.align as string) || 'left')

  /* 选项 */
  const fontFamilyOptions = FONT_FAMILY_OPTIONS.map((o) => ({ label: o.label, value: o.value }))
  const fontSizeOptions = FONT_SIZE_OPTIONS.map((o) => ({ label: `${o.label} · ${o.value}`, value: o.value }))
  const lineHeightOptions = LINE_HEIGHT_OPTIONS.map((v) => ({ label: `行高 ${v}`, value: String(v) }))
  const indentOptions = [
    { label: '无', value: '0' },
    { label: '2字符', value: '2' },
    { label: '4字符', value: '4' },
    { label: '6字符', value: '6' },
  ]

  const tableCellAligns = [
    { value: 'left', label: '左上', icon: '↖' },
    { value: 'center', label: '中上', icon: '↑' },
    { value: 'right', label: '右上', icon: '↗' },
  ]

  const BORDER_COLOR_PRESETS = ['#000000', '#333333', '#666666', '#999999', '#cccccc', '#1890ff', '#52c41a', '#faad14', '#f5222d']
  const BG_COLOR_PRESETS = ['#ffffff', '#f5f5f5', '#e6f7ff', '#f6ffed', '#fff7e6', '#fff1f0', '#f9f0ff', '#e6fffb']

  /* 操作方法 */
  const run = (fn: (chain: ChainedCommands) => ChainedCommands) => {
    const ed = getEditor()
    if (!ed) return
    fn(ed.chain().focus()).run()
  }

  const setTextAlign = (align: string) => run((c: ChainedCommands) => c.setTextAlign(align))
  // Select/InputNumber 的 change 事件参数类型为 antd SelectValue/ValueType（含数组/对象），
  // 此处按 unknown 接收后显式转换，保持函数签名与模板绑定兼容
  const setLineHeight = (val: unknown) => run((c: ChainedCommands) => c.setLineHeight(String(val)))
  const setFirstLineIndent = (val: unknown) => run((c: ChainedCommands) => c.setIndent(Number(String(val))))
  const setParagraphSpacing = (_type: string, _val: unknown) => {
    // Tiptap 默认不支持段前段后，需自定义扩展；此处预留
  }

  const setFontFamily = (val: unknown) => run((c: ChainedCommands) => c.setFontFamily(String(val)))
  const setFontSize = (val: unknown) => run((c: ChainedCommands) => c.setFontSize(String(val)))
  const setTextColor = (color: string) => run((c: ChainedCommands) => c.setColor(color))
  const toggleBold = () => run((c: ChainedCommands) => c.toggleBold())
  const toggleItalic = () => run((c: ChainedCommands) => c.toggleItalic())
  const toggleUnderline = () => run((c: ChainedCommands) => c.toggleUnderline())
  const toggleStrike = () => run((c: ChainedCommands) => c.toggleStrike())

  const setTableCellAlign = (align: string) => {
    const ed = getEditor()
    if (!ed) return
    ed.chain().focus().updateAttributes('tableCell', { textAlign: align }).run()
  }

  const setTableBorderColor = (_color: string) => {
    // 需自定义表格扩展支持边框颜色；预留
  }

  const setTableBgColor = (color: string) => {
    const ed = getEditor()
    if (!ed) return
    ed.chain().focus().updateAttributes('tableCell', { backgroundColor: color || null }).run()
  }

  const setImageWidth = (val: number | string | null) => {
    if (val == null) return
    const ed = getEditor()
    if (!ed) return
    ed.chain().focus().updateAttributes('image', { width: Number(val) }).run()
  }

  const setImageHeight = (val: number | string | null) => {
    if (val == null) return
    const ed = getEditor()
    if (!ed) return
    ed.chain().focus().updateAttributes('image', { height: Number(val) }).run()
  }

  const setImageAlign = (align: string) => {
    const ed = getEditor()
    if (!ed) return
    ed.chain().focus().updateAttributes('image', { align }).run()
  }

  /* 生命周期：transaction bump + 暗色监听 */
  let transactionHandler: (() => void) | null = null

  onMounted(() => {
    checkDarkMode()
    darkObserver = new MutationObserver(checkDarkMode)
    darkObserver.observe(document.documentElement, { attributes: true, attributeFilter: ['data-theme'] })

    const ed = getEditor()
    if (ed) {
      transactionHandler = bump
      ed.on('transaction', transactionHandler)
    }
  })

  watch(getEditor, (ed, oldEd) => {
    if (oldEd && transactionHandler) oldEd.off('transaction', transactionHandler)
    if (ed) {
      transactionHandler = bump
      ed.on('transaction', transactionHandler)
    }
  })

  onBeforeUnmount(() => {
    darkObserver?.disconnect()
    const ed = getEditor()
    if (ed && transactionHandler) {
      ed.off('transaction', transactionHandler)
    }
  })

  return {
    isDark,
    bump,
    hasSelection,
    isInParagraph,
    isInTable,
    isInImage,
    textAlign,
    lineHeight,
    firstLineIndent,
    paragraphSpacing,
    textStyleAttrs,
    fontFamily,
    fontSize,
    textColor,
    isBold,
    isItalic,
    isUnderline,
    isStrike,
    tableCellAlign,
    imageAttrs,
    imageWidth,
    imageHeight,
    imageAlign,
    fontFamilyOptions,
    fontSizeOptions,
    lineHeightOptions,
    indentOptions,
    tableCellAligns,
    TEXT_COLOR_PRESETS,
    BORDER_COLOR_PRESETS,
    BG_COLOR_PRESETS,
    run,
    setTextAlign,
    setLineHeight,
    setFirstLineIndent,
    setParagraphSpacing,
    setFontFamily,
    setFontSize,
    setTextColor,
    toggleBold,
    toggleItalic,
    toggleUnderline,
    toggleStrike,
    setTableCellAlign,
    setTableBorderColor,
    setTableBgColor,
    setImageWidth,
    setImageHeight,
    setImageAlign,
  }
}
