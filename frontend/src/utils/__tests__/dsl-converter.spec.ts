/**
 * dsl-converter 测试 — DSL ↔ ProseMirror JSON 双向映射
 */
import { describe, it, expect } from 'vitest'
import {
  dslToProseMirror,
  proseMirrorToDSL,
  isDSLEmpty,
} from '@/utils/dsl-converter'
import { createBlock, createContent } from '@/types/dsl'

describe('dslToProseMirror', () => {
  it('heading block → PM heading node', () => {
    const dsl = createContent([
      createBlock('heading', { level: 2, content: '系统架构' }),
    ])
    const pm = dslToProseMirror(dsl)
    expect(pm.type).toBe('doc')
    const nodes = pm.content as unknown[]
    expect(nodes.length).toBe(1)
    const heading = nodes[0] as Record<string, unknown>
    expect(heading.type).toBe('heading')
    expect((heading.attrs as Record<string, unknown>).level).toBe(2)
  })

  it('paragraph block → PM paragraph node', () => {
    const dsl = createContent([
      createBlock('paragraph', { content: '正文内容' }),
    ])
    const pm = dslToProseMirror(dsl)
    const nodes = pm.content as unknown[]
    expect(nodes.length).toBe(1)
    expect((nodes[0] as Record<string, unknown>).type).toBe('paragraph')
  })

  it('unordered list → PM bulletList', () => {
    const dsl = createContent([
      createBlock('list', {
        ordered: false,
        items: [
          { content: '项A', children: [] },
          { content: '项B', children: [] },
        ],
      }),
    ])
    const pm = dslToProseMirror(dsl)
    const nodes = pm.content as unknown[]
    expect((nodes[0] as Record<string, unknown>).type).toBe('bulletList')
  })

  it('ordered list → PM orderedList', () => {
    const dsl = createContent([
      createBlock('list', {
        ordered: true,
        items: [{ content: '第一', children: [] }],
      }),
    ])
    const pm = dslToProseMirror(dsl)
    const nodes = pm.content as unknown[]
    expect((nodes[0] as Record<string, unknown>).type).toBe('orderedList')
  })

  it('nested list → PM nested bulletList', () => {
    const dsl = createContent([
      createBlock('list', {
        ordered: false,
        items: [
          {
            content: '父项',
            children: [{ content: '子项', children: [] }],
          },
        ],
      }),
    ])
    const pm = dslToProseMirror(dsl)
    const nodes = pm.content as unknown[]
    const list = nodes[0] as Record<string, unknown>
    const listItems = list.content as unknown[]
    const firstItem = listItems[0] as Record<string, unknown>
    const itemContent = firstItem.content as unknown[]
    // paragraph + nested bulletList
    expect(itemContent.length).toBe(2)
    const nested = itemContent[1] as Record<string, unknown>
    expect(nested.type).toBe('bulletList')
  })

  it('table → PM table node', () => {
    const dsl = createContent([
      createBlock('table', {
        headers: ['A', 'B'],
        rows: [['1', '2']],
        style: 'grid',
      }),
    ])
    const pm = dslToProseMirror(dsl)
    const nodes = pm.content as unknown[]
    expect((nodes[0] as Record<string, unknown>).type).toBe('table')
    const tableContent = (nodes[0] as Record<string, unknown>).content as unknown[]
    // header row + data row
    expect(tableContent.length).toBe(2)
  })

  it('image → PM image node', () => {
    const dsl = createContent([
      createBlock('image', { url: 'https://example.com/img.png', alt: '图' }),
    ])
    const pm = dslToProseMirror(dsl)
    const nodes = pm.content as unknown[]
    const img = nodes[0] as Record<string, unknown>
    expect(img.type).toBe('image')
    expect((img.attrs as Record<string, unknown>).src).toBe('https://example.com/img.png')
  })

  it('code_block → PM codeBlock node', () => {
    const dsl = createContent([
      createBlock('code_block', { content: 'print(1)', language: 'python' }),
    ])
    const pm = dslToProseMirror(dsl)
    const nodes = pm.content as unknown[]
    expect((nodes[0] as Record<string, unknown>).type).toBe('codeBlock')
  })

  it('empty content → empty doc', () => {
    const pm = dslToProseMirror(createContent([]))
    expect((pm.content as unknown[]).length).toBe(0)
  })
})

