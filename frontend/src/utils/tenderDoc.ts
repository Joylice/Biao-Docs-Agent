/**
 * 招标文件（tender_file）展示层纯函数：状态映射、超时判定、主文档选取、时间格式化.
 *
 * 抽出原因：招标解析页在「评分点 tab 上方（收起态一行摘要）」与「展开态文件列表」
 * 两处展示同一套状态，口径只能有一份（分量表会漂移）。项目未引入 @vue/test-utils，
 * 故这些分支逻辑外置为纯函数并在 __tests__ 锁定行为。
 *
 * 入参口径宽松：a-table record 由 antd 以 Record<string, any> 注入，故状态/时间字段
 * 声明为 unknown，判定全部走值比较，不做结构解构。
 */

/** 解析超时阈值（毫秒）：uploaded/parsing 超过 15 分钟视为超时，允许重新解析 */
export const TENDER_PARSE_TIMEOUT_MS = 15 * 60 * 1000

/** 招标文件最小结构（接口返回） */
export interface TenderDoc {
  id: string
  title: string
  status: string
  created_at: string
}

/** 宽松入参（兼容接口返回与 a-table record） */
export interface TenderDocLike {
  status?: unknown
  created_at?: unknown
}

const STATUS_COLORS: Record<string, string> = {
  uploaded: 'default',
  parsing: 'processing',
  parsed: 'blue',
  indexed: 'success',
  failed: 'error',
}

const STATUS_TEXTS: Record<string, string> = {
  uploaded: '已上传',
  parsing: '解析中',
  parsed: '已解析',
  indexed: '已完成',
  failed: '失败',
}

/** 是否处于解析进行中（未出结果）状态 */
export const isTenderParsing = (doc: TenderDocLike): boolean =>
  doc.status === 'uploaded' || doc.status === 'parsing'

/** 解析是否已超时（仅对进行中状态有意义；created_at 非法时不判超时） */
export const isTenderStale = (doc: TenderDocLike, now: number = Date.now()): boolean => {
  if (!isTenderParsing(doc)) return false
  const created = new Date(String(doc.created_at ?? '')).getTime()
  if (Number.isNaN(created)) return false
  return now - created > TENDER_PARSE_TIMEOUT_MS
}

/** 能否重新解析：已解析 / 失败 / 进行中但已超时 */
export const canReparseTender = (doc: TenderDocLike, now: number = Date.now()): boolean =>
  doc.status === 'parsed' || doc.status === 'failed' || isTenderStale(doc, now)

/** 状态标签颜色（未知状态回落 default） */
export const tenderStatusColor = (status?: string | null): string =>
  STATUS_COLORS[status ?? ''] ?? 'default'

/** 状态中文文案（未知状态原样返回） */
export const tenderStatusText = (status?: string | null): string =>
  STATUS_TEXTS[status ?? ''] ?? (status ?? '')

/** 上传时间格式化：YYYY-MM-DD HH:mm；空值返回 —，非法值原样返回 */
export const formatTenderTime = (time?: string | null): string => {
  if (!time) return '—'
  const d = new Date(time)
  if (Number.isNaN(d.getTime())) return time
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`
}

/** 进行中的文档（不含超时：超时的由用户手动重新解析，不再轮询） */
export const pendingTenderDocs = <T extends TenderDocLike>(
  docs: T[],
  now: number = Date.now(),
): T[] => docs.filter((d) => isTenderParsing(d) && !isTenderStale(d, now))

/**
 * 主招标文件：列表首条.
 *
 * 后端 documents 列表按 created_at DESC 返回（document_service.py:124），
 * 故首条即最近上传的招标文件；收起态一行摘要展示它。
 */
export const pickPrimaryTender = <T>(docs: T[]): T | null => docs[0] ?? null
