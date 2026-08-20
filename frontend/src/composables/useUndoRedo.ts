import { computed, ref, toRaw } from 'vue'
import type { ComputedRef, Ref } from 'vue'

/**
 * 递归解包 Vue 响应式 Proxy（reactive/ref 包装的数组与嵌套对象），
 * 还原为可被 structuredClone 序列化的普通数据。
 * - 数组：逐项递归；普通对象：逐键递归
 * - Date/RegExp/Map/Set 等内置实例原样返回（structuredClone 可直接处理）
 * - 原始值直接返回（toRaw 对非 Proxy 是幂等的）
 */
const deepRaw = <T>(value: T): T => {
  const raw = toRaw(value) as T
  if (Array.isArray(raw)) {
    return raw.map((item) => deepRaw(item)) as unknown as T
  }
  if (raw !== null && typeof raw === 'object') {
    if (raw instanceof Date || raw instanceof RegExp || raw instanceof Map || raw instanceof Set) {
      return raw
    }
    const result: Record<string, unknown> = {}
    for (const key of Object.keys(raw as Record<string, unknown>)) {
      result[key] = deepRaw((raw as Record<string, unknown>)[key])
    }
    return result as T
  }
  return raw
}

/**
 * 深克隆快照：先递归解包响应式 Proxy 再 structuredClone；
 * 克隆失败（或无 structuredClone 的旧环境）降级 JSON 往返（业务快照均为可序列化数据）。
 */
const cloneSnapshot = <T>(value: T): T => {
  const plain = deepRaw(value)
  try {
    if (typeof structuredClone === 'function') return structuredClone(plain)
  } catch {
    // structuredClone 无法处理时降级 JSON 往返
  }
  return JSON.parse(JSON.stringify(plain)) as T
}

export interface UseUndoRedoOptions {
  /** 单方向保留的快照上限，超出丢弃最旧快照，默认 50 */
  limit?: number
}

export interface UseUndoRedoReturn<T> {
  /** 当前状态（接入方以此为唯一数据源） */
  state: Ref<T>
  /** 操作前推入快照；会清空重做栈 */
  push: (snapshot: T) => void
  /** 撤销一步，无可撤销时返回 false */
  undo: () => boolean
  /** 重做一步，无可重做时返回 false */
  redo: () => boolean
  /** 以外部最新值重置状态并清空双向历史（后端数据刷新后用） */
  reset: (value: T) => void
  canUndo: ComputedRef<boolean>
  canRedo: ComputedRef<boolean>
}

/**
 * 泛型快照栈撤销/重做。
 * - push/undo/redo/reset 内部均深克隆（含响应式 Proxy 解包），快照与活动状态互不共享引用，
 *   接入方对 state 做原地变更（如树节点 splice）也不会污染历史快照。
 */
export function useUndoRedo<T>(initial: T, options: UseUndoRedoOptions = {}): UseUndoRedoReturn<T> {
  const limit = options.limit ?? 50
  const state = ref(initial) as Ref<T>
  const past = ref<T[]>([]) as Ref<T[]>
  const future = ref<T[]>([]) as Ref<T[]>

  const push = (snapshot: T) => {
    past.value.push(cloneSnapshot(snapshot))
    if (past.value.length > limit) past.value.shift()
    future.value = []
  }

  const undo = (): boolean => {
    if (past.value.length === 0) return false
    const snapshot = past.value.pop() as T
    future.value.push(cloneSnapshot(state.value))
    state.value = snapshot
    return true
  }

  const redo = (): boolean => {
    if (future.value.length === 0) return false
    const snapshot = future.value.pop() as T
    past.value.push(cloneSnapshot(state.value))
    state.value = snapshot
    return true
  }

  const reset = (value: T) => {
    state.value = cloneSnapshot(value)
    past.value = []
    future.value = []
  }

  return {
    state,
    push,
    undo,
    redo,
    reset,
    canUndo: computed(() => past.value.length > 0),
    canRedo: computed(() => future.value.length > 0),
  }
}
