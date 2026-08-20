<template>
  <div class="generate-view">
    <PageContainer
      title="方案大纲生成"
      :subtitle="`进度: ${Math.round(progress * 100)}%`"
    >
      <!-- 高风险废标条款预警 -->
      <a-alert
        v-if="highRiskClauseCount > 0"
        type="warning"
        show-icon
        banner
        class="generate-view__alert"
        :message="`本项目存在 ${highRiskClauseCount} 条高风险废标条款，请重点关注`"
        description="前往招标解析确认页逐条人工确认"
      />

      <!-- 断线重连提示 -->
      <a-alert v-if="wsError" type="warning" show-icon class="generate-view__alert" :message="wsError" />

      <!-- 加载失败 -->
      <ErrorState v-if="loadError" :description="loadError">
        <template #action>
          <a-button type="primary" @click="loadInitial">重试</a-button>
        </template>
      </ErrorState>

      <template v-else>
        <!-- 尚未确认评分点 -->
        <EmptyState
          v-if="needConfirmScorePoints"
          description="尚未确认评分点：请先在「招标解析」页确认智能解析的评分点"
        >
          <template #action>
            <a-button type="primary" @click="router.push({ name: 'Parse', params: { projectId } })">
              前往招标解析
            </a-button>
          </template>
        </EmptyState>

        <!-- 大纲生成中 -->
        <a-card v-else-if="outlinePolling" class="generate-view__polling">
          <a-alert type="info" show-icon message="方案大纲正在生成中，请稍候..." />
          <LoadingSkeleton class="mt-4" :rows="4" />
        </a-card>

        <!-- 主内容区：左右分栏 -->
        <template v-else-if="outline.length > 0 || generating || generated">
          <!-- 大纲待确认编辑区 -->
          <a-card v-if="awaitingOutlineConfirm" class="generate-view__outline-edit" title="大纲编辑">
            <template #extra>
              <a-space>
                <a-tag color="orange">待确认</a-tag>
                <a-tag v-if="draftState !== 'idle'" :color="draftTagColor">{{ draftStatusText }}</a-tag>
                <a-button size="small" :loading="draftState === 'saving'" @click="saveDraftNow">
                  保存草稿
                </a-button>
                <a-button size="small" type="primary" :loading="generating" @click="handleStartGenerate">
                  确认大纲
                </a-button>
              </a-space>
            </template>
            <a-alert
              type="info"
              show-icon
              message="标题编号按层级自动重算；可增删子节、调整顺序与层级；编辑内容自动保存草稿"
              class="mb-4"
            />
            <OutlineTreeEditor
              :nodes="editedTree"
              :active-key="activeNodeKey"
              :readonly="!canEditOutlineNow"
              @select="onEditSelect"
              @add-child="handleAddChild"
              @remove="handleRemoveNode"
              @move="handleMoveNode"
              @promote="handlePromoteNode"
              @demote="handleDemoteNode"
              @update-title="handleUpdateTitle"
              @update-clauses="handleUpdateClauses"
            />
            <a-button
              v-if="canEditOutlineNow"
              type="dashed"
              block
              class="mt-4"
              @click="handleAddChapter"
            >
              <template #icon><PlusOutlined /></template>
              添加章节
            </a-button>
          </a-card>

          <!-- 左右分栏：大纲树 + 章节预览/评分对标 -->
          <div v-else class="generate-view__split">
            <div class="generate-view__sider">
              <OutlinePanel
                :outline="outline"
                :selected-chapter="selectedChapter"
                :awaiting-confirm="awaitingOutlineConfirm"
                :assignment-map="assignmentMap"
                @select="selectedChapter = $event"
              />
            </div>
            <div class="generate-view__main">
              <a-tabs v-model:activeKey="activeTab" class="generate-view__tabs">
                <a-tab-pane key="preview" tab="章节预览">
                  <ChapterPreview
                    :selected-chapter="selectedChapter"
                    :current-chapter="currentChapter"
                    :display-chapters="displayChapters"
                    :progress="progress"
                    :generating="generating"
                    :generated="generated"
                    :project-id="projectId"
                    :can-go-division="canCompileSelectedChapter"
                    @close="selectedChapter = ''"
                    @go-division="goToDivision"
                  />
                </a-tab-pane>
                <a-tab-pane key="benchmark" tab="评分对标">
                  <ScoreMatchPanel
                    :items="benchmarkItems"
                    :loading="benchmarkLoading"
                    :error="benchmarkError"
                    @retry="loadBenchmark"
                  />
                </a-tab-pane>
              </a-tabs>
            </div>
          </div>

          <!-- 操作按钮 -->
          <div class="generate-view__actions">
            <a-popconfirm
              v-if="awaitingOutlineConfirm && !generating && !generated && canEditOutlineNow"
              title="重新生成将覆盖当前大纲，确认继续？"
              ok-text="重新生成"
              cancel-text="取消"
              :confirm-loading="regeneratingOutline"
              @confirm="handleRegenerateOutline"
            >
              <a-button :loading="regeneratingOutline">重新生成大纲</a-button>
            </a-popconfirm>
            <a-button
              v-if="!awaitingOutlineConfirm && !generating && !generated && canEditOutlineNow"
              type="primary"
              :loading="generating"
              @click="handleStartGenerate"
            >
              开始生成
            </a-button>
            <a-button v-if="generated" type="primary" @click="goToReview">进入审阅</a-button>
          </div>
        </template>

        <!-- 空状态 -->
        <EmptyState v-else description="尚未开始生成，点击下方按钮开始生成技术方案">
          <template #action>
            <a-button v-if="canEditOutlineNow" type="primary" :loading="generating" @click="handleStartGenerate">
              开始生成
            </a-button>
          </template>
        </EmptyState>
      </template>
    </PageContainer>

    <!-- 草稿恢复弹窗 -->
    <a-modal
      v-model:open="draftRestoreVisible"
      title="恢复编辑草稿"
      ok-text="恢复草稿"
      cancel-text="丢弃草稿"
      @ok="applyDraft"
      @cancel="discardDraft"
    >
      <p>检测到 {{ pendingDraftUpdatedAt }} 保存的未完成大纲编辑草稿，是否恢复继续编辑？</p>
    </a-modal>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, watch, nextTick, onMounted, onUnmounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { message } from 'ant-design-vue'
