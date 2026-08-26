# 开发计划提示词：大纲生成页与分工页职责分离改造

> **状态**：✅ 已完成（2026-08-25），4 个任务全部执行完毕并部署。
> **用途**：将本提示词完整粘贴给 AI 编码代理，即可按计划执行改造。
> **约束**：遵循 AGENTS.md 分层铁律、TDD、先读后改。所有改动须同步测试。
> **范围**：纯前端改造，不涉及后端 API 变更。

---

## 一、项目背景

投标软件技术方案智能体，业务主线：招标解析 → 大纲生成 → 方案生成（分工编制）→ 审阅导出。

技术栈：Vue 3 + TypeScript + Ant Design Vue + Vite + pnpm。前端代码位于 `frontend/src/`。

## 二、现状与问题

### 2.1 大纲生成页（GenerateView）

**文件**：`frontend/src/views/generate/GenerateView.vue`

当前大纲生成页在确认大纲后，**仍在本页执行章节内容生成**：

- 引入 `useGenerateWebSocket` composable，建立 WebSocket 连接接收流式生成内容（第 319-337 行）
- 引入方案生成状态轮询 `startGenPolling`（3s 间隔、100 次上限，第 267-291 行）
- 管理 `generating` / `generated` 状态，驱动 UI 展示生成进度和章节内容（第 210-211 行）
- `handleStartGenerate` 函数在确认大纲后启动 WebSocket + 轮询（第 360-384 行）
- `ChapterPreview` 组件的章节预览数据源为 `displayChapters`（即 workflow status 的 `chapters` 字段），非分工编制的最新内容

**问题**：大纲页职责混杂——既管大纲生成/确认，又承担章节内容生成的展示和驱动。确认大纲后应转至分工页编制，大纲页仅做预览。

### 2.2 分工页（DivisionView）

**文件**：`frontend/src/views/division/DivisionView.vue`

- 看板所有卡片对所有人可见，但缺少"本人卡片"视觉突出
- `handleSelectTask`（第 472-477 行）点击任意卡片均跳转编辑器，无只读/可编辑区分
- `resolveMoveAction`（第 485-504 行）拖拽状态转换逻辑正确，但未区分 viewer 和 assignee 的操作权限

### 2.3 编辑器（WordEditorPage）

**文件**：`frontend/src/components/editor/WordEditorPage.vue`

- `canEdit` 计算属性（第 534-539 行）：`isOwner` 时返回 `true`，即 owner 可编辑任意章节
- `canAccept`（第 540-542 行）：`!currentTask.value.assignee_id` 判断有误，应为 `currentTask.value.assignee_id === currentUserId.value`
- 非本人章节进入编辑器时，`readonly` 绑定为 `loading || !canEdit`（第 227 行），仅靠 `canEdit` 控制，但 `canEdit` 对无分工任务返回 `true`
- WordEditor 的 `:readonly` prop（第 227 行）仅控制编辑器内容区，Ribbon 工具栏、AI 辅助输入框等未联动只读

### 2.4 权限体系

**文件**：`frontend/src/composables/usePermission.ts`

- `canEditChapter`（第 92-96 行）：`isOwner || assigneeIds.some(id => id === currentUserId.value)`，即 owner 可编辑任意章节
- `canReviewChapter`（第 98 行）：仅 owner

## 三、改造目标

| 角色              | 大纲页     | 分工页          | 编辑器            |
| --------------- | ------- | ------------ | -------------- |
| 项目发起人(owner)    | 确认/编辑大纲 | 全看 + 分配 + 审核 | **只读预览**（不可编制） |
| 分工编制人(assignee) | 只读预览    | 本人卡片突出 + 全看  | **编制本人章节**     |
| 其他成员            | 只读预览    | 全看（无分配权）     | **只读预览**       |

核心原则：

1. 大纲页确认大纲后 → 引导跳转分工页，不在本页生成章节内容
2. 大纲页章节预览数据源切换为分工章节内容（`fetchChapterContent` API）
3. 编辑器对非本人章节强制只读，owner 不可编制任何章节
4. 分工人员互相可见对方卡片，但仅可编制自己的部分

