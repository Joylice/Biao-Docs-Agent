/**
 * N6 契约守卫 —— N7/N8/N9 纯重构的**行为等价机械凭据**。
 *
 * 为什么需要：这三个阶段是「编排层按域外置」的纯重构（不改行为），而**页级行为没有自动化
 * 覆盖** —— `src/**\/*.spec.ts` 覆盖的是 composable/store/util，没有一个挂载页面组件。
 * 本脚本把 `docs/editor-refactor-checklist.md` §四 的**硬契约**变成可机械复跑的断言。
 *
 * 它守的是什么（改了就是回归，多数**编译期查不出**）：
 * - 路由 path/name（含「编辑器用单数 `/project/`、工作区用复数 `/projects/`」这个坑）；
 * - 5 处子组件 `defineExpose` 的方法名（ref 调用式契约，不 expose → **运行期**才报
 *   `is not a function`）；
 * - 4 个 composable 的导出面与**默认值**（默认值即契约）；
 * - `useEditorHotkeys` 的 18 个 combo、`useDivisionBoard` 的 34 项返回面与 3 个看板快捷键；
 * - 两个页面仍装配同一批子组件与 composable，导出/打印/目录能力仍从原路径导入。
 *
 * 运行：cd frontend && node scripts/check-editor-contracts.mjs
 * 退出码：0 = 全部契约在位；1 = 有契约被破坏（逐条列出）
 * 用法：N7/N8/N9 **改动前后各跑一次**，两份输出应完全一致。
 * 注意：本脚本**只做静态结构断言**，不替代人工视觉复核（见清单 §5/§6）。
 */
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import path from 'node:path'

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..')
const read = (rel) => readFileSync(path.join(ROOT, rel), 'utf8')

let failed = 0
let checked = 0
const ok = (msg) => {
  checked++
  console.log(`  ok    ${msg}`)
}
const bad = (msg) => {
  checked++
  failed++
  console.error(`  FAIL  ${msg}`)
}
const assert = (cond, msg) => (cond ? ok(msg) : bad(msg))
const group = (title) => console.log(`\n[${title}]`)

/** 取 `name(` 起、配平括号为止的整块文本（找不到返回 null） */
function callBlock(src, name) {
  const i = src.indexOf(`${name}(`)
  if (i < 0) return null
  let depth = 0
  for (let j = i + name.length; j < src.length; j++) {
    if (src[j] === '(') depth++
    else if (src[j] === ')') {
      depth--
      if (depth === 0) return src.slice(i, j + 1)
    }
  }
  return null
}

/** 取**最后一个** `return {` 起、配平花括号为止的整块（找不到返回 null） */
function returnBlock(src) {
  const i = src.lastIndexOf('return {')
  if (i < 0) return null
  let depth = 0
  for (let j = i + 'return {'.length - 1; j < src.length; j++) {
    if (src[j] === '{') depth++
    else if (src[j] === '}') {
      depth--
      if (depth === 0) return src.slice(i, j + 1)
    }
  }
  return null
}

const hasWord = (block, word) => block !== null && new RegExp(`\\b${word}\\b`).test(block)

const F = {
  router: 'src/router/index.ts',
  editorPage: 'src/components/editor/WordEditorPage.vue',
  reviewView: 'src/views/review/ReviewView.vue',
  panels: 'src/composables/useEditorPanels.ts',
  hotkeys: 'src/composables/useEditorHotkeys.ts',
  aiAssist: 'src/composables/useEditorAiAssist.ts',
  divisionBoard: 'src/views/division/composables/useDivisionBoard.ts',
  annModal: 'src/views/review/components/AnnotationEditModal.vue',
  actionPanel: 'src/views/review/components/ReviewActionPanel.vue',
  autoComments: 'src/views/review/components/ReviewAutoComments.vue',
  webSearchPanel: 'src/components/configCenter/panels/WebSearchPanel.vue',
  verCompare: 'src/views/review/components/ReviewVersionCompare.vue',
  verModals: 'src/views/review/components/ReviewVersionModals.vue',
  verSection: 'src/views/review/components/ReviewVersionSection.vue',
}