import { PlusOutlined } from '@ant-design/icons-vue'
import api from '@/api/client'
import { usePermission } from '@/composables/usePermission'
import PageContainer from '@/components/PageContainer.vue'
import EmptyState from '@/components/EmptyState.vue'
import ErrorState from '@/components/ErrorState.vue'
import LoadingSkeleton from '@/components/LoadingSkeleton.vue'
import OutlineTreeEditor from '@/components/outline/OutlineTreeEditor.vue'
import OutlinePanel from './components/OutlinePanel.vue'
import ChapterPreview from './components/ChapterPreview.vue'
import ScoreMatchPanel from './components/ScoreMatchPanel.vue'
import type {
  OutlineItem,
  OutlineSection,
  OutlineTreeNode,
  AssignmentNode,
  BenchmarkItem,
  DisqualificationClause,
  OutlineDraft,
} from '@/types'

const route = useRoute()
const router = useRouter()
const projectId = route.params.projectId as string

const { isProjectOwner, canEditOutline, canEditChapter } = usePermission()
const projectOwnerId = ref('')
const canEditOutlineNow = computed(() => canEditOutline(isProjectOwner(projectOwnerId.value)))

// 状态
const progress = ref(0)
const generating = ref(false)
const generated = ref(false)
const regeneratingOutline = ref(false)
const outline = ref<OutlineItem[]>([])
const editedTree = ref<OutlineTreeNode[]>([])
const activeNodeKey = ref('')
const chapters = ref<Record<string, string>>({})
const currentChapter = ref('')
const selectedChapter = ref('')
const wsError = ref('')
const loadError = ref('')
const activeTab = ref('preview')

