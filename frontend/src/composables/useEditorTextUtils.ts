/**
 * useEditorTextUtils：编辑器文本工具 composable
 *
 * 从 WordEditorPage 抽离：
 * - increaseFontSize / decreaseFontSize（基于 FONT_SIZE_OPTIONS）
 */
import type { Editor } from '@tiptap/core'
import { FONT_SIZE_OPTIONS } from '../components/editor/extensions/font-size'

export function useEditorTextUtils(getEditor: () => Editor | undefined) {
  /**
   * 增大字号：在 FONT_SIZE_OPTIONS（从大到小排列）中找到当前字号，
   * 取上一个（更大）的 value 调用 setFontSize。
   */
  const increaseFontSize = () => {
    const ed = getEditor()
    if (!ed) return
    const current = ed.getAttributes('textStyle').fontSize as string | null | undefined
    const idx = current
      ? FONT_SIZE_OPTIONS.findIndex((o) => o.value === current)
      : -1
    if (idx === -1) {
      // 当前字号不在预设中：取首个大于当前 px 的选项
      const currentPx = current ? parseFloat(current) : 14
      const next = FONT_SIZE_OPTIONS.find((o) => parseFloat(o.value) > currentPx)
      if (next) ed.chain().focus().setFontSize(next.value).run()
      return
    }
    if (idx > 0) {
      ed.chain().focus().setFontSize(FONT_SIZE_OPTIONS[idx - 1].value).run()
    }
  }

  /**
   * 减小字号：在 FONT_SIZE_OPTIONS 中取下一个（更小）的 value。
   */
  const decreaseFontSize = () => {
    const ed = getEditor()
    if (!ed) return
    const current = ed.getAttributes('textStyle').fontSize as string | null | undefined
    const idx = current
      ? FONT_SIZE_OPTIONS.findIndex((o) => o.value === current)
      : -1
    if (idx === -1) {
      const currentPx = current ? parseFloat(current) : 14
      for (let i = FONT_SIZE_OPTIONS.length - 1; i >= 0; i--) {
        if (parseFloat(FONT_SIZE_OPTIONS[i].value) < currentPx) {
          ed.chain().focus().setFontSize(FONT_SIZE_OPTIONS[i].value).run()
          return
        }
      }
      return
    }
    if (idx < FONT_SIZE_OPTIONS.length - 1) {
      ed.chain().focus().setFontSize(FONT_SIZE_OPTIONS[idx + 1].value).run()
    }
  }

  return {
    increaseFontSize,
    decreaseFontSize,
  }
}