describe('proseMirrorToDSL', () => {
  it('PM heading → DSL heading', () => {
    const pm = {
      type: 'doc',
      content: [
        { type: 'heading', attrs: { level: 3 }, content: [{ type: 'text', text: '标题' }] },
      ],
    }
    const dsl = proseMirrorToDSL(pm)
    expect(dsl.blocks.length).toBe(1)
    expect(dsl.blocks[0].type).toBe('heading')
    expect(dsl.blocks[0].level).toBe(3)
    expect(dsl.blocks[0].content).toBe('标题')
  })

  it('PM paragraph → DSL paragraph', () => {
    const pm = {
      type: 'doc',
      content: [
        { type: 'paragraph', content: [{ type: 'text', text: '正文' }] },
      ],
    }
    const dsl = proseMirrorToDSL(pm)
    expect(dsl.blocks[0].type).toBe('paragraph')
    expect(dsl.blocks[0].content).toBe('正文')
  })

  it('PM bulletList → DSL list', () => {
    const pm = {
      type: 'doc',
      content: [
        {
          type: 'bulletList',
          content: [
            {
              type: 'listItem',
              content: [
                { type: 'paragraph', content: [{ type: 'text', text: '项A' }] },
              ],
            },
          ],
        },
      ],
    }
    const dsl = proseMirrorToDSL(pm)
    expect(dsl.blocks[0].type).toBe('list')
    expect(dsl.blocks[0].ordered).toBe(false)
    expect(dsl.blocks[0].items?.length).toBe(1)
    expect(dsl.blocks[0].items?.[0].content).toBe('项A')
  })

  it('PM table → DSL table', () => {
    const pm = {
      type: 'doc',
      content: [
        {
          type: 'table',
          content: [
            {
              type: 'tableRow',
              content: [
                { type: 'tableHeader', content: [{ type: 'paragraph', content: [{ type: 'text', text: 'A' }] }] },
                { type: 'tableHeader', content: [{ type: 'paragraph', content: [{ type: 'text', text: 'B' }] }] },
              ],
            },
            {
              type: 'tableRow',
              content: [
                { type: 'tableCell', content: [{ type: 'paragraph', content: [{ type: 'text', text: '1' }] }] },
                { type: 'tableCell', content: [{ type: 'paragraph', content: [{ type: 'text', text: '2' }] }] },
              ],
            },
          ],
        },
      ],
    }
    const dsl = proseMirrorToDSL(pm)
    expect(dsl.blocks[0].type).toBe('table')
    expect(dsl.blocks[0].headers).toEqual(['A', 'B'])
    expect(dsl.blocks[0].rows).toEqual([['1', '2']])
  })

  it('PM image → DSL image', () => {
    const pm = {
      type: 'doc',
      content: [
        { type: 'image', attrs: { src: 'url', alt: '图', title: '图' } },
      ],
    }
    const dsl = proseMirrorToDSL(pm)
    expect(dsl.blocks[0].type).toBe('image')
    expect(dsl.blocks[0].url).toBe('url')
    expect(dsl.blocks[0].alt).toBe('图')
  })

  it('PM codeBlock → DSL code_block', () => {
    const pm = {
      type: 'doc',
      content: [
        { type: 'codeBlock', attrs: { language: 'python' }, content: [{ type: 'text', text: 'print(1)' }] },
      ],
    }
    const dsl = proseMirrorToDSL(pm)
    expect(dsl.blocks[0].type).toBe('code_block')
    expect(dsl.blocks[0].language).toBe('python')
    expect(dsl.blocks[0].content).toBe('print(1)')
  })

  it('PM nested list → DSL nested list', () => {
    const pm = {
      type: 'doc',
      content: [
        {
          type: 'bulletList',
          content: [
            {
              type: 'listItem',
              content: [
                { type: 'paragraph', content: [{ type: 'text', text: '父' }] },
                {
                  type: 'bulletList',
                  content: [
                    {
                      type: 'listItem',
                      content: [
                        { type: 'paragraph', content: [{ type: 'text', text: '子' }] },
                      ],
                    },
                  ],
                },
              ],
            },
          ],
        },
      ],
    }
    const dsl = proseMirrorToDSL(pm)
    expect(dsl.blocks[0].type).toBe('list')
    expect(dsl.blocks[0].items?.[0].content).toBe('父')
    expect(dsl.blocks[0].items?.[0].children.length).toBe(1)
    expect(dsl.blocks[0].items?.[0].children[0].content).toBe('子')
  })
})

