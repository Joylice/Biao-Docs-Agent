<template>
  <div class="division-view">
    <PageContainer
      title="方案生成与分工"
      subtitle="拖拽卡片切换状态，点击卡片编辑章节内容"
    >
      <!-- 章节分工（仅 owner 可见）：为章节指定负责人并推送分工 -->
      <a-card
        v-if="isOwner"
        title="章节分工"
        class="division-view__assign-card"
      >
        <template #extra>
          <a-button
            type="primary"
            size="small"
            :disabled="changedCount === 0"
            :loading="assigning"
            @click="handleAssign"
          >
            {{ changedCount > 0 ? `推送分工（${changedCount} 项）` : '推送分工' }}
          </a-button>
        </template>
        <EmptyState
          v-if="outline.length === 0"
          illustration="board"
          description="暂无大纲，请先到「方案大纲生成」页确认大纲"
        >
          <template #action>
            <a-button
              type="primary"
              @click="goToGenerate"
            >
              前往方案大纲生成
            </a-button>
          </template>
        </EmptyState>
        <a-table
          v-else
          :columns="assignColumns"
          :data-source="assignRows"
          :pagination="false"
          row-key="chapter_no"
          size="middle"
        >
          <template #bodyCell="{ column, record }">
            <template v-if="column.key === 'chapter'">
              {{ record.chapter_no }} {{ record.title }}
            </template>
            <template v-else-if="column.key === 'assignee'">
              <a-select
                v-model:value="draftAssignees[record.chapter_no]"
                :options="memberOptions"
                placeholder="选择负责人"
                allow-clear
                show-search
                :filter-option="filterMember"
                style="width: 180px"
              />
            </template>
            <template v-else-if="column.key === 'status'">
              <a-tag
                v-if="record.status && TASK_STATUS_META[record.status as TaskStatus]"
                :color="TASK_STATUS_META[record.status as TaskStatus].color"
              >
                {{ TASK_STATUS_META[record.status as TaskStatus].text }}
              </a-tag>
              <span v-else>—</span>
            </template>
          </template>
        </a-table>
      </a-card>

      <!-- 工具栏 -->
      <div class="division-view__toolbar">
        <a-space wrap>
          <a-select
            v-if="isOwner"
            v-model:value="filterAssignee"
            placeholder="全部负责人"
            allow-clear
            style="width: 180px"
            :options="assigneeFilterOptions"
          />
          <a-tag v-else color="processing">
            仅显示我的任务
          </a-tag>
          <a-tag color="blue">
            共 {{ filteredItems.length }} 个章节
          </a-tag>
          <a-tag
            v-if="myTaskCount > 0"
            color="processing"
          >
            我的任务 {{ myTaskCount }}
          </a-tag>
        </a-space>
        <a-space>
          <a-button
            :loading="loading"
            @click="fetchAll"
          >
            <template #icon>
              <ReloadOutlined />
            </template>
            刷新
          </a-button>
          <a-tag
            v-if="approvedCount > 0"
            color="success"
          >
            已通过 {{ approvedCount }} 章
          </a-tag>
          <a-button
            v-if="approvedCount > 0"
            type="primary"
            :loading="confirmingDivision"
            @click="handleConfirmDivision"
          >
            <template #icon>
              <CheckCircleOutlined />
            </template>
            进入审阅
          </a-button>
          <a-button
            type="primary"
            ghost
            @click="goToGenerate"
          >
            <template #icon>
              <ArrowLeftOutlined />
            </template>
            返回大纲
          </a-button>
        </a-space>
      </div>

      <!-- 加载/错误状态 -->
      <LoadingSkeleton
        v-if="loading"
        :rows="6"
      />
      <ErrorState
        v-else-if="loadError"
        :description="loadError"
      >
        <template #action>
          <a-button
            type="primary"
            @click="fetchAll"
          >
            重试
          </a-button>
        </template>
      </ErrorState>

      <!-- 5列泳道看板（无任务时展示空态插画） -->
      <EmptyState
        v-else-if="items.length === 0"
        illustration="board"
        description="暂无分工任务，确认大纲并推送分工后任务将出现在看板"
      />

      <template v-else>
        <DivisionKanban
          :items="filteredItems"
          :is-owner="isOwner"
          @select="handleSelectTask"
          @move="handleMoveTask"
        />
      </template>
    </PageContainer>

    <!-- 章节编辑改为全屏富文本编辑器页面（路由跳转） -->
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { message } from 'ant-design-vue'
import {
  ArrowLeftOutlined,
  CheckCircleOutlined,
  ReloadOutlined,
} from '@ant-design/icons-vue'
import { fetchWorkflowStatus, confirmDivision } from '@/api/workflow'
import {
  fetchChapterAssignments,
  upsertChapterAssignments,
  acceptAssignment,
  submitAssignment,
  approveAssignment,
  rejectAssignment,
  fetchProject,
  fetchProjectMembers,
} from '@/api'
import PageContainer from '@/components/PageContainer.vue'
import ErrorState from '@/components/ErrorState.vue'
import EmptyState from '@/components/EmptyState.vue'
import LoadingSkeleton from '@/components/LoadingSkeleton.vue'
import DivisionKanban from './components/DivisionKanban.vue'
import { currentUserId, fetchCurrentUserRole } from '@/stores/currentUser'
import { usePermission } from '@/composables/usePermission'
import { useHotkeys } from '@/composables/useHotkeys'
import { useUndoRedo } from '@/composables/useUndoRedo'
import { TASK_STATUS_META } from '@/types'
import type {
  AssignmentItem,
  TaskStatus,
  AssignmentNode,
  ProjectMember,
  OutlineItem,
  OutlineSection,
} from '@/types'