// 分工映射
const assignmentMap = ref<Map<string, AssignmentNode>>(new Map())

// 废标条款
const disqualificationClauses = ref<DisqualificationClause[]>([])
const highRiskClauseCount = computed(
  () => disqualificationClauses.value.filter((c) => c.severity === 'high').length,
)

// 工作流状态
const phase = ref('init')
const interruptType = ref('')
const outlinePolling = ref(false)
let outlinePollTimer: number | null = null
let outlinePollCount = 0

const needConfirmScorePoints = computed(
  () =>
    outline.value.length === 0 &&
    !generating.value &&
    !generated.value &&
    !outlinePolling.value &&
    (phase.value === 'init' || interruptType.value === 'confirm_score_points'),
)

const awaitingOutlineConfirm = computed(
  () => interruptType.value === 'confirm_outline' && !generating.value && !generated.value,
)

const displayChapters = computed(() => chapters.value)

// 评分对标
const benchmarkItems = ref<BenchmarkItem[]>([])
const benchmarkLoading = ref(false)
const benchmarkLoaded = ref(false)
const benchmarkError = ref('')

const benchmarkVisible = computed(
  () =>
    ['generate', 'review', 'export', 'done'].includes(phase.value) ||
    generating.value ||
    generated.value,
)

// 草稿状态
type DraftState = 'idle' | 'dirty' | 'saving' | 'saved' | 'error'
const draftState = ref<DraftState>('idle')
const draftRestoreVisible = ref(false)
const pendingDraft = ref<OutlineDraft | null>(null)
const pendingDraftUpdatedAt = ref('')
let suppressDraftWatch = false
let draftTimer: number | null = null
const DRAFT_DEBOUNCE_MS = 2000

let nodeKeySeed = 0
const nextNodeKey = () => `n${Date.now()}_${nodeKeySeed++}`

const draftStatusText = computed(() => {
  const map: Record<DraftState, string> = {
    idle: '', dirty: '未保存', saving: '保存中', saved: '已自动保存', error: '保存失败',
  }
  return map[draftState.value]
})

const draftTagColor = computed(() => {
  const map: Record<DraftState, string> = {
    idle: 'default', dirty: 'warning', saving: 'processing', saved: 'green', error: 'red',
  }
  return map[draftState.value]
})

// WebSocket
let ws: WebSocket | null = null
let reconnectTimer: number | null = null
let reconnectAttempts = 0
let genPollTimer: number | null = null
let genPollCount = 0

/* ---------------- 大纲树转换 ---------------- */
const outlineToTree = (items: OutlineItem[]): OutlineTreeNode[] =>
  items.map((c) => ({
    key: nextNodeKey(),
    title: c.title,
    covered_clauses: [...(c.covered_clauses ?? [])],
    children: sectionsToTree(c.sections),
  }))

const sectionsToTree = (sections?: OutlineSection[]): OutlineTreeNode[] => {
  if (!Array.isArray(sections)) return []
  return sections.map((s) =>
    typeof s === 'string'
      ? { key: nextNodeKey(), title: s }
      : { key: nextNodeKey(), title: s.title, children: sectionsToTree(s.children) },
  )
}

const treeToOutline = (nodes: OutlineTreeNode[]): OutlineItem[] =>
  nodes.map((n, i) => ({
    chapter_no: String(i + 1),
    title: n.title.trim(),
    sections: treeToSections(n.children),
    covered_clauses: n.covered_clauses?.length ? n.covered_clauses : undefined,
  }))

const treeToSections = (nodes?: OutlineTreeNode[]): OutlineSection[] | undefined => {
  if (!nodes?.length) return undefined
  return nodes.map((n) => {
    const children = treeToSections(n.children)
    return children?.length ? { title: n.title.trim(), children } : { title: n.title.trim() }
  })
}

const syncTreeFromOutline = () => {
  suppressDraftWatch = true
  editedTree.value = outlineToTree(outline.value)
  activeNodeKey.value = editedTree.value[0]?.key ?? ''
  nextTick(() => { suppressDraftWatch = false })
}

