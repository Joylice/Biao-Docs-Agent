/**
 * useFormatBrush：格式刷能力封装（纯函数 composable）。
 *
 * - copyFormat(mode)：采集当前选区的 marks（粗体/斜体/下划线/删除线/
 *   字体/字号/文字色/高亮）与段落属性（对齐/行高/首行缩进），存入内部状态，
 *   并激活刷子（mode: 'single' 单次 | 'continuous' 连续）。
 * - applyFormat()：将存储的 marks/属性逐一应用到当前选区；
 *   single 模式应用后自动取消，continuous 模式保持激活。
 * - cancelBrush()：退出刷子模式并清空存储。
 *
 * 复制范围：bold/italic/underline/strike/fontFamily/fontSize/color/highlight/
 * textAlign/lineHeight/textIndent。组件层根据 brushActive 设置 cursor: copy。
 */
import { ref, type Ref, type ShallowRef } from 'vue'
import type { Editor } from '@tiptap/core'

/** 存储的 mark（类型名 + 属性） */
interface StoredMark {
  type: string
  attrs: Record<string, unknown>
}

/** 存储的段落属性 */
interface StoredBlockAttrs {
  textAlign?: string
  lineHeight?: string
  textIndent?: string
}

/** 复制到的完整格式快照 */
interface StoredFormat {
  marks: StoredMark[]
  attrs: StoredBlockAttrs
}

/** 刷子模式 */
export type BrushMode = 'single' | 'continuous' | 'off'

export interface UseFormatBrushReturn {
  /** 是否激活刷子（组件据此切换光标为 copy） */
  brushActive: Ref<boolean>
  /** 当前刷子模式 */
  brushMode: Ref<BrushMode>
  /** 复制当前选区格式并激活刷子 */
  copyFormat: (mode?: BrushMode) => void
  /** 将存储的格式应用到当前选区 */
  applyFormat: () => void
  /** 取消刷子模式 */
  cancelBrush: () => void
}

/**
 * 格式刷 composable。
 * @param editor 编辑器实例引用（可能为 undefined）
 */
export function useFormatBrush(editor: ShallowRef<Editor | undefined> | Ref<Editor | undefined>): UseFormatBrushReturn {
  const brushActive = ref(false)
  const brushMode = ref<BrushMode>('off')
  // 非响应式存储：仅内部使用，无需触发渲染
  let stored: StoredFormat | null = null

  const copyFormat = (mode: BrushMode = 'single'): void => {
    const inst = editor.value
    if (!inst) return
    // 采集选区起点的活动 marks（含 textStyle 的字体/字号/文字色、highlight）
    const marks: StoredMark[] = inst.state.selection.$from
      .marks()
      .map((m) => ({ type: m.type.name, attrs: { ...m.attrs } }))
    // 采集光标所在段落/标题的块级属性
    const parentAttrs = inst.state.selection.$from.parent.attrs ?? {}
    const attrs: StoredBlockAttrs = {}
    if (parentAttrs.textAlign) attrs.textAlign = String(parentAttrs.textAlign)
    if (parentAttrs.lineHeight) attrs.lineHeight = String(parentAttrs.lineHeight)
    if (parentAttrs.textIndent) attrs.textIndent = String(parentAttrs.textIndent)

    stored = { marks, attrs }
    brushMode.value = mode
    brushActive.value = true
  }

  const applyFormat = (): void => {
    const inst = editor.value
    if (!stored || !inst) return
    let chain = inst.chain().focus()
    // 逐一应用存储的 marks
    for (const mark of stored.marks) {
      chain = chain.setMark(mark.type, mark.attrs)
    }
    // 应用段落属性
    if (stored.attrs.textAlign) {
      chain = chain.setTextAlign(stored.attrs.textAlign)
    }
    if (stored.attrs.lineHeight) {
      chain = chain.setLineHeight(stored.attrs.lineHeight)
    }
    if (stored.attrs.textIndent) {
      // textIndent 挂在 paragraph/heading 节点（同 Indent 扩展）
      chain = chain
        .updateAttributes('paragraph', { textIndent: stored.attrs.textIndent })
        .updateAttributes('heading', { textIndent: stored.attrs.textIndent })
    }
    chain.run()
    // single 模式：应用后自动取消；continuous 模式保持激活
    if (brushMode.value === 'single') {
      cancelBrush()
    }
  }

  const cancelBrush = (): void => {
    stored = null
    brushActive.value = false
    brushMode.value = 'off'
  }

  return { brushActive, brushMode, copyFormat, applyFormat, cancelBrush }
}
