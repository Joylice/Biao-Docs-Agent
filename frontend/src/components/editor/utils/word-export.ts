/**
 * Word 导出工具：将富文本 HTML 转换为 Word 兼容的 .doc 文件
 *
 * 方案：生成带 Word XML 命名空间的 HTML 文件，保存为 .doc 扩展名
 * Word 可正常打开和编辑，格式（字体/颜色/表格/图片/列表）保留良好
 *
 * 优点：无需额外依赖，实现简单，兼容性好
 * 适用：投标技术方案导出（A4纸张、宋体/黑体、表格、图片）
 */

/** Word 文档页面设置（A4纵向，标准页边距） */
interface WordPageSettings {
  /** 纸张宽度（twips，1英寸=1440 twips） */
  pageWidth?: number
  /** 纸张高度（twips） */
  pageHeight?: number
  /** 上边距（twips） */
  marginTop?: number
  /** 下边距（twips） */
  marginBottom?: number
  /** 左边距（twips） */
  marginLeft?: number
  /** 右边距（twips） */
  marginRight?: number
}

/** 页眉页脚配置 */
interface HeaderFooterOptions {
  /** 页眉内容（支持 HTML） */
  header?: string
  /** 页脚内容（支持 HTML，{page} 会被替换为页码） */
  footer?: string
  /** 是否显示页码 */
  showPageNumber?: boolean
  /** 页码位置：center / right / left */
  pageNumberAlign?: 'center' | 'right' | 'left'
  /** 首页是否不同 */
  differentFirstPage?: boolean
  /** 首页页眉 */
  firstPageHeader?: string
  /** 首页页脚 */
  firstPageFooter?: string
}

/** 默认 A4 纵向页面设置（1英寸页边距） */
const DEFAULT_PAGE_SETTINGS: Required<WordPageSettings> = {
  // A4: 210mm × 297mm ≈ 11906 × 16838 twips
  pageWidth: 11906,
  pageHeight: 16838,
  // 1英寸 = 1440 twips
  marginTop: 1440,
  marginBottom: 1440,
  marginLeft: 1440,
  marginRight: 1440,
}

/**
 * 构建页眉页脚 HTML
 */
function buildHeaderFooter(options: HeaderFooterOptions): { headerHtml: string; footerHtml: string } {
  const {
    header = '',
    footer = '',
    showPageNumber = true,
    pageNumberAlign = 'center',
  } = options

  const alignClass = `hf-align-${pageNumberAlign}`

  const headerHtml = header
    ? `<div class="doc-header">${header}</div>`
    : ''

  let footerContent = footer
  if (showPageNumber && !footer.includes('{page}')) {
    footerContent = footerContent || `<span class="${alignClass}">第 {page} 页</span>`
  }

  const footerHtml = footerContent
    ? `<div class="doc-footer">${footerContent}</div>`
    : ''

  return { headerHtml, footerHtml }
}

/**
 * 构建 Word XML 文档头（包含页面设置、默认字体、样式）
 */
