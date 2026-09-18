/**
 * useEditorHotkeys：WordEditorPage 快捷键注册表（从页面组件抽离）。
 *
 * 页面只保留「快捷键 → 动作」的声明式映射，具体键位语义集中于此：
 * - Ctrl+S 保存、Ctrl+F/H 查找替换、Ctrl+L/E/R/J 对齐、Ctrl+1/2/3 行高
 * - Ctrl+Shift+>/< 增减字号、Ctrl+Shift+C/V 格式刷、Alt+Shift+←/→ 标题级别
 * - Ctrl+Enter 分页符、Escape 关闭面板/取消格式刷
 *
 * 依赖注入（避免 composable 反向依赖页面内部 ref）：
 * - getEditor：获取 Tiptap Editor 实例（可能为 undefined）
 * - saveNow：Ctrl+S 保存动作
 * - getSearch：返回 { mode, visible } 两个 Ref（Ctrl+F/H 打开查找替换面板）
 * - increaseFontSize / decreaseFontSize：字号增减动作
 * - getFormatBrush：返回格式刷对象（Ctrl+Shift+C/V、Escape 取消）
 */
import type { Ref } from 'vue'
import type { Editor } from '@tiptap/core'
import { useHotkeys, type HotkeyBinding } from './useHotkeys'

export interface UseEditorHotkeysOptions {
  /** 获取当前编辑器实例 */
  getEditor: () => Editor | undefined
  /** Ctrl+S 保存 */
  saveNow: () => void | Promise<void>
  /** 查找替换面板状态（Ctrl+F/H 打开并切模式） */
  getSearch: () => { mode: Ref<'find' | 'replace'>; visible: Ref<boolean> }
  /** Ctrl+Shift+> 增大字号 */
  increaseFontSize: () => void
  /** Ctrl+Shift+< 减小字号 */
  decreaseFontSize: () => void
  /** 格式刷对象（Ctrl+Shift+C/V 复制/应用，Escape 取消） */
  getFormatBrush: () => {
    copyFormat: (mode?: 'single' | 'continuous') => void
    applyFormat: () => void
    cancelBrush: () => void
    brushActive: Ref<boolean>
  }
}

/** 标题级别：Alt+Shift+← 降低级别（level 数值 +1，H4 再按回退段落） */
const decreaseHeadingLevel = (ed: Editor): void => {
  if (ed.isActive('heading', { level: 4 })) {
    ed.chain().focus().setParagraph().run()
  } else if (ed.isActive('heading')) {
    const lvl = ed.getAttributes('heading').level as number
    ed.chain().focus().setHeading({ level: (lvl + 1) as 1 | 2 | 3 | 4 }).run()
  } else {
    ed.chain().focus().setHeading({ level: 1 }).run()
  }
}

/** 标题级别：Alt+Shift+→ 提升级别（level 数值 -1，H1 再按回退段落） */
const increaseHeadingLevel = (ed: Editor): void => {
  if (ed.isActive('heading', { level: 1 })) {
    ed.chain().focus().setParagraph().run()
  } else if (ed.isActive('heading')) {
    const lvl = ed.getAttributes('heading').level as number
    if (lvl > 1) {
      ed.chain().focus().setHeading({ level: (lvl - 1) as 1 | 2 | 3 | 4 }).run()
    }
  } else {
    ed.chain().focus().setHeading({ level: 4 }).run()
  }
}

export function useEditorHotkeys(options: UseEditorHotkeysOptions): void {
  const { getEditor, saveNow, getSearch, increaseFontSize, decreaseFontSize, getFormatBrush } = options

  // setup 阶段快照一次 Ref/函数，运行时读取 .value 保持响应式
  const { mode: searchMode, visible: searchVisible } = getSearch()
  const { copyFormat, applyFormat, cancelBrush, brushActive } = getFormatBrush()

  const bindings: HotkeyBinding[] = [
    // 保存
    { combo: 'ctrl+s', allowInInput: true, handler: () => void saveNow() },
    // 查找 / 替换
    {
      combo: 'ctrl+f',
      allowInInput: true,
      handler: () => {
        searchMode.value = 'find'
        searchVisible.value = true
      },
    },
    {
      combo: 'ctrl+h',
      allowInInput: true,
      handler: () => {
        searchMode.value = 'replace'
        searchVisible.value = true
      },
    },
    // 对齐
    {
      combo: 'ctrl+l',
      allowInInput: true,
      handler: () => getEditor()?.chain().focus().setTextAlign('left').run(),
    },
    {
      combo: 'ctrl+e',
      allowInInput: true,
      handler: () => getEditor()?.chain().focus().setTextAlign('center').run(),
    },
    {
      combo: 'ctrl+r',
      allowInInput: true,
      handler: () => getEditor()?.chain().focus().setTextAlign('right').run(),
    },
    {
      combo: 'ctrl+j',
      allowInInput: true,
      handler: () => getEditor()?.chain().focus().setTextAlign('justify').run(),
    },
    // 行高
    {
      combo: 'ctrl+1',
      allowInInput: true,
      handler: () => getEditor()?.chain().focus().setLineHeight('1').run(),
    },
    {
      combo: 'ctrl+2',
      allowInInput: true,
      handler: () => getEditor()?.chain().focus().setLineHeight('1.5').run(),
    },
    {
      combo: 'ctrl+3',
      allowInInput: true,
      handler: () => getEditor()?.chain().focus().setLineHeight('2').run(),
    },
    // 字号增减（Shift+. → '>'，Shift+, → '<'）
    {
      combo: 'ctrl+shift+>',
      allowInInput: true,
      handler: increaseFontSize,
    },
    {
      combo: 'ctrl+shift+<',
      allowInInput: true,
      handler: decreaseFontSize,
    },
    // 格式刷
    {
      combo: 'ctrl+shift+c',
      allowInInput: true,
      handler: () => copyFormat('continuous'),
    },
    {
      combo: 'ctrl+shift+v',
      allowInInput: true,
      handler: () => applyFormat(),
    },
    // 标题级别：Alt+Shift+← 降低（增大 level 数值），Alt+Shift+→ 提升
    {
      combo: 'alt+shift+arrowleft',
      allowInInput: true,
      handler: () => {
        const ed = getEditor()
        if (ed) decreaseHeadingLevel(ed)
      },
    },
    {
      combo: 'alt+shift+arrowright',
      allowInInput: true,
      handler: () => {
        const ed = getEditor()
        if (ed) increaseHeadingLevel(ed)
      },
    },
    // 分页符（Tiptap page-break 扩展已处理 Mod-Enter，此处仅在编辑器外触发）
    {
      combo: 'ctrl+enter',
      allowInInput: true,
      handler: (e: KeyboardEvent) => {
        // 当事件源自 contenteditable 编辑区时，Tiptap 已处理 Mod-Enter，
        // 跳过以避免重复插入分页符（结构化判断，避免依赖 HTMLElement 全局）
        const target = e.target as { isContentEditable?: boolean } | null
        if (target && target.isContentEditable) return
        getEditor()?.chain().focus().setPageBreak().run()
      },
    },
    // Escape：依次关闭搜索面板 / 取消格式刷
    {
      combo: 'escape',
      allowInInput: true,
      handler: () => {
        if (searchVisible.value) {
          searchVisible.value = false
        } else if (brushActive.value) {
          cancelBrush()
        }
      },
    },
  ]

  useHotkeys(bindings)
}
