import { onMounted, onUnmounted } from 'vue'

/** 单条快捷键绑定 */
export interface HotkeyBinding {
  /** 组合键，形如 'ctrl+s' / 'ctrl+k' / 'escape' / 'arrowleft'；修饰键支持 ctrl/shift/alt/meta(cmd) */
  combo: string
  /** 命中时的回调（命中即 preventDefault，如 Ctrl+S 拦截浏览器保存弹窗） */
  handler: (e: KeyboardEvent) => void
  /** 焦点在输入控件（input/textarea/select/contenteditable）内时是否仍触发，默认 false（跳过） */
  allowInInput?: boolean
}

interface ParsedCombo {
  ctrl: boolean
  shift: boolean
  alt: boolean
  meta: boolean
  key: string
}

const parseCombo = (combo: string): ParsedCombo => {
  const parsed: ParsedCombo = { ctrl: false, shift: false, alt: false, meta: false, key: '' }
  for (const raw of combo.toLowerCase().split('+')) {
    const part = raw.trim()
    if (!part) continue
    if (part === 'ctrl' || part === 'control') parsed.ctrl = true
    else if (part === 'shift') parsed.shift = true
    else if (part === 'alt') parsed.alt = true
    else if (part === 'meta' || part === 'cmd') parsed.meta = true
    else parsed.key = part
  }
  return parsed
}

const matchesEvent = (parsed: ParsedCombo, e: KeyboardEvent): boolean =>
  parsed.key !== '' &&
  parsed.ctrl === e.ctrlKey &&
  parsed.shift === e.shiftKey &&
  parsed.alt === e.altKey &&
  parsed.meta === e.metaKey &&
  parsed.key === e.key.toLowerCase()

/** 焦点是否位于可输入控件（input/textarea/select/contenteditable） */
const isEditableTarget = (target: EventTarget | null): boolean => {
  if (!(target instanceof HTMLElement)) return false
  const tag = target.tagName
  return tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT' || target.isContentEditable
}

/**
 * 声明式快捷键绑定：在组件 onMounted/onUnmounted 时自动挂卸 window keydown 监听。
 * - 命中组合键时 preventDefault（如 ctrl+s 阻止浏览器保存弹窗）
 * - 焦点在输入控件内时默认跳过（allowInInput: true 的绑定除外）
 */
export function useHotkeys(bindings: HotkeyBinding[]): void {
  const parsedBindings = bindings.map((b) => ({ ...b, parsed: parseCombo(b.combo) }))

  const onKeyDown = (e: KeyboardEvent) => {
    for (const binding of parsedBindings) {
      if (!matchesEvent(binding.parsed, e)) continue
      if (!binding.allowInInput && isEditableTarget(e.target)) continue
      e.preventDefault()
      binding.handler(e)
      return
    }
  }

  onMounted(() => window.addEventListener('keydown', onKeyDown))
  onUnmounted(() => window.removeEventListener('keydown', onKeyDown))
}