const route = useRoute()
const router = useRouter()
const projectId = route.params.projectId as string

const { isProjectOwner } = usePermission()

// 状态
const loading = ref(false)
const loadError = ref('')
/**
 * 看板撤销/重做：items 即快照栈的 state。拖拽移动前 push 快照，
 * 移动成功后后端刷新数据但保留历史（撤销仅恢复本地视图，不回滚后端状态）。
 */
const kanbanHistory = useUndoRedo<AssignmentItem[]>([])
const items = kanbanHistory.state
const projectOwnerId = ref('')

// 分配面板（仅 owner）：大纲主干、树形分工数据、成员列表、分配草稿与提交态
const outline = ref<OutlineItem[]>([])
const assignTree = ref<AssignmentNode[]>([])
const members = ref<ProjectMember[]>([])
const draftAssignees = ref<Record<string, string | undefined>>({})
const assigning = ref(false)

// 筛选
const filterAssignee = ref<string | undefined>(undefined)

const isOwner = computed(() => isProjectOwner(projectOwnerId.value))

// 分配表格列
const assignColumns = [
  { title: '章节', key: 'chapter', dataIndex: 'chapter_no' },
  { title: '负责人', key: 'assignee', width: 220 },
  { title: '状态', key: 'status', width: 120 },
]

/** 分配表格行：以大纲章/节为主干，按 chapter_no 合并已有分工数据 */
interface AssignRow {
  chapter_no: string
  title: string
  id?: string
  assignee_id?: string
  assignee_name?: string
  status?: TaskStatus | string
  children?: AssignRow[]
}

const memberOptions = computed(() =>
  members.value.map((m) => ({
    value: m.user_id,
    label: m.display_name ? `${m.display_name}（${m.email}）` : m.email,
  })),
)

const filterMember = (input: string, option: { label: string }) =>
  option.label.toLowerCase().includes(input.toLowerCase())

/** 分工树递归拍平：章行 + 子节 children */
const flattenAssignmentNodes = (nodes: AssignmentNode[]): AssignmentNode[] =>
  nodes.flatMap((n) => [n, ...(n.children?.length ? flattenAssignmentNodes(n.children) : [])])

/** 大纲子节标题：字符串（LLM 原始）或 { title } 对象（编辑产物） */
const sectionTitleOf = (section: OutlineSection): string =>
  typeof section === 'string' ? section : section.title