## 四、任务拆解（4 个任务，按顺序执行）

### 任务 1：大纲页移除章节内容生成逻辑，改为纯预览

**文件**：`frontend/src/views/generate/GenerateView.vue`

**删除内容**：

1. 删除 `useGenerateWebSocket` import 和调用（第 192、319-337 行）
2. 删除方案生成轮询 `startGenPolling` / `stopGenPolling` / `resetGenPollCount`（第 267-291 行）
3. 删除 `generating` / `generated` ref 状态（第 210-211 行）
4. 删除 `markGenerated` 函数（第 293-299 行）
5. 删除 `currentChapter` ref（第 215 行）及其 watch（第 415-417 行）
6. 删除 WebSocket 相关的 `wsError` ref（第 218 行）和模板中的断线重连提示（第 19-25 行）
7. 删除 `handleStartGenerate` 中的 WebSocket 连接和轮询启动逻辑（第 374-377 行）

**修改内容**：

1. `handleStartGenerate` 改为：确认大纲后仅调用 `confirmOutline` API，成功后 `message.success('大纲已确认，请前往分工页进行章节编制')`，展示引导跳转 UI
2. 模板中"开始生成"按钮（第 132-139 行）改为"确认大纲并去分工"按钮，文案改为"去分工编制"
3. 删除"进入审阅"按钮（第 141-146 行），改为"去分工"按钮跳转 `Division` 路由
4. 模板中 `v-else-if="outline.length > 0 || generating || generated"` 条件（第 75 行）简化为 `v-else-if="outline.length > 0"`
5. `GenerateTabsPanel` 的 props 中移除 `generating` / `generated` / `currentChapter` / `canGoDivision`
6. `ChapterPreview` 的 props 中移除 `generating` / `generated` / `currentChapter` / `progress` / `canGoDivision`，移除"去编制"按钮和"关闭"按钮
7. `onUnmounted` 中删除 `disposeWebSocket()` 和 `stopGenPolling()`（第 428-429 行）

**新增内容**：

1. 确认大纲后展示一个引导卡片：`a-alert type="success"` + "大纲已确认" + "前往分工编制"按钮
2. 章节预览改为通过 `fetchChapterContent(projectId, chapterNo)` 拉取分工章节内容（见任务 2）

**测试要点**：

- 确认大纲后不再启动 WebSocket 和轮询
- 页面不再显示"生成中"状态
- 确认大纲后出现引导跳转分工页的 UI

### 任务 2：章节预览数据源切换为分工章节内容

**文件**：

- `frontend/src/views/generate/components/ChapterPreview.vue`
- `frontend/src/views/generate/GenerateView.vue`

**改动**：

1. `ChapterPreview.vue` 移除 props：`currentChapter` / `generating` / `generated` / `progress` / `canGoDivision`
2. `ChapterPreview.vue` 移除 emits：`close` / `go-division`
3. `ChapterPreview.vue` 新增逻辑：watch `selectedChapter`，当值变化时调用 `fetchChapterContent(projectId, selectedChapter)` 拉取分工章节内容
4. 拉取结果优先使用 `content_html`，其次 `markdownToHtml(content)`，存入本地 ref `chapterContent`
5. 模板中 `MarkdownRenderer` 的 `:source` 从 `displayChapters[selectedChapter]` 改为 `chapterContent`
6. 移除进度条 `a-progress`（第 48-54 行）和生成状态标签（第 5-28 行）
7. 新增加载状态：拉取中显示 `LoadingSkeleton`
8. `GenerateView.vue` 中移除 `chapters` ref（第 214 行）和 `displayChapters` computed（第 264 行），不再从 workflow status 读取章节内容
9. `GenerateView.vue` 中移除 `loadInitial` 中的 `chapters.value = data.chapters || {}`（第 398 行）
10. 保留评分对标 Tab 不变

**API 调用**：

