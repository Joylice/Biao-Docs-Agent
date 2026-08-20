/** 防抖函数返回类型：可调用、可撤销待执行 */
export interface DebouncedFn<A extends unknown[]> {
  (...args: A): void
  /** 撤销尚未执行的延迟调用 */
  cancel: () => void
}

/**
 * 防抖：最后一次调用后停顿 wait 毫秒才真正执行，期间重复调用重新计时。
 * @param fn 目标函数
 * @param wait 防抖间隔（毫秒），默认 300
 */
export function debounce<A extends unknown[]>(
  fn: (...args: A) => void,
  wait = 300,
): DebouncedFn<A> {
  let timer: ReturnType<typeof setTimeout> | undefined
  const debounced = ((...args: A) => {
    if (timer !== undefined) clearTimeout(timer)
    timer = setTimeout(() => {
      timer = undefined
      fn(...args)
    }, wait)
  }) as DebouncedFn<A>
  debounced.cancel = () => {
    if (timer !== undefined) {
      clearTimeout(timer)
      timer = undefined
    }
  }
  return debounced
}