console.log('N6 契约守卫 — 清单 §四 硬契约静态校验（前置检查，非行为测试）')

/* ────────────────────────────── 1. 路由 ────────────────────────────── */
group('路由契约（src/router/index.ts）')
{
  const rt = read(F.router)
  const pairs = [
    ["path: '/project/:projectId/editor/:chapterNo'", "name: 'ChapterEditor'", '编辑器页'],
    ["path: '/projects/:projectId'", "name: 'Workspace'", '工作区父路由'],
    ["path: 'review'", "name: 'Review'", '审阅子路由'],
    ["path: 'division'", "name: 'Division'", '分工子路由'],
  ]
  for (const [p, n, label] of pairs) {
    assert(rt.includes(p), `${label} path 在位：${p}`)
    assert(rt.includes(n), `${label} name 在位：${n}`)
  }
  assert(!rt.includes("path: '/projects/:projectId/editor"), '编辑器路由不得变成复数 /projects/')
  assert(rt.includes('children: ['), '工作区仍以 children 承载子路由（否则侧边栏高亮/默认跳转失效）')
}

/* ─────────────────── 2. 子组件 defineExpose（运行期才报错） ─────────────────── */
group('子组件 defineExpose 契约（ref 调用式；不 expose 只在运行期报错）')
{
  const expects = [
    [F.annModal, ['open'], 'AnnotationEditModal'],
    [F.actionPanel, ['setComment'], 'ReviewActionPanel'],
    [F.verCompare, ['loadAndCompare'], 'ReviewVersionCompare'],
    [F.verModals, ['openSnapshotModal', 'openArchiveModal', 'snapshotting'], 'ReviewVersionModals'],
    [F.verSection, ['load', 'isOwner', 'versions'], 'ReviewVersionSection'],
  ]
  for (const [file, keys, label] of expects) {
    const block = callBlock(read(file), 'defineExpose')
    assert(block !== null, `${label} 仍有 defineExpose(...)`)
    for (const k of keys) assert(hasWord(block, k), `${label} 仍暴露 ${k}`)
  }
}

/* ─────────────────── 3. useEditorPanels：导出面 + 默认值 ─────────────────── */
group('useEditorPanels 导出面与默认值（默认值即契约）')
{
  const src = read(F.panels)
  const ret = returnBlock(src)
  const keys = [
    'outlineVisible',
    'rulerVisible',
    'propertiesVisible',
    'commentsVisible',
    'versionHistoryVisible',
    'searchVisible',
    'searchMode',
    'zoom',
    'linkModalOpen',
    'linkUrl',
    'fileInputRef',
    'searchQuery',
    'toggleProperties',
    'toggleComments',
    'toggleVersionHistory',
  ]
  assert(ret !== null, 'useEditorPanels 仍有 return { ... }')
  for (const k of keys) assert(hasWord(ret, k), `useEditorPanels 返回 ${k}`)
  assert(/outlineVisible\s*=\s*ref\(false\)/.test(src), '默认：大纲隐藏（false）')
  assert(/rulerVisible\s*=\s*ref\(true\)/.test(src), '默认：标尺显示（true，Word 风格）')
  assert(/propertiesVisible\s*=\s*ref\(false\)/.test(src), '默认：属性面板关闭')
  assert(/commentsVisible\s*=\s*ref\(false\)/.test(src), '默认：批注面板关闭')
  assert(/versionHistoryVisible\s*=\s*ref\(false\)/.test(src), '默认：版本历史关闭')
  assert(/searchVisible\s*=\s*ref\(false\)/.test(src), '默认：查找面板关闭')
  assert(/zoom\s*=\s*ref\(100\)/.test(src), '默认：缩放 100')
  assert(/searchMode\s*=\s*ref<[^>]*>\('find'\)/.test(src), "默认：查找模式 'find'")
}