```typescript
import { fetchChapterContent } from '@/api'
// 选中章节时拉取
const chapterContent = ref('')
const contentLoading = ref(false)
watch(() => props.selectedChapter, async (no) => {
  if (!no) { chapterContent.value = ''; return }
  contentLoading.value = true
  try {
    const { data } = await fetchChapterContent(props.projectId, no)
    const html = data.data?.content_html || markdownToHtml(data.data?.content || '')
    chapterContent.value = html
  } catch { chapterContent.value = '' }
  finally { contentLoading.value = false }
}, { immediate: true })
```

**测试要点**：

- 选中大纲章节后，展示的是分工编制的最新内容（而非 workflow 生成阶段的旧内容）
- 未分工的章节显示空态
- 切换章节时正确加载新内容

### 任务 3：分工页看板权限细化与本人卡片突出

**文件**：

- `frontend/src/views/division/DivisionView.vue`
- `frontend/src/views/division/components/DivisionKanban.vue`

**改动 DivisionView.vue**：

1. `handleSelectTask` 增加权限判断：
   - 当前用户是章节 assignee → 跳转编辑器（可编辑模式）
   - 当前用户是 owner 或非 assignee → 跳转编辑器（只读模式），通过 query param `readonly=1` 标记
2. 新增 computed `currentUserId` 引入（已有 `currentUserId` from stores）
3. 看板拖拽权限：仅 assignee 可拖拽本人卡片（领取/提交），owner 可拖拽审核/打回；非本人卡片不可拖拽

**改动 DivisionKanban.vue**：

1. 卡片样式区分：本人卡片的 `assignee_id === currentUserId` 时添加高亮边框（如 `border-left: 3px solid var(--color-primary)`）
2. 非本人卡片不可拖拽：`draggable` 属性绑定 `isDraggable(item)` 函数
3. `isDraggable` 逻辑：
   - 本人卡片且状态为 pending/in_progress/rejected → 可拖拽（领取/提交）
   - owner 且卡片状态为 submitted → 可拖拽（审核/打回）
   - 其他情况 → 不可拖拽
4. 卡片底部新增 assignee 名称标签（已有但需确保清晰展示）

**测试要点**：

- 本人卡片有视觉高亮
- 非本人卡片不可拖拽
- 点击非本人卡片进入编辑器为只读模式
- 点击本人卡片进入编辑器为可编辑模式

### 任务 4：编辑器非本人章节和 Owner 强制只读

**文件**：

- `frontend/src/components/editor/WordEditorPage.vue`
- `frontend/src/composables/useChapterPersistence.ts`

**改动 WordEditorPage.vue**：

1. 修改 `canEdit` 计算属性（第 534-539 行）：
   ```typescript
   const canEdit = computed(() => {
     if (!currentTask.value) return false // 无分工任务时不可编辑（仅 owner 可看）
     if (isOwner.value) return false // owner 不可编制任何章节
     if (isAssignee.value && ['in_progress', 'rejected'].includes(currentTask.value.status)) return true
     return false
   })
   ```
2. 新增 `isReadOnly` computed：
   ```typescript
   const isReadOnly = computed(() => !canEdit.value)
   ```
3. WordEditor 的 `:readonly` prop 改为 `loading || isReadOnly`（第 227 行，实际不变，因 `!canEdit` 即 `isReadOnly`）
4. Ribbon 工具栏 `WordEditorToolbar` 添加 `v-if="!isReadOnly"` 条件（第 191-199 行），只读时隐藏整个 Ribbon
5. AI 辅助输入区 `word-page__assist` 添加 `v-if="!isReadOnly"` 条件（第 234-266 行），只读时隐藏
6. 保存按钮添加 `v-if="!isReadOnly"` 条件（第 74-82 行），只读时隐藏
7. 任务操作按钮权限调整：
   - `canAccept`：改为 `isAssignee && status === 'pending'`（移除 owner 可领取）
   - `canSubmit`：保持 `canEdit && status === 'in_progress'`（canEdit 已排除 owner）
   - `canApprove`/`canReject`：保持 `isOwner && status === 'submitted'`（不变）