describe('round-trip: DSL → PM → DSL', () => {
  it('heading round-trip', () => {
    const original = createContent([
      createBlock('heading', { level: 2, content: '标题' }),
    ])
    const pm = dslToProseMirror(original)
    const restored = proseMirrorToDSL(pm)
    expect(restored.blocks[0].type).toBe('heading')
    expect(restored.blocks[0].level).toBe(2)
    expect(restored.blocks[0].content).toBe('标题')
  })

  it('paragraph round-trip', () => {
    const original = createContent([
      createBlock('paragraph', { content: '正文段落' }),
    ])
    const pm = dslToProseMirror(original)
    const restored = proseMirrorToDSL(pm)
    expect(restored.blocks[0].type).toBe('paragraph')
    expect(restored.blocks[0].content).toBe('正文段落')
  })

  it('table round-trip', () => {
    const original = createContent([
      createBlock('table', { headers: ['A', 'B'], rows: [['1', '2']], style: 'grid' }),
    ])
    const pm = dslToProseMirror(original)
    const restored = proseMirrorToDSL(pm)
    expect(restored.blocks[0].type).toBe('table')
    expect(restored.blocks[0].headers).toEqual(['A', 'B'])
    expect(restored.blocks[0].rows).toEqual([['1', '2']])
  })

  it('image round-trip', () => {
    const original = createContent([
      createBlock('image', { url: 'https://example.com/img.png', alt: '图' }),
    ])
    const pm = dslToProseMirror(original)
    const restored = proseMirrorToDSL(pm)
    expect(restored.blocks[0].type).toBe('image')
    expect(restored.blocks[0].url).toBe('https://example.com/img.png')
    expect(restored.blocks[0].alt).toBe('图')
  })

  it('nested list round-trip', () => {
    const original = createContent([
      createBlock('list', {
        ordered: false,
        items: [
          {
            content: '父项',
            children: [{ content: '子项', children: [] }],
          },
        ],
      }),
    ])
    const pm = dslToProseMirror(original)
    const restored = proseMirrorToDSL(pm)
    expect(restored.blocks[0].type).toBe('list')
    expect(restored.blocks[0].items?.[0].content).toBe('父项')
    expect(restored.blocks[0].items?.[0].children.length).toBe(1)
    expect(restored.blocks[0].items?.[0].children[0].content).toBe('子项')
  })

  it('full document round-trip', () => {
    const original = createContent([
      createBlock('heading', { level: 2, content: '系统架构' }),
      createBlock('paragraph', { content: '正文段落。' }),
      createBlock('table', { headers: ['A', 'B'], rows: [['1', '2']], style: 'grid' }),
      createBlock('list', {
        ordered: false,
        items: [{ content: '项A', children: [] }],
      }),
      createBlock('image', { url: 'url', alt: '图' }),
      createBlock('code_block', { content: 'print(1)', language: 'python' }),
    ])
    const pm = dslToProseMirror(original)
    const restored = proseMirrorToDSL(pm)
    expect(restored.blocks.length).toBe(6)
    expect(restored.blocks.map((b) => b.type)).toEqual([
      'heading', 'paragraph', 'table', 'list', 'image', 'code_block',
    ])
  })
})

describe('isDSLEmpty', () => {
  it('null is empty', () => {
    expect(isDSLEmpty(null)).toBe(true)
  })

  it('empty blocks is empty', () => {
    expect(isDSLEmpty(createContent([]))).toBe(true)
  })

  it('non-empty content is not empty', () => {
    expect(isDSLEmpty(createContent([createBlock('paragraph', { content: 'x' })]))).toBe(false)
  })
})
