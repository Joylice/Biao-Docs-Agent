/**
 * 分页符扩展：自定义块级原子节点 pageBreak。
 * - 渲染为 <div class="page-break" data-page-break="true"></div>，
 *   视觉（虚线 + "分页符" 文字）由 WordEditor.vue 的 :deep 样式承担；
 *   打印时 page-break-after: always 生效，实现真实分页。
 * - 命令 setPageBreak：在当前选区插入一个分页符节点。
 */
import { Node, mergeAttributes } from '@tiptap/core'

/* 命令类型扩展：保证 chain().setPageBreak() 在 TS 严格模式下可推导 */
declare module '@tiptap/core' {
  interface Commands<ReturnType> {
    pageBreak: {
      /** 在当前光标位置插入分页符 */
      setPageBreak: () => ReturnType
    }
  }
}

export const PageBreak = Node.create({
  name: 'pageBreak',
  group: 'block',
  atom: true,
  selectable: true,
  draggable: true,

  parseHTML() {
    return [{ tag: 'div[data-page-break]' }]
  },

  renderHTML({ HTMLAttributes }) {
    return [
      'div',
      mergeAttributes(HTMLAttributes, { class: 'page-break', 'data-page-break': 'true' }),
    ]
  },

  addCommands() {
    return {
      setPageBreak:
        () =>
        ({ commands }) =>
          commands.insertContent({ type: 'pageBreak' }),
    }
  },

  addKeyboardShortcuts() {
    return {
      'Mod-Enter': () => this.editor.commands.setPageBreak(),
    }
  },
})