/**
 * 分配表格数据源：以大纲章行为主干（章行 + 子节行），按 chapter_no 合并已有分工。
 * chapter-assignments 仅返回已分配章节，无分工记录时须以大纲为主干，owner 才能首次分配；
 * 大纲外的孤儿分工记录追加末尾（容错脏数据）。
 */
const assignRows = computed<AssignRow[]>(() => {
  const flat = flattenAssignmentNodes(assignTree.value)
  const byNo = new Map(flat.map((n) => [n.chapter_no, n]))
  const rows: AssignRow[] = []
  const pushed = new Set<string>()

  const mergeFrom = (no: string, title: string): AssignRow => {
    const a = byNo.get(no)
    return {
      chapter_no: no,
      title,
      id: a?.id ?? undefined,
      assignee_id: a?.assignee_id ?? undefined,
      assignee_name: a?.assignee_name ?? undefined,
      status: a?.status ?? undefined,
    }
  }

  const pushChapter = (chapterNo: string, title: string, sections: OutlineSection[]) => {
    const row = mergeFrom(chapterNo, title)
    // 子节编号规则与大纲树一致：`${chapter_no}.${i+1}`
    const children = sections.map((s, i) => mergeFrom(`${chapterNo}.${i + 1}`, sectionTitleOf(s)))
    const covered = new Set(children.map((c) => c.chapter_no))
    // 追加大纲子节未覆盖的节级分工记录（编号超出大纲范围的历史分工）
    flat.forEach((a) => {
      if (a.chapter_no.startsWith(`${chapterNo}.`) && !covered.has(a.chapter_no)) {
        children.push(mergeFrom(a.chapter_no, a.title))
        covered.add(a.chapter_no)
      }
    })
    row.children = children.length ? children : undefined
    rows.push(row)
    pushed.add(chapterNo)
    children.forEach((c) => pushed.add(c.chapter_no))
  }

  // 主干：大纲章行
  outline.value.forEach((c) => pushChapter(c.chapter_no, c.title, c.sections ?? []))

  // 孤儿分工记录（不在大纲内）：追加为顶层行
  assignTree.value.forEach((node) => {
    if (pushed.has(node.chapter_no)) return
    // 子节级记录若父章已展示，则已并入其 children，不再重复提升为顶层
    if (node.chapter_no.includes('.') && pushed.has(node.chapter_no.split('.')[0])) return
    const row = mergeFrom(node.chapter_no, node.title)
    const children = (node.children ?? []).map((c) => mergeFrom(c.chapter_no, c.title))
    row.children = children.length ? children : undefined
    rows.push(row)
    pushed.add(node.chapter_no)
    children.forEach((c) => pushed.add(c.chapter_no))
  })

  return rows
})

/** 可分配行：章行 + 其子节行（粒度与树形接口一致） */
const assignableRows = computed<AssignRow[]>(() =>
  assignRows.value.flatMap((row) => [row, ...(row.children?.length ? row.children : [])]),
)

/** 待推送的变更条目：草稿与已推送值不一致且非空 */
const changedItems = computed(() =>
  assignableRows.value.filter((row) => {
    const next = draftAssignees.value[row.chapter_no]
    return !!next && next !== row.assignee_id
  }),
)
const changedCount = computed(() => changedItems.value.length)

const assigneeFilterOptions = computed(() => {
  const map = new Map<string, string>()
  items.value.forEach((item) => {
    if (item.assignee_id && item.assignee_name) {
      map.set(item.assignee_id, item.assignee_name)
    }
  })
  return Array.from(map.entries()).map(([value, label]) => ({ value, label }))
})

const filteredItems = computed(() => {
  // 项目成员（非 owner）：只看属于自己的任务
  if (!isOwner.value) {
    return items.value.filter((item) => item.assignee_id === currentUserId.value)
  }
  // owner：按筛选人过滤，未筛选时显示全部
  if (!filterAssignee.value) return items.value
  return items.value.filter((item) => item.assignee_id === filterAssignee.value)
})

