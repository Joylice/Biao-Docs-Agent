/**
 * tenderDoc 纯函数测试（招标文件状态口径）.
 *
 * 锁定招标解析页「收起态一行摘要」与「展开态文件列表」共用的判定逻辑，
 * 防止两处展示漂移。
 */
import { describe, expect, it } from 'vitest'

import {
  TENDER_PARSE_TIMEOUT_MS,
  canReparseTender,
  formatTenderTime,
  isTenderParsing,
  isTenderStale,
  pendingTenderDocs,
  pickPrimaryTender,
  tenderStatusColor,
  tenderStatusText,
} from '@/utils/tenderDoc'

const NOW = new Date('2026-09-16T12:00:00Z').getTime()
const ago = (ms: number) => new Date(NOW - ms).toISOString()

describe('isTenderParsing', () => {
  it('uploaded / parsing 视为进行中', () => {
    expect(isTenderParsing({ status: 'uploaded' })).toBe(true)
    expect(isTenderParsing({ status: 'parsing' })).toBe(true)
  })

  it('parsed / failed / indexed 不视为进行中', () => {
    expect(isTenderParsing({ status: 'parsed' })).toBe(false)
    expect(isTenderParsing({ status: 'failed' })).toBe(false)
    expect(isTenderParsing({ status: 'indexed' })).toBe(false)
  })
})

describe('isTenderStale', () => {
  it('进行中且超过 15 分钟判定超时', () => {
    expect(isTenderStale({ status: 'parsing', created_at: ago(TENDER_PARSE_TIMEOUT_MS + 1000) }, NOW)).toBe(true)
  })

  it('进行中但未超时不判定超时', () => {
    expect(isTenderStale({ status: 'parsing', created_at: ago(60 * 1000) }, NOW)).toBe(false)
  })

  it('已结束状态永不判超时（即使时间很久）', () => {
    expect(isTenderStale({ status: 'parsed', created_at: ago(10 * 60 * 60 * 1000) }, NOW)).toBe(false)
  })

  it('created_at 非法时不判超时', () => {
    expect(isTenderStale({ status: 'parsing', created_at: 'not-a-date' }, NOW)).toBe(false)
  })
})

describe('canReparseTender', () => {
  it('parsed / failed 可重新解析', () => {
    expect(canReparseTender({ status: 'parsed', created_at: ago(1000) }, NOW)).toBe(true)
    expect(canReparseTender({ status: 'failed', created_at: ago(1000) }, NOW)).toBe(true)
  })

  it('解析中未超时不可重新解析（避免重复入队）', () => {
    expect(canReparseTender({ status: 'parsing', created_at: ago(30 * 1000) }, NOW)).toBe(false)
  })

  it('解析中超时可重新解析', () => {
    expect(canReparseTender({ status: 'parsing', created_at: ago(TENDER_PARSE_TIMEOUT_MS + 1) }, NOW)).toBe(true)
  })
})

describe('tenderStatusColor / tenderStatusText', () => {
  it('已知状态映射颜色与中文', () => {
    expect(tenderStatusColor('parsed')).toBe('blue')
    expect(tenderStatusColor('failed')).toBe('error')
    expect(tenderStatusText('parsing')).toBe('解析中')
    expect(tenderStatusText('indexed')).toBe('已完成')
  })

  it('未知状态回落 default 并原样回显文案', () => {
    expect(tenderStatusColor('weird')).toBe('default')
    expect(tenderStatusColor(null)).toBe('default')
    expect(tenderStatusText('weird')).toBe('weird')
    expect(tenderStatusText(undefined)).toBe('')
  })
})

describe('formatTenderTime', () => {
  it('空值返回 —', () => {
    expect(formatTenderTime('')).toBe('—')
    expect(formatTenderTime(null)).toBe('—')
  })

  it('非法值原样返回', () => {
    expect(formatTenderTime('bad')).toBe('bad')
  })

  it('正常值格式化为 YYYY-MM-DD HH:mm（补零）', () => {
    const d = new Date(2026, 8, 6, 9, 5)
    expect(formatTenderTime(d.toISOString())).toBe('2026-09-06 09:05')
  })
})

describe('pendingTenderDocs', () => {
  it('只保留进行中且未超时的文档', () => {
    const docs = [
      { status: 'parsing', created_at: ago(1000) },
      { status: 'parsing', created_at: ago(TENDER_PARSE_TIMEOUT_MS + 1) },
      { status: 'parsed', created_at: ago(1000) },
    ]
    expect(pendingTenderDocs(docs, NOW)).toHaveLength(1)
  })
})

describe('pickPrimaryTender', () => {
  it('取列表首条（后端按上传时间倒序）', () => {
    expect(pickPrimaryTender([{ id: 'a' }, { id: 'b' }])).toEqual({ id: 'a' })
  })

  it('空列表返回 null', () => {
    expect(pickPrimaryTender([])).toBeNull()
  })
})