function buildWordHeader(_settings: Required<WordPageSettings>, title: string, _hfOptions?: HeaderFooterOptions): string {
  return `
<html xmlns:o="urn:schemas-microsoft-com:office:office"
      xmlns:w="urn:schemas-microsoft-com:office:word"
      xmlns="http://www.w3.org/TR/REC-html40">
<head>
<meta charset="utf-8">
<title>${escapeHtml(title)}</title>
<!--[if gte mso 9]>
<xml>
  <w:WordDocument>
    <w:View>Print</w:View>
    <w:Zoom>100</w:Zoom>
    <w:DoNotOptimizeForBrowser/>
  </w:WordDocument>
  <w:DocumentProperties>
    <w:Title>${escapeHtml(title)}</w:Title>
    <w:Author>投标方案智能体</w:Author>
  </w:DocumentProperties>
</xml>
<![endif]-->
<style>
  /* Word 文档默认样式 */
  @page {
    size: A4 portrait;
    margin: 2.54cm;
    mso-page-orientation: portrait;
  }
  @page :first {
    margin-top: 2.54cm;
  }
  body {
    font-family: '宋体', SimSun, serif;
    font-size: 12pt;
    line-height: 1.5;
    color: #000000;
  }
  /* 标题样式 */
  h1 {
    font-family: '黑体', SimHei, sans-serif;
    font-size: 22pt;
    font-weight: bold;
    text-align: center;
    margin: 24pt 0 18pt 0;
    page-break-after: avoid;
  }
  h2 {
    font-family: '黑体', SimHei, sans-serif;
    font-size: 16pt;
    font-weight: bold;
    margin: 18pt 0 12pt 0;
    page-break-after: avoid;
  }
  h3 {
    font-family: '黑体', SimHei, sans-serif;
    font-size: 14pt;
    font-weight: bold;
    margin: 12pt 0 8pt 0;
    page-break-after: avoid;
  }
  h4 {
    font-family: '黑体', SimHei, sans-serif;
    font-size: 12pt;
    font-weight: bold;
    margin: 8pt 0 6pt 0;
    page-break-after: avoid;
  }
  p {
    margin: 6pt 0;
    text-indent: 2em;
  }
  /* 列表样式 */
  ul, ol {
    margin: 6pt 0;
    padding-left: 2em;
  }
  li {
    margin: 3pt 0;
  }
  /* 表格样式 */
  table {
    border-collapse: collapse;
    width: 100%;
    margin: 10pt 0;
    font-size: 10.5pt;
  }
  th, td {
    border: 1px solid #000000;
    padding: 4pt 6pt;
    vertical-align: top;
  }
  th {
    background-color: #f2f2f2;
    font-weight: bold;
    text-align: center;
  }
  /* 图片样式 */
  img {
    max-width: 100%;
    height: auto;
  }
  /* 引用样式 */
  blockquote {
    border-left: 3px solid #999999;
    padding-left: 10pt;
    margin: 8pt 0;
    color: #666666;
  }
  /* 代码样式 */
  pre, code {
    font-family: 'Consolas', 'Courier New', monospace;
    font-size: 10pt;
    background-color: #f5f5f5;
  }
  pre {
    padding: 8pt;
    border: 1px solid #dddddd;
    white-space: pre-wrap;
  }
  code {
    padding: 1pt 3pt;
  }
  /* 分页符 */
  .page-break {
    page-break-after: always;
  }
  /* 链接样式 */
  a {
    color: #0000ff;
    text-decoration: underline;
  }
  /* 水平分割线 */
  hr {
    border: none;
    border-top: 1px solid #999999;
    margin: 12pt 0;
  }
  /* 页眉页脚样式 */
  .doc-header {
    text-align: center;
    font-size: 10.5pt;
    color: #666666;
    border-bottom: 1px solid #cccccc;
    padding-bottom: 6pt;
    margin-bottom: 12pt;
  }
  .doc-footer {
    text-align: center;
    font-size: 9pt;
    color: #666666;
    border-top: 1px solid #cccccc;
    padding-top: 6pt;
    margin-top: 12pt;
  }
  .hf-align-left { text-align: left; }
  .hf-align-center { text-align: center; }
  .hf-align-right { text-align: right; }
</style>
</head>
<body>
`
}

/** Word 文档尾 */
const WORD_FOOTER = `
</body>
</html>
`

/**
 * HTML 转义
 */
function escapeHtml(text: string): string {
  return text
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;')
}

/**
 * 清理编辑器 HTML：移除 Tiptap 特定属性，转换为 Word 兼容格式
 * - 移除 data-* 属性
 * - 移除 contenteditable 属性
 * - 移除 class 中的 Tiptap 特定类
 * - 转换分页符 div 为 page-break 类
 */
function cleanHtmlForWord(html: string): string {
  let cleaned = html

  // 移除 contenteditable 属性
  cleaned = cleaned.replace(/\scontenteditable="[^"]*"/g, '')

  // 移除 data-* 属性（Tiptap 内部使用）
  cleaned = cleaned.replace(/\sdata-[a-z-]+="[^"]*"/g, '')

  // 移除 spellcheck 属性
  cleaned = cleaned.replace(/\sspellcheck="[^"]*"/g, '')

  // 转换 Tiptap 分页符为 Word 分页符
  cleaned = cleaned.replace(
    /<div[^>]*class="[^"]*page-break[^"]*"[^>]*><\/div>/g,
    '<div class="page-break"></div>',
  )

  // 移除空的 p 标签（Tiptap 占位）
  cleaned = cleaned.replace(/<p><\/p>/g, '<p>&nbsp;</p>')

  return cleaned
}

/**
 * 导出为 Word .doc 文件
 *
 * @param html 富文本 HTML 内容
 * @param filename 文件名（不含扩展名）
 * @param title 文档标题
 * @param pageSettings 页面设置（可选，默认A4纵向1英寸边距）
 * @param headerFooter 页眉页脚配置（可选）
 */