watch(outline, syncTreeFromOutline, { deep: true })

/* ---------------- 树操作 ---------------- */
const findNodePath = (nodes: OutlineTreeNode[], key: string): number[] | null => {
  for (let i = 0; i < nodes.length; i += 1) {
    if (nodes[i].key === key) return [i]
    if (nodes[i].children?.length) {
      const found = findNodePath(nodes[i].children!, key)
      if (found) return [i, ...found]
    }
  }
  return null
}

const nodeAt = (path: number[] | null): OutlineTreeNode | null => {
  if (!path) return null
  let nodes: OutlineTreeNode[] = editedTree.value
  let cur: OutlineTreeNode | null = null
  for (const i of path) {
    cur = nodes[i]
    if (!cur) return null
    nodes = cur.children ?? []
  }
  return cur
}

const nodeListAndIndex = (path: number[] | null): [OutlineTreeNode[], number] | null => {
  if (!path) return null
  const list = path.length > 1 ? nodeAt(path.slice(0, -1))?.children : editedTree.value
  if (!list) return null
  return [list, path[path.length - 1]]
}

const handleAddChapter = () => {
  editedTree.value.push({ key: nextNodeKey(), title: '', covered_clauses: [] })
}

const handleAddChild = (key: string) => {
  const path = findNodePath(editedTree.value, key)
  const node = nodeAt(path)
  if (!node || !path) return
  if (path.length >= 4) { message.warning('最多支持 4 级层级'); return }
  node.children = node.children ?? []
  node.children.push({ key: nextNodeKey(), title: '' })
}

const handleRemoveNode = (key: string) => {
  const pair = nodeListAndIndex(findNodePath(editedTree.value, key))
  if (!pair) return
  pair[0].splice(pair[1], 1)
  if (activeNodeKey.value === key) activeNodeKey.value = ''
}

const handleMoveNode = (key: string, dir: -1 | 1) => {
  const pair = nodeListAndIndex(findNodePath(editedTree.value, key))
  if (!pair) return
  const [list, idx] = pair
  const j = idx + dir
  if (j < 0 || j >= list.length) return
  const tmp = list[idx]; list[idx] = list[j]; list[j] = tmp
}

const handlePromoteNode = (key: string) => {
  const path = findNodePath(editedTree.value, key)
  if (!path || path.length >= 4) return
  const pair = nodeListAndIndex(path)
  if (!pair || pair[1] === 0) return
  const [list, idx] = pair
  const prev = list[idx - 1]
  prev.children = prev.children ?? []
  prev.children.push(list[idx])
  list.splice(idx, 1)
}

const handleDemoteNode = (key: string) => {
  const path = findNodePath(editedTree.value, key)
  if (!path || path.length <= 1) return
  const parent = nodeAt(path.slice(0, -1))
  const grand = nodeListAndIndex(path.slice(0, -1))
  if (!parent || !grand) return
  const node = parent.children!.splice(path[path.length - 1], 1)[0]
  grand[0].splice(grand[1] + 1, 0, node)
}

const handleUpdateTitle = (key: string, title: string) => {
  const node = nodeAt(findNodePath(editedTree.value, key))
  if (node) node.title = title
}

const handleUpdateClauses = (key: string, text: string) => {
  const node = nodeAt(findNodePath(editedTree.value, key))
  if (!node) return
  node.covered_clauses = text.split(/[,，、]/).map((s) => s.trim()).filter(Boolean)
}

const onEditSelect = (key: string) => { activeNodeKey.value = key }

/* ---------------- 草稿保存 ---------------- */
const scheduleDraftSave = () => {
  if (!awaitingOutlineConfirm.value || !canEditOutlineNow.value) return
  if (draftTimer !== null) clearTimeout(draftTimer)
  draftState.value = 'dirty'
  draftTimer = window.setTimeout(saveDraftNow, DRAFT_DEBOUNCE_MS)
}

