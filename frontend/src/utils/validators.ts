/**
 * 常用校验器：邮箱 / 手机号 / URL / 非空字符串
 */

/** 邮箱校验 */
export const isEmail = (value: string): boolean =>
  /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(value)

/** 中国大陆手机号校验（11 位，1 开头） */
export const isPhone = (value: string): boolean => /^1[3-9]\d{9}$/.test(value)

/** URL 校验（http/https） */
export const isUrl = (value: string): boolean => {
  try {
    const url = new URL(value)
    return url.protocol === 'http:' || url.protocol === 'https:'
  } catch {
    return false
  }
}

/** 非空字符串（去空白后非空） */
export const isNonEmpty = (value: string): boolean => value.trim().length > 0

/** 字符串长度范围校验 */
export const isLengthInRange = (value: string, min: number, max: number): boolean => {
  const len = value.trim().length
  return len >= min && len <= max
}

/** 正整数校验 */
export const isPositiveInteger = (value: string): boolean =>
  /^[1-9]\d*$/.test(value.trim())