export function exportToWord(
  html: string,
  filename: string,
  title: string = '技术方案',
  pageSettings?: WordPageSettings,
  headerFooter?: HeaderFooterOptions,
): void {
  const settings = { ...DEFAULT_PAGE_SETTINGS, ...pageSettings }

  // 构建页眉页脚
  const hf = headerFooter ?? { showPageNumber: true, pageNumberAlign: 'center' }
  const { headerHtml, footerHtml } = buildHeaderFooter(hf)

  // 构建完整 Word 文档
  const header = buildWordHeader(settings, title, hf)
  const cleanedBody = cleanHtmlForWord(html)
  const fullHtml = header + headerHtml + cleanedBody + footerHtml + WORD_FOOTER

  // 创建 Blob（Word 兼容的 MIME 类型）
  const blob = new Blob(['\ufeff', fullHtml], {
    type: 'application/msword;charset=utf-8',
  })

  // 触发下载
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = `${filename}.doc`
  document.body.appendChild(link)
  link.click()
  document.body.removeChild(link)

  // 释放 URL
  setTimeout(() => URL.revokeObjectURL(url), 100)
}

/**
 * 导出为纯 HTML 文件（备用方案，浏览器可打开）
 */
export function exportToHtml(
  html: string,
  filename: string,
  title: string = '技术方案',
): void {
  const fullHtml = `<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>${escapeHtml(title)}</title>
<style>
  body { font-family: '宋体', SimSun, serif; max-width: 800px; margin: 40px auto; padding: 0 20px; line-height: 1.6; }
  h1, h2, h3, h4 { font-family: '黑体', SimHei, sans-serif; }
  table { border-collapse: collapse; width: 100%; }
  th, td { border: 1px solid #333; padding: 8px; }
  img { max-width: 100%; }
</style>
</head>
<body>
${cleanHtmlForWord(html)}
</body>
</html>`

  const blob = new Blob([fullHtml], { type: 'text/html;charset=utf-8' })
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = `${filename}.html`
  document.body.appendChild(link)
  link.click()
  document.body.removeChild(link)
  setTimeout(() => URL.revokeObjectURL(url), 100)
}

/**
 * 打印当前文档（浏览器打印对话框）
 * 将编辑器内容写入新窗口，触发打印
 *
 * @param html 富文本 HTML 内容
 * @param title 文档标题
 * @param headerFooter 页眉页脚配置（可选）
 */
export function printDocument(
  html: string,
  title: string = '技术方案',
  headerFooter?: HeaderFooterOptions,
): void {
  const printWindow = window.open('', '_blank', 'width=900,height=700')
  if (!printWindow) {
    alert('请允许弹出窗口以进行打印')
    return
  }

  const hf = headerFooter ?? { showPageNumber: true, pageNumberAlign: 'center', header: title }
  const { headerHtml, footerHtml } = buildHeaderFooter(hf)

  const printHtml = `<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<title>${escapeHtml(title)}</title>
<style>
  @page { size: A4; margin: 2.54cm; }
  body { font-family: '宋体', SimSun, serif; font-size: 12pt; line-height: 1.5; color: #000; }
  h1, h2, h3, h4 { font-family: '黑体', SimHei, sans-serif; }
  h1 { font-size: 22pt; text-align: center; }
  h2 { font-size: 16pt; }
  h3 { font-size: 14pt; }
  h4 { font-size: 12pt; }
  p { text-indent: 2em; margin: 6pt 0; }
  table { border-collapse: collapse; width: 100%; font-size: 10.5pt; }
  th, td { border: 1px solid #000; padding: 4pt 6pt; }
  th { background: #f2f2f2; font-weight: bold; }
  img { max-width: 100%; }
  .page-break { page-break-after: always; }
  .doc-header { text-align: center; font-size: 10.5pt; color: #666; border-bottom: 1px solid #ccc; padding-bottom: 6pt; margin-bottom: 12pt; }
  .doc-footer { text-align: center; font-size: 9pt; color: #666; border-top: 1px solid #ccc; padding-top: 6pt; margin-top: 12pt; }
  @media print {
    body { margin: 0; }
  }
</style>
</head>
<body>
${headerHtml}
${cleanHtmlForWord(html)}
${footerHtml}
<script>
  window.onload = function() {
    setTimeout(function() {
      window.print();
    }, 300);
  };
</script>
</body>
</html>`

  printWindow.document.open()
  printWindow.document.write(printHtml)
  printWindow.document.close()
}