const saveDraftNow = async () => {
  if (!awaitingOutlineConfirm.value) return
  if (draftTimer !== null) { clearTimeout(draftTimer); draftTimer = null }
  draftState.value = 'saving'
  try {
    await api.put(`/projects/${projectId}/workflow/outline-draft`, {
      outline: treeToOutline(editedTree.value),
      mounted_doc_ids: null,
      mounted_kb_ids: null,
    })
    draftState.value = 'saved'
  } catch { draftState.value = 'error' }
}

const clearDraft = async () => {
  try { await api.delete(`/projects/${projectId}/workflow/outline-draft`) } catch { /* 幂等 */ }
  draftState.value = 'idle'
}

const loadDraftIfAny = async () => {
  try {
    const res = await api.get(`/projects/${projectId}/workflow/outline-draft`)
    const d = res.data?.data
    if (d?.outline?.length) {
      pendingDraft.value = d
      pendingDraftUpdatedAt.value = d.updated_at ? new Date(d.updated_at).toLocaleString('zh-CN') : ''
      draftRestoreVisible.value = true
    }
  } catch { /* 静默 */ }
}

const applyDraft = () => {
  const d = pendingDraft.value
  if (!d) return
  suppressDraftWatch = true
  editedTree.value = outlineToTree(d.outline)
  nextTick(() => { suppressDraftWatch = false })
  draftRestoreVisible.value = false
  pendingDraft.value = null
  draftState.value = 'saved'
  message.success('已恢复编辑草稿')
}

const discardDraft = () => {
  draftRestoreVisible.value = false
  pendingDraft.value = null
  clearDraft()
}

watch(editedTree, () => { if (!suppressDraftWatch) scheduleDraftSave() }, { deep: true })

watch(
  [awaitingOutlineConfirm, canEditOutlineNow],
  ([awaiting, canEdit], [prevAwaiting, prevCanEdit]) => {
    if (awaiting && canEdit && !(prevAwaiting && prevCanEdit) && !draftRestoreVisible.value) {
      loadDraftIfAny()
    }
    if (!awaiting && draftTimer !== null) { clearTimeout(draftTimer); draftTimer = null }
  },
)

/* ---------------- 大纲轮询 ---------------- */
const stopOutlinePolling = () => {
  if (outlinePollTimer !== null) { clearInterval(outlinePollTimer); outlinePollTimer = null }
  outlinePolling.value = false
}

const startOutlinePolling = () => {
  if (outlinePollTimer !== null) return
  outlinePolling.value = true
  outlinePollTimer = window.setInterval(async () => {
    outlinePollCount += 1
    if (outlinePollCount > 120) {
      stopOutlinePolling()
      loadError.value = '大纲生成超时，请刷新页面后重试'
      return
    }
    await loadInitial()
  }, 2000)
}

/* ---------------- 评分对标 ---------------- */
const loadBenchmark = async () => {
  benchmarkLoading.value = true
  benchmarkError.value = ''
  try {
    const { data } = await api.get(`/projects/${projectId}/benchmark`)
    benchmarkItems.value = data?.data?.items ?? []
    benchmarkLoaded.value = true
  } catch (err) {
    const msg = (err as { response?: { data?: { message?: string } } })?.response?.data?.message
    benchmarkError.value = msg || '评分对标加载失败'
  } finally { benchmarkLoading.value = false }
}

watch(
  benchmarkVisible,
  (visible) => { if (visible && !benchmarkLoaded.value && !benchmarkLoading.value) loadBenchmark() },
  { immediate: true },
)

/* ---------------- 废标条款 ---------------- */
const loadDisqualificationClauses = async () => {
  try {
    const res = await api.get(`/projects/${projectId}/disqualification-clauses`)
    disqualificationClauses.value = res.data?.data?.items || []
  } catch { disqualificationClauses.value = [] }
}

/* ---------------- 分工映射 ---------------- */
const collectAssignments = (items: AssignmentNode[], map: Map<string, AssignmentNode>) => {
  for (const item of items) {
    if (item.chapter_no) map.set(item.chapter_no, item)
    if (item.children?.length) collectAssignments(item.children, map)
  }
}