/* ─────────────────── 4. useEditorHotkeys：18 个 combo ─────────────────── */
group('useEditorHotkeys 快捷键契约（17 项绑定 / 18 个 combo）')
{
  const src = read(F.hotkeys)
  const combos = [
    'ctrl+s',
    'ctrl+f',
    'ctrl+h',
    'ctrl+l',
    'ctrl+e',
    'ctrl+r',
    'ctrl+j',
    'ctrl+1',
    'ctrl+2',
    'ctrl+3',
    'ctrl+shift+>',
    'ctrl+shift+<',
    'ctrl+shift+c',
    'ctrl+shift+v',
    'alt+shift+arrowleft',
    'alt+shift+arrowright',
    'ctrl+enter',
    'escape',
  ]
  for (const c of combos) assert(src.includes(`combo: '${c}'`), `快捷键在位：${c}`)
  assert(src.includes('allowInInput: true'), 'allowInInput: true 语义保留（输入框内也生效）')
  assert(src.includes('isContentEditable'), 'ctrl+enter 的 contenteditable 跳过判断保留')
}

/* ─────────────────── 5. useEditorAiAssist：导出面与门禁 ─────────────────── */
group('useEditorAiAssist 导出面与门禁')
{
  const src = read(F.aiAssist)
  const ret = returnBlock(src)
  for (const k of ['assistPrompt', 'assistMode', 'assisting', 'handleAssist'])
    assert(hasWord(ret, k), `useEditorAiAssist 返回 ${k}`)
  assert(/assistMode\s*=\s*ref<[^>]*>\('append'\)/.test(src), "默认：assistMode 'append'")
  const options = ['projectId', 'chapterNo', 'getEditor', 'getCurrentTask', 'getIsAssignee']
  for (const o of options) assert(src.includes(o), `注入项在位：${o}`)
  const messages = [
    '未找到当前章节的分工记录，请先在分工页推送分工',
    '仅章节负责人可使用 AI 辅助功能',
    '请先领取任务后再使用 AI 辅助',
  ]
  for (const m of messages) assert(src.includes(m), `门禁文案在位：${m.slice(0, 12)}…`)
  assert(src.includes("status === 5011"), 'AI 失败映射保留 5011 分支')
}