const myTaskCount = computed(() =>
  items.value.filter(
    (item) => item.assignee_id === currentUserId.value && item.status !== 'approved',
  ).length,
)

/** 已审核通过的章节数（>0 时允许进入审阅） */
const approvedCount = computed(
  () => items.value.filter((item) => item.status === 'approved').length,
)
/** 分工编制完成确认（resume wait_division → 进入审阅）状态 */
const confirmingDivision = ref(false)

const handleConfirmDivision = async () => {
  confirmingDivision.value = true
  try {
    await confirmDivision(projectId)
    message.success('分工编制已完成，进入审阅')
    router.push({ name: 'Review', params: { projectId } })
  } catch (err) {
    const msg = (err as { response?: { data?: { message?: string } } })?.response?.data?.message
    message.error(msg || '进入审阅失败，请确认分工编制已提交并审核')
  } finally { confirmingDivision.value = false }
}

/* ---------------- 数据加载 ---------------- */

/** 同步分配草稿基线（owner 下拉初值 = 已推送的 assignee_id） */
const syncDraftBaseline = (nodes: AssignmentNode[]) => {
  const draft: Record<string, string | undefined> = {}
  const walk = (list: AssignmentNode[]) => {
    list.forEach((node) => {
      draft[node.chapter_no] = node.assignee_id ?? undefined
      if (node.children?.length) walk(node.children)
    })
  }
  walk(nodes)
  draftAssignees.value = draft
}

const fetchAssignments = async () => {
  try {
    const { data } = await fetchChapterAssignments(projectId)
    if (data.code === 0) {
      const tree: AssignmentNode[] = data.data?.items || []
      assignTree.value = tree
      syncDraftBaseline(tree)
      // 拍平树形结构
      const flat: AssignmentItem[] = []
      const flatten = (nodes: AssignmentNode[]) => {
        nodes.forEach((node) => {
          if (node.id) {
            flat.push(node as unknown as AssignmentItem)
          }
          if (node.children?.length) flatten(node.children)
        })
      }
      flatten(tree)
      items.value = flat
    }
  } catch {
    loadError.value = '分工数据加载失败'
  }
}

/** 拉取工作流状态中的大纲（分配表格主干数据源） */
const fetchOutline = async () => {
  try {
    const { data } = await fetchWorkflowStatus(projectId)
    if (data.code === 0) {
      outline.value = data.data?.outline || []
    }
  } catch {
    // 静默失败：大纲缺失仅影响分配表格主干，由空态提示引导
  }
}

const fetchProjectOwner = async () => {
  try {
    const { data } = await fetchProject(projectId)
    if (data.code === 0) {
      projectOwnerId.value = data.data?.owner_id || ''
    }
  } catch {
    // 静默失败
  }
}

const fetchMembers = async () => {
  try {
    const { data } = await fetchProjectMembers(projectId)
    if (data.code === 0) {
      members.value = data.data?.items || []
    }
  } catch {
    // 静默失败
  }
}

const fetchAll = async () => {
  loading.value = true
  loadError.value = ''
  try {
    await Promise.all([
      fetchAssignments(),
      fetchOutline(),
      fetchProjectOwner(),
      fetchMembers(),
    ])
  } finally {
    loading.value = false
    // 全量刷新（初次加载/手动刷新）：以后端数据为基线，清空撤销历史
    kanbanHistory.reset(items.value)
  }
}