const fetchAssignments = async () => {
  try {
    const { data } = await api.get(`/projects/${projectId}/chapter-assignments`)
    if (data.code === 0) {
      const map = new Map<string, AssignmentNode>()
      collectAssignments(data.data?.items ?? [], map)
      assignmentMap.value = map
    }
  } catch { /* 静默 */ }
}

const canCompileSelectedChapter = computed(() => {
  const no = selectedChapter.value
  if (!no) return false
  const own = assignmentMap.value.get(no)
  const ids: Array<string | null> = [own?.assignee_id ?? null]
  for (const child of own?.children ?? []) ids.push(child.assignee_id)
  return canEditChapter(ids, isProjectOwner(projectOwnerId.value))
})

/* ---------------- WebSocket ---------------- */
const clearReconnect = () => {
  if (reconnectTimer !== null) { clearTimeout(reconnectTimer); reconnectTimer = null }
}

const connectWebSocket = () => {
  const protocol = window.location.protocol === 'https:' ? 'wss' : 'ws'
  const token = localStorage.getItem('access_token') || ''
  const wsUrl = `${protocol}://${window.location.host}/ws/${projectId}?token=${encodeURIComponent(token)}`
  ws = new WebSocket(wsUrl)
  ws.onmessage = (event) => {
    const data = JSON.parse(event.data)
    if (data.type === 'progress') {
      progress.value = data.progress
      currentChapter.value = data.current_chapter || ''
      if (data.chapters) chapters.value = data.chapters
      if (data.current_chapter && generating.value && !selectedChapter.value) {
        selectedChapter.value = data.current_chapter
      }
      if (wsError.value) wsError.value = ''
    } else if (data.type === 'section_token') {
      const no = data.chapter_no
      if (no) {
        chapters.value[no] = (chapters.value[no] ?? '') + (data.delta ?? '')
        if (generating.value && !selectedChapter.value) selectedChapter.value = no
      }
    } else if (data.type === 'section_done') {
      const no = data.chapter_no
      if (no && typeof data.content === 'string') chapters.value[no] = data.content
    } else if (data.type === 'done') {
      markGenerated()
    } else if (typeof data.type === 'string' && data.type.startsWith('task_')) {
      fetchAssignments()
    }
  }
  ws.onclose = (event) => {
    if (event.code === 4001) {
      clearReconnect()
      localStorage.removeItem('access_token')
      message.warning('登录已过期，请重新登录')
      router.push({ name: 'Login' })
    } else if (event.code === 4003) {
      clearReconnect()
      generating.value = false
      message.error('无权限访问该项目')
    } else {
      reconnectAttempts += 1
      if (reconnectAttempts <= 3) {
        wsError.value = '连接已断开，正在自动重连...'
        reconnectTimer = window.setTimeout(() => { wsError.value = ''; connectWebSocket() }, 3000)
      } else { wsError.value = '连接已断开，请刷新页面重试' }
    }
  }
}

const markGenerated = () => {
  generated.value = true
  generating.value = false
  progress.value = 1
  wsError.value = ''
  stopGenPolling()
}

const stopGenPolling = () => {
  if (genPollTimer !== null) { clearInterval(genPollTimer); genPollTimer = null }
}

const startGenPolling = () => {
  if (genPollTimer !== null) return
  genPollTimer = window.setInterval(async () => {
    genPollCount += 1
    if (genPollCount > 100) { stopGenPolling(); generating.value = false; wsError.value = '生成状态同步超时'; return }
    try {
      const res = await api.get(`/projects/${projectId}/workflow/status`)
      const data = res.data?.data
      if (data?.progress >= 0.75 || ['review', 'done'].includes(data?.phase)) {
        if (data?.chapters) chapters.value = data.chapters
        markGenerated()
      }
    } catch { /* 忽略 */ }
  }, 3000)
}

/* ---------------- 操作 ---------------- */
const fetchProjectOwner = async () => {
  try {
    const { data } = await api.get(`/projects/${projectId}`)
    if (data.code === 0) projectOwnerId.value = data.data?.owner_id || ''
  } catch { /* 静默 */ }
}

