/**
 * localStorage 类型安全封装：带 JSON 序列化、默认值与过期时间
 */

/** 写入（JSON 序列化） */
export const setStorage = <T>(key: string, value: T): void => {
  try {
    localStorage.setItem(key, JSON.stringify(value))
  } catch {
    // 隐私模式 / 配额超限时静默失败
  }
}

/** 读取（JSON 反序列化，无值或解析失败返回默认值） */
export const getStorage = <T>(key: string, defaultValue: T): T => {
  try {
    const raw = localStorage.getItem(key)
    if (raw === null) return defaultValue
    return JSON.parse(raw) as T
  } catch {
    return defaultValue
  }
}

/** 带过期时间的写入：expireMs 毫秒后读取返回默认值 */
export const setStorageWithExpiry = <T>(key: string, value: T, expireMs: number): void => {
  try {
    localStorage.setItem(
      key,
      JSON.stringify({ value, expiresAt: Date.now() + expireMs }),
    )
  } catch {
    // 静默失败
  }
}

/** 带过期时间的读取 */
export const getStorageWithExpiry = <T>(key: string, defaultValue: T): T => {
  try {
    const raw = localStorage.getItem(key)
    if (raw === null) return defaultValue
    const parsed = JSON.parse(raw) as { value: T; expiresAt: number }
    if (Date.now() > parsed.expiresAt) {
      localStorage.removeItem(key)
      return defaultValue
    }
    return parsed.value
  } catch {
    return defaultValue
  }
}

/** 删除 */
export const removeStorage = (key: string): void => {
  try {
    localStorage.removeItem(key)
  } catch {
    // 静默失败
  }
}