/* ---------------- 分工推送（仅 owner） ---------------- */
const handleAssign = async () => {
  const payload = changedItems.value.map((row) => ({
    chapter_no: row.chapter_no,
    title: row.title,
    assignee_id: draftAssignees.value[row.chapter_no] as string,
  }))
  if (payload.length === 0) return

  // 推送前校验：确保所有条目 chapter_no/title/assignee_id 不为空
  const invalid = payload.find((item) => !item.chapter_no || !item.title || !item.assignee_id)
  if (invalid) {
    console.error('[分工推送] 无效条目:', invalid)
    message.error(`章节「${invalid.chapter_no || '未知'}」信息不完整（标题或负责人为空），无法推送`)
    return
  }

  // 校验 assignee_id 格式是否为合法 UUID
  const uuidRegex = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i
  const invalidUuid = payload.find((item) => !uuidRegex.test(item.assignee_id))
  if (invalidUuid) {
    console.error('[分工推送] 无效 assignee_id:', invalidUuid)
    message.error(`章节「${invalidUuid.chapter_no}」的负责人ID格式错误，请重新选择负责人`)
    return
  }

  assigning.value = true
  try {
    console.log('[分工推送] 开始推送，payload:', JSON.stringify(payload, null, 2))
    // 后端幂等 upsert，响应同为树形结构
    const { data, status } = await upsertChapterAssignments(projectId, payload)
    console.log('[分工推送] 响应 status:', status, 'data:', data)
    if (data.code === 0) {
      // 推送成功后统一从后端重新加载分工列表（内部已含 syncDraftBaseline），
      // 避免 upsert 返回树与 list 接口结构不一致导致的状态不同步
      await fetchAssignments()
      message.success(`已推送 ${payload.length} 个章节的分工任务`)
    } else {
      console.error('[分工推送] 后端返回业务错误 code:', data.code, 'message:', data.message)
      const detail = `错误码: ${data.code}，消息: ${data.message || '未知错误'}`
      message.error(`分工推送失败：${detail}`, 5)
    }
  } catch (err) {
    const e = err as {
      response?: { status?: number; data?: { message?: string; code?: number } }
      message?: string
      request?: unknown
    }
    console.error('[分工推送] 请求异常:', e)
    console.error('[分工推送] 异常 response:', e?.response)
    console.error('[分工推送] 异常 request:', e?.request)

    const status = e?.response?.status
    const body = e?.response?.data
    const msg = body?.message
    const code = body?.code

    // 构建详细错误信息
    let detail = ''
    if (status) {
      detail += `HTTP状态码: ${status}\n`
    }
    if (code) {
      detail += `业务错误码: ${code}\n`
    }
    if (msg) {
      detail += `错误消息: ${msg}\n`
    }
    if (e?.message) {
      detail += `异常消息: ${e.message}\n`
    }
    if (!detail) {
      detail = '未知错误，请查看浏览器控制台日志'
    }

    // 针对常见错误码给出更友好的提示
    let friendlyMsg = '分工推送失败'
    if (code === 4004) {
      friendlyMsg = `负责人不是项目成员：${msg || '请先将该用户添加为项目成员'}`
    } else if (code === 4000) {
      friendlyMsg = `分工数据不完整：${msg || '请检查章节标题和负责人是否已填写'}`
    } else if (status === 500) {
      friendlyMsg = `服务器内部错误（500）：${msg || '请联系管理员查看后端日志'}`
    } else if (status === 401 || status === 403) {
      friendlyMsg = `权限不足（${status}）：请确认您是项目负责人且已登录`
    } else if (msg) {
      friendlyMsg = msg
    }

    // 显示错误，包含详细信息
    message.error({
      content: `${friendlyMsg}\n\n${detail}`,
      duration: 8,
    })

    // 同时在控制台输出完整的 payload 方便排查
    console.error('[分工推送] 失败时的 payload:', JSON.stringify(payload, null, 2))
  } finally {
    assigning.value = false
  }
}

/* ---------------- 看板交互 ---------------- */
/**
 * 点击任务卡片 → 跳转全屏富文本编辑器页面。
 * 本人卡片 → 可编辑模式；非本人卡片（含 owner）→ 只读模式（query param 标记）。
 */
const handleSelectTask = (item: AssignmentItem) => {
  const isMyTask = item.assignee_id === currentUserId.value
  router.push({
    name: 'ChapterEditor',
    params: { projectId, chapterNo: item.chapter_no },
    query: isMyTask ? undefined : { readonly: '1' },
  })
}