const handleRegenerateOutline = async () => {
  regeneratingOutline.value = true
  try {
    await api.post(`/projects/${projectId}/workflow/regenerate-outline`)
    message.success('大纲已重新生成')
    await clearDraft()
    await loadInitial()
  } catch (err) {
    const msg = (err as { response?: { data?: { message?: string } } })?.response?.data?.message
    message.error(msg || '重新生成大纲失败')
  } finally { regeneratingOutline.value = false }
}

const handleStartGenerate = async () => {
  if (awaitingOutlineConfirm.value) {
    if (editedTree.value.length === 0) { message.warning('大纲不能为空'); return }
    for (const c of editedTree.value) {
      if (!c.title.trim()) { message.warning('章节存在空标题'); return }
    }
  }
  generating.value = true
  try {
    const body: Record<string, unknown> = { mounted_doc_ids: null, mounted_kb_ids: null }
    if (awaitingOutlineConfirm.value) body.outline = treeToOutline(editedTree.value)
    await api.post(`/projects/${projectId}/workflow/confirm-outline`, body)
    clearDraft()
    reconnectAttempts = 0
    genPollCount = 0
    startGenPolling()
    connectWebSocket()
    message.info('开始生成方案...')
  } catch (err) {
    const msg = (err as { response?: { data?: { message?: string } } })?.response?.data?.message
    message.error(msg || '启动生成失败')
    generating.value = false
  }
}

const goToDivision = () => router.push({ name: 'Division', params: { projectId } })
const goToReview = () => router.push({ name: 'Review', params: { projectId } })

const loadInitial = async () => {
  loadError.value = ''
  try {
    const res = await api.get(`/projects/${projectId}/workflow/status`)
    const data = res.data?.data
    phase.value = data?.phase || 'init'
    interruptType.value = data?.interrupt?.type || ''
    if (data?.outline?.length) {
      outline.value = data.outline
      chapters.value = data.chapters || {}
      progress.value = data.progress || 0
      generated.value = progress.value >= 0.75
      stopOutlinePolling()
      if (!selectedChapter.value && outline.value.length > 0) {
        selectedChapter.value = outline.value[0].chapter_no
      }
    } else if (
      !generated.value &&
      phase.value !== 'init' &&
      interruptType.value !== 'confirm_score_points'
    ) {
      startOutlinePolling()
    }
  } catch { loadError.value = '方案状态加载失败' }
}

watch(currentChapter, (no) => {
  if (no && generating.value && !selectedChapter.value) selectedChapter.value = no
})

onMounted(() => {
  loadInitial()
  loadDisqualificationClauses()
  fetchProjectOwner()
  fetchAssignments()
})

onUnmounted(() => {
  clearReconnect()
  stopOutlinePolling()
  stopGenPolling()
  if (draftTimer !== null) { clearTimeout(draftTimer); draftTimer = null }
  ws?.close()
})
</script>

<style scoped>
.generate-view {
  width: 100%;
}

.generate-view__alert {
  margin-bottom: 16px;
}

.generate-view__polling {
  margin-bottom: 16px;
}

.generate-view__outline-edit {
  margin-bottom: 16px;
}

.generate-view__split {
  display: flex;
  gap: 16px;
  align-items: flex-start;
}

.generate-view__sider {
  width: 300px;
  flex-shrink: 0;
  position: sticky;
  top: 24px;
  max-height: calc(100vh - 120px);
}

.generate-view__main {
  flex: 1;
  min-width: 0;
}

.generate-view__tabs {
  background: var(--bg-surface);
  border: 1px solid var(--border-color);
  border-radius: var(--radius-lg);
  padding: 0 16px 16px;
}

.generate-view__actions {
  display: flex;
  gap: 12px;
  justify-content: flex-end;
  margin-top: 24px;
}

.mt-4 { margin-top: 16px; }
.mb-4 { margin-bottom: 16px; }
</style>