8. 顶部 Header 新增只读标识：当 `isReadOnly` 时展示 `a-tag color="default"` "只读模式"
9. `useChapterPersistence` 中自动保存逻辑：`isReadOnly` 时不触发自动保存

**改动 useChapterPersistence.ts**：

1. 新增 `isReadOnly` 参数（从 WordEditorPage 传入）
2. `handleContentUpdate` 回调中：如果 `isReadOnly` 则不触发防抖保存
3. `beforeunload` 拦截：`isReadOnly` 时不拦截

**测试要点**：

- Owner 进入任意章节编辑器 → 只读模式，无 Ribbon、无保存、无 AI 辅助输入
- Assignee 进入本人章节 → 正常编辑模式
- Assignee 进入非本人章节 → 只读模式
- 只读模式下导出、打印、批注查看、大纲导航、版本历史等功能正常
- 自动保存不在只读模式下触发

### 任务 5（后端完善，2026-08-25）：分工驱动模式 — 确认大纲后不自动生成

**背景**：任务 1-4 完成后，大纲页已不再展示/驱动章节生成，但后端 confirm-outline 确认后
仍会 resume 工作流自动批量生成全部章节（retrieve → write → validate 循环），
与「章节内容由分工编制」的需求冲突。本任务实现后端分工驱动模式。

**核心设计决策**（用户确认）：
1. **确认大纲后完全关闭自动批量生成**，工作流停在「待分工」（wait_division interrupt）
2. **分工审核通过（approved）时回写正式方案**（state.chapters + proposal_sections），供审阅/导出

**改动**：

| 文件 | 变更 |
|------|------|
| `backend/app/api/workflow.py` | `ConfirmOutlineBody` 增加 `start_generation: bool = False`；API 将标记传入 resume payload；`next_phase` 按标记返回 generate/division；新增 `POST /workflow/confirm-division` 端点（resume wait_division → 进入审阅） |
| `backend/app/agents/nodes/outline.py` | `confirm_outline_node` 识别 `start_generation=False`：`current_phase="division"`，图边路由到 wait_division；缺省 True 保持旧行为（测试兼容） |
| `backend/app/agents/graph.py` | 新增 `wait_division` 节点；`outline_route` 三分支：regenerate / wait_division / retrieve；`wait_division → integrate → review` |
| `backend/app/agents/nodes/wait_division.py` | 新节点（HITL interrupt）：等待分工完成，resume confirmed 后进入整合审阅 |
| `backend/app/agents/nodes/__init__.py` | re-export `wait_division_node` |
| `backend/app/services/infra/workflow_runtime.py` | 新增 `sync_approved_chapter`：审核通过章节回写 state.chapters + proposal_sections（status=approved）+ 摘要（不要求章节已存在，兼容分工驱动初始空 chapters） |
| `backend/app/api/division.py` | `review_assignment` 审核通过且内容非空时调用 `sync_approved_chapter` |
| `frontend/src/types/workflow.ts` | `ConfirmOutlineRequest` 增加 `start_generation?: boolean` |
| `frontend/src/api/workflow.ts` | 新增 `confirmDivision` API |
| `frontend/src/views/generate/GenerateView.vue` | `handleConfirmOutline` 显式传 `start_generation: false` |
| `frontend/src/views/division/DivisionView.vue` | 新增「已通过 N 章」标签 + 「进入审阅」按钮（有 approved 章节时显示），调用 confirmDivision 并跳转审阅页 |

**兼容性**：`confirm_outline_node` 节点层 `decision.get("start_generation", True)` 缺省 True，
直接 resume True 的旧调用路径（测试）仍走自动生成链路；API 层默认 False 满足新需求。

**测试**（新增 8 个，全部通过）：
- `tests/services/test_workflow_runtime.py`：4 个（start_generation=False 停靠、旧行为兼容、
  wait_division resume 进审阅、sync_approved_chapter 回写）