/** 拖拽移动动作描述：合法状态转换 → 对应后端接口；非法返回 null */
interface MoveAction {
  kind: 'accept' | 'submit' | 'approve' | 'reject'
  successText: string
}

const resolveMoveAction = (item: AssignmentItem, targetStatus: TaskStatus): MoveAction | null => {
  // 后端真实路由（backend/app/api/division.py）：chapter-assignments；审核统一走 review
  if (targetStatus === 'in_progress' && item.status === 'pending') {
    // 领取
    return { kind: 'accept', successText: `已领取：${item.title}` }
  }
  if (targetStatus === 'submitted' && ['in_progress', 'rejected'].includes(item.status)) {
    // 提交（含打回后修订完成再次提审：rejected → submitted）
    return { kind: 'submit', successText: `已提交：${item.title}` }
  }
  if (targetStatus === 'approved' && item.status === 'submitted') {
    // 审核通过（review 端点，body 对齐后端 ReviewBody：{ action }）
    return { kind: 'approve', successText: `已通过：${item.title}` }
  }
  if (targetStatus === 'rejected' && item.status === 'submitted') {
    // 打回（默认原因；review 端点，body 对齐后端 ReviewBody：{ action, comment }）
    return { kind: 'reject', successText: `已打回：${item.title}` }
  }
  return null
}

const handleMoveTask = async (item: AssignmentItem, targetStatus: TaskStatus) => {
  // 拖拽状态变更：根据目标状态执行对应操作
  const action = resolveMoveAction(item, targetStatus)
  if (!action) {
    message.warning('该状态转换不支持，请通过卡片按钮操作')
    return
  }
  // 变更前推快照：Ctrl+Z 可撤销（仅恢复本地视图，不回滚后端状态）
  kanbanHistory.push(items.value)
  try {
    if (action.kind === 'accept') {
      await acceptAssignment(projectId, item.id)
    } else if (action.kind === 'submit') {
      await submitAssignment(projectId, item.id)
    } else if (action.kind === 'approve') {
      await approveAssignment(projectId, item.id)
    } else {
      await rejectAssignment(projectId, item.id, '看板拖拽打回，请在编辑抽屉中查看详情')
    }
    message.success(action.successText)
    await fetchAssignments()
  } catch (err) {
    const msg = (err as { response?: { data?: { message?: string } } })?.response?.data?.message
    message.error(msg || '状态变更失败')
    await fetchAssignments() // 刷新回原状态
    // 后端数据已回滚为原状，清掉本次移动产生的过期历史，避免误撤销
    kanbanHistory.reset(items.value)
  }
}

/** 撤销：恢复移动前的本地视图（后端状态不变，刷新后以后端为准） */
const handleKanbanUndo = () => {
  if (!kanbanHistory.undo()) {
    message.info('没有可撤销的看板操作')
    return
  }
  message.success('已撤销上一步移动（仅恢复本地视图，刷新后以后端数据为准）')
}

/** 重做：恢复被撤销的移动 */
const handleKanbanRedo = () => {
  if (!kanbanHistory.redo()) {
    message.info('没有可重做的看板操作')
    return
  }
  message.success('已重做看板移动（仅恢复本地视图，刷新后以后端数据为准）')
}

/* 快捷键：看板页挂载时生效；焦点在输入控件内不触发（useHotkeys 默认行为） */
useHotkeys([
  { combo: 'ctrl+z', handler: handleKanbanUndo },
  { combo: 'ctrl+shift+z', handler: handleKanbanRedo },
  { combo: 'ctrl+y', handler: handleKanbanRedo },
])

const goToGenerate = () => {
  router.push({ name: 'Generate', params: { projectId } })
}

onMounted(() => {
  fetchAll()
  fetchCurrentUserRole()
})
</script>

<style scoped>
.division-view {
  width: 100%;
}

.division-view__assign-card {
  margin-bottom: 16px;
}

.division-view__toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 16px;
  padding: 12px 16px;
  background: var(--bg-surface);
  border: 1px solid var(--border-color);
  border-radius: var(--radius-lg);
}
</style>