/* ─────────────────── 6. useDivisionBoard：签名 + 34 项返回面 ─────────────────── */
group('useDivisionBoard 注入签名与返回面（可注入依赖是测试缝，签名不得改）')
{
  const src = read(F.divisionBoard)
  for (const k of ['api: DivisionApi', 'notify: DivisionNotify', 'routerPush:', 'fetchCurrentUserRole:'])
    assert(src.includes(k), `注入依赖在位：${k}`)
  for (const k of [
    'DivisionApi',
    'DivisionNotify',
    'DivisionRouteTarget',
    'AssignRow',
    'MoveAction',
  ])
    assert(new RegExp(`export (interface|type|const|function) ${k}\\b`).test(src), `模块级导出在位：${k}`)
  // flattenAssignmentNodes / sectionTitleOf 移至 divisionUtils.ts（N9 拆分）；useDivisionBoard re-export
  const divUtils = read('src/views/division/composables/divisionUtils.ts')
  assert(new RegExp(`export (interface|type|const|function) flattenAssignmentNodes\\b`).test(divUtils), '模块级导出在位：flattenAssignmentNodes（divisionUtils.ts）')
  assert(new RegExp(`export (interface|type|const|function) sectionTitleOf\\b`).test(divUtils), '模块级导出在位：sectionTitleOf（divisionUtils.ts）')
  assert(src.includes('flattenAssignmentNodes'), 'useDivisionBoard 仍引用 flattenAssignmentNodes')
  assert(src.includes('sectionTitleOf'), 'useDivisionBoard 仍引用 sectionTitleOf')

  const ret = returnBlock(src)
  const keys = [
    'loading',
    'loadError',
    'items',
    'isOwner',
    'outline',
    'assignTree',
    'members',
    'draftAssignees',
    'assigning',
    'filterAssignee',
    'assignColumns',
    'memberOptions',
    'filterMember',
    'assignRows',
    'assignableRows',
    'changedItems',
    'changedCount',
    'assigneeFilterOptions',
    'filteredItems',
    'myTaskCount',
    'approvedCount',
    'confirmingDivision',
    'handleConfirmDivision',
    'syncDraftBaseline',
    'fetchAssignments',
    'fetchOutline',
    'fetchProjectOwner',
    'fetchMembers',
    'fetchAll',
    'handleAssign',
    'handleSelectTask',
    'resolveMoveAction',
    'handleMoveTask',
    'handleKanbanUndo',
    'handleKanbanRedo',
    'goToGenerate',
  ]
  assert(ret !== null, 'useDivisionBoard 仍有 return { ... }')
  for (const k of keys) assert(hasWord(ret, k), `useDivisionBoard 返回 ${k}`)
  // 看板快捷键移至 useDivisionDragDrop.ts（N9 拆分）
  const dragDrop = read('src/views/division/composables/useDivisionDragDrop.ts')
  for (const c of ['ctrl+z', 'ctrl+shift+z', 'ctrl+y'])
    assert(dragDrop.includes(`combo: '${c}'`), `看板快捷键在位：${c}（useDivisionDragDrop.ts）`)
  assert(
    /onMounted\(\(\)\s*=>\s*\{[\s\S]{0,200}?fetchAll\(\)[\s\S]{0,200}?fetchCurrentUserRole\(\)/.test(src),
    'onMounted 仍调 fetchAll() + fetchCurrentUserRole()',
  )
}

/* ─────────────────── 7. 页面装配：子组件 / composable / 能力导入 ─────────────────── */
group('WordEditorPage 装配契约（src/components/editor/WordEditorPage.vue）')
{
  const src = read(F.editorPage)
  const children = [
    'WordEditorToolbar',
    'WordEditorStatusBar',
    'WordEditorOutline',
    'ChapterNavigator',
    'WordEditorSearchPanel',
    'WordEditorTableToolbar',
    'WordEditorImageToolbar',
    'WordEditorContextMenu',
    'WordEditorRuler',
    'WordEditorProperties',
    'WordEditorComments',
    'WordEditorVersionHistory',
    'PaginatedPreview',
  ]
  for (const c of children) assert(src.includes(c), `仍装配子组件 ${c}`)
  for (const f of ['exportToWord', 'printDocument'])
    assert(src.includes(f), `导出能力在位：${f}`)
  for (const f of ['insertToc', 'updateToc']) assert(src.includes(f), `目录能力在位：${f}`)
  assert(src.includes("from './utils/word-export'"), 'word-export 导入路径不变')
  assert(src.includes("from './utils/toc-generator'"), 'toc-generator 导入路径不变')
  assert(src.includes('shallowRef'), 'shallowRef 仍在用（tiptap Editor 换 ref 会运行期崩）')
  assert(/router\.push\(\{\s*name:\s*'Division'/.test(src), "跳转分工页 { name: 'Division' } 不变")
  const composables = [
    'useTaskWorkflow',
    'useEditorHotkeys',
    'useImageUpload',
    'useFormatBrush',
    'useAiAssistant',
    'useChapterPersistence',
    'useEditorPanels',
    'useEditorAiAssist',
    'useEditorTextUtils',
  ]
  for (const c of composables) assert(src.includes(c), `仍装配 ${c}`)
}

group('ReviewView 装配契约（src/views/review/ReviewView.vue）')
{
  const src = read(F.reviewView)
  const children = [
    'ReviewChapterList',
    'ReviewProgressBar',
    'ReviewActionPanel',
    'ReviewVersionSection',
    'ReviewVersionCompare',
    'ReviewExportModal',
    'AnnotationEditModal',
    'ReviewAnnotationPanel',
    'ReviewContentArea',
  ]
  for (const c of children) assert(src.includes(c), `仍装配子组件 ${c}`)
  // PaginatedPreview 装配在 ReviewContentArea 子组件中（N8 拆分后移出 ReviewView）
  const contentArea = read('src/views/review/components/ReviewContentArea.vue')
  assert(contentArea.includes('PaginatedPreview'), 'PaginatedPreview 仍装配在 ReviewContentArea 中')
  assert(contentArea.includes('WordEditor'), 'WordEditor 仍装配在 ReviewContentArea 中')
  for (const c of [
    'useAnnotations',
    'useAnnotationView',
    'useReviewState',
    'useReviewNavigation',
    'useReviewActions',
  ])
    assert(src.includes(c), `仍装配 ${c}`)
  assert(src.includes('ReviewAutoComments'), '仍装配 ReviewAutoComments（AI 自动审阅意见卡片）')
  assert(src.includes('审阅与导出'), '页头标题「审阅与导出」在位')
  assert(src.includes('审阅生成内容，批注修改意见或确认导出'), '副标题在位')
  // 批注动态 placeholder 在 N8 后移入 ReviewAnnotationPanel 子组件
  const annPanel = read('src/views/review/components/ReviewAnnotationPanel.vue')
  assert(annPanel.includes('对选中文字添加批注'), '批注动态 placeholder 在 ReviewAnnotationPanel 中')
  assert(src.includes('回滚成功，已恢复'), '回滚成功提示在位')
}

/* ─────────────── 外部工具绑定 UI（"绑定即生效"口径：只列有调用点的节点） ─────────────── */
group('外部工具绑定契约（stageNodes.ts / WebSearchPanel.vue / useExternalToolsConfig.ts）')
{
  const nodes = read('src/config/stageNodes.ts')
  const panel = read(F.webSearchPanel)
  const composable = read('src/composables/useExternalToolsConfig.ts')

  assert(nodes.includes('BINDABLE_STAGE_NODE_KEYS'), 'stageNodes 导出 BINDABLE_STAGE_NODE_KEYS')
  // 必须做**集合等价**（含"多一个"），不能只做前缀匹配 —— 变异验证证实：
  // 只匹配前 4 项时，往数组里塞回 'export' 守卫照样 rc=0（漏报新增）。
  const bindableMatch = nodes.match(/BINDABLE_STAGE_NODE_KEYS[^=]*=\s*\[([^\]]*)\]/)
  const bindableKeys = bindableMatch
    ? bindableMatch[1]
        .split(',')
        .map((s) => s.trim().replace(/^'|'$/g, ''))
        .filter(Boolean)
    : []
  assert(
    JSON.stringify(bindableKeys) === JSON.stringify(['parse', 'outline', 'generate', 'review']),
    '可绑定节点集合恰为 parse/outline/generate/review（「方案导出」不入列）',
  )
  assert(nodes.includes("label: '方案导出'"), '「方案导出」节点仍在 5 节点归并表中（路由/概览面板依赖）')

  const idx = panel.indexOf('const unboundNodes')
  assert(idx >= 0, 'WebSearchPanel 仍有 unboundNodes（绑定下拉数据源）')
  const unboundBlock = idx >= 0 ? panel.slice(idx, idx + 300) : ''
  assert(
    unboundBlock.includes('BINDABLE_NODE_GROUPS'),
    '绑定下拉取 BINDABLE_NODE_GROUPS（「方案导出」不进下拉）',
  )
  assert(
    !unboundBlock.includes('STAGE_NODE_GROUPS'),
    '绑定下拉不得回退全量 STAGE_NODE_GROUPS（否则方案导出回到下拉）',
  )
  assert(panel.includes('legacyBoundNodes'), '存量假绑定仍有解绑通道（不静默隐藏）')
  assert(
    composable.includes('BINDABLE_STAGE_NODE_KEYS.includes(nodeKey)'),
    'bindNode 用 BINDABLE_STAGE_NODE_KEYS 兜底（防经代码路径写入假绑定）',
  )
}

/* ─────────────── S4：SKILL.md 契约体系（skills 分类 / 双面板改名 / api 封装） ─────────────── */
group('S4 行为准则契约（configRegistry / SkillPanel / api/skills / useSkillsConfig）')
{
  const registry = read('src/config/configRegistry.ts')
  const panel = read('src/components/configCenter/panels/SkillPanel.vue')
  const toolPanel = read('src/components/configCenter/panels/ToolBindingsPanel.vue')
  const api = read('src/api/skills.ts')
  const skillsCfg = read('src/composables/useSkillsConfig.ts')
  const toolCfg = read('src/composables/useToolBindingsConfig.ts')

  // 分类集合等价（铁律⑤：禁前缀匹配 —— 前缀拦不住「多一个/换一个」）
  const catsMatch = registry.match(/const categories[^=]*=\s*\[([\s\S]*?)\n\]/)
  const catIds = catsMatch
    ? [...catsMatch[1].matchAll(/id:\s*'([a-z]+)'/g)].map((m) => m[1])
    : []
  assert(
    JSON.stringify(catIds) ===
      JSON.stringify(['overview', 'llm', 'retrieval', 'websearch', 'tools', 'skills', 'system']),
    '一级分类集合恰为 7 项（S4：「技能」→ tools 外部工具，新增 skills 行为准则）',
  )
  assert(!/panels\/SkillsPanel\.vue/.test(registry), 'configRegistry 不再 import SkillsPanel（已更名，防回退）')

  // 条目 → 面板绑定
  const tIdx = registry.indexOf("id: 'tools:bindings'")
  assert(
    tIdx >= 0 && registry.slice(tIdx, tIdx + 500).includes('markRaw(ToolBindingsPanel)'),
    'tools:bindings 挂 ToolBindingsPanel（外部工具绑定）',
  )
  const sIdx = registry.indexOf("id: 'skills:list'")
  assert(
    sIdx >= 0 && registry.slice(sIdx, sIdx + 500).includes('markRaw(SkillPanel)'),
    'skills:list 挂 SkillPanel（行为准则）',
  )

  // api 端点面（对齐后端 /settings/skills 9 端点；仅需登录无 admin）
  for (const fn of [
    'getSkills',
    'getSkill',
    'createSkill',
    'updateSkill',
    'deleteSkill',
    'resetSkill',
    'exportSkills',
    'importSkills',
    'previewSkill',
  ])
    assert(new RegExp(`export const ${fn}\\b`).test(api), `api/skills 导出 ${fn}`)
  assert(api.includes('/settings/skills'), 'api/skills 端点前缀 /settings/skills')
  assert(api.includes('expected_version'), 'api/skills 透传 expected_version（乐观锁前端半边）')

  // SkillPanel 内置只读（前端把 403 变成不渲染 —— 后端门禁的 UI 前置防线）
  const writeGuards = (panel.match(/v-if="!row\.builtin"/g) || []).length
  assert(
    writeGuards >= 4,
    `内置行不渲染写操作（v-if="!row.builtin" × ${writeGuards} ≥ 4）`,
  )
  assert(panel.includes('onReset'), '覆盖内置行有「恢复内置」入口（onReset 接线）')
  assert(panel.includes('row.shadowsBuiltin'), '恢复内置按钮按 shadowsBuiltin 显隐')

  // useSkillsConfig：乐观锁版本回写（连续两次保存第二次不 409 的关键）
  assert(
    /optimisticVersion\s*=\s*updated\.optimisticVersion/.test(skillsCfg),
    'useSkillsConfig 保存后回写 optimisticVersion（防连续保存 409）',
  )

  // 改名防交叉回退（import 语句级精确匹配，注释里的改名史不误伤）
  assert(
    !/from '@\/composables\/useToolBindingsConfig'/.test(panel),
    'SkillPanel 不引用 useToolBindingsConfig（语义防串）',
  )
  assert(
    !/from '@\/composables\/useSkillsConfig'/.test(toolPanel),
    'ToolBindingsPanel 不引用 useSkillsConfig（语义防串）',
  )
  assert(skillsCfg.includes('SkillView'), 'useSkillsConfig 消费 SkillView（真 skill 模型）')
  assert(toolCfg.includes('ToolRow'), 'useToolBindingsConfig 仍导出 ToolRow（工具视图行）')
}

/* ────────────────────────────── 汇总 ────────────────────────────── */
console.log('\n' + '─'.repeat(64))
if (failed === 0) {
  console.log(`契约守卫通过：${checked} 项断言全部在位。`)
  process.exit(0)
} else {
  console.error(`契约守卫失败：${checked} 项断言中 ${failed} 项被破坏（见上方 FAIL 行）。`)
  console.error('若确为有意变更，请同步更新 docs/editor-refactor-checklist.md §四 并在此处登记。')
  process.exit(1)
}