- `tests/api/test_workflow.py`：2 个（confirm-outline 传 start_generation、confirm-division 端点）
- `tests/api/test_division.py`：2 个（审核通过内容回写、内容为空跳过回写）

**回归**：后端完整测试 1154 passed / 0 failed；前端 vue-tsc 0 errors。

## 五、文件变更清单

| 文件路径                                                           | 变更类型 | 说明                                                         |
| -------------------------------------------------------------- | ---- | ---------------------------------------------------------- |
| `frontend/src/views/generate/GenerateView.vue`                 | 修改   | 移除 WebSocket/轮询，改为纯预览+引导跳转                                 |
| `frontend/src/views/generate/components/ChapterPreview.vue`    | 修改   | 数据源切换为 fetchChapterContent                                 |
| `frontend/src/views/generate/components/GenerateTabsPanel.vue` | 修改   | 移除 generating/generated/currentChapter/canGoDivision props |
| `frontend/src/views/division/DivisionView.vue`                 | 修改   | handleSelectTask 权限区分，拖拽权限                                 |
| `frontend/src/views/division/components/DivisionKanban.vue`    | 修改   | 本人卡片高亮，非本人不可拖拽                                             |
| `frontend/src/components/editor/WordEditorPage.vue`            | 修改   | canEdit 收紧，Ribbon/AI/保存只读隐藏                                |
| `frontend/src/composables/useChapterPersistence.ts`            | 修改   | isReadOnly 时不触发自动保存                                        |
| `backend/app/api/workflow.py`                                | 修改   | start_generation 参数 + confirm-division 端点                    |
| `backend/app/agents/nodes/outline.py`                         | 修改   | 识别 start_generation=False → division 阶段                    |
| `backend/app/agents/graph.py`                                | 修改   | wait_division 节点 + 三分支路由                              |
| `backend/app/agents/nodes/wait_division.py`                   | 新增   | 待分工 HITL interrupt 节点                                  |
| `backend/app/services/infra/workflow_runtime.py`              | 修改   | sync_approved_chapter 审核通过回写                          |
| `backend/app/api/division.py`                                | 修改   | 审核通过时回写正式方案                                      |

## 六、执行约束

1. **先读后改**：每个文件改动前先 Read 确认当前内容
2. **分层铁律**：纯前端改动，不涉及后端 API 或 service 层
3. **TDD**：每个任务先写/改测试再实现，前端测试位于 `frontend/src/**/*.spec.ts`
4. **不混入无关重构**：仅做上述清单中的改动，不顺便重构其他代码
5. **Conventional Commits**：`feat: 大纲页与分工页职责分离改造`
6. **类型安全**：所有改动通过 `vue-tsc -b` 类型检查（0 errors）
7. **验证命令**：`cd frontend && npx vue-tsc -b --noEmit && pnpm lint`

## 七、验收标准

- [ ] 大纲页确认大纲后不启动 WebSocket/轮询，展示引导跳转分工页
- [ ] 大纲页章节预览数据来自 `fetchChapterContent` API（分工编制的最新内容）
- [ ] 分工页看板本人卡片高亮，非本人卡片不可拖拽
- [ ] 分工页点击非本人卡片进入编辑器为只读模式
- [ ] 编辑器：Owner 进入任意章节为只读模式（无 Ribbon、无保存、无 AI 辅助输入）
- [ ] 编辑器：Assignee 进入非本人章节为只读模式
- [ ] 编辑器：Assignee 进入本人章节为正常编辑模式
- [ ] 只读模式下导出、打印、批注、大纲导航、版本历史功能正常
- [ ] `vue-tsc -b` 类型检查 0 errors
- [ ] `pnpm lint` 无新增 lint 错误
- [x] 后端：确认大纲后工作流停在 wait_division，不自动批量生成章节（start_generation=false）
- [x] 后端：分工审核通过时内容回写 state.chapters + proposal_sections（status=approved）
- [x] 后端：分工页「进入审阅」→ confirm-division → resume → review
- [x] 后端完整测试 1154 passed / 0 failed
