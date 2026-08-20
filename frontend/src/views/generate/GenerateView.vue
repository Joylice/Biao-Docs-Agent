<template>
  <div class="generate-view">
    <PageContainer
      title="方案生成"
      :subtitle="`进度: ${Math.round(progress * 100)}%`"
    >
      <!-- 断线重连提示 -->
      <a-alert
        v-if="wsError"
        type="warning"
        show-icon
        class="mb-4"
        :message="wsError"
      />

      <!-- 状态加载失败 -->
      <ErrorState
        v-if="loadError"
        :description="loadError"
      >
        <template #action>
          <a-button
            type="primary"
            @click="loadInitial"
          >
            重试
          </a-button>
        </template>
      </ErrorState>

      <!-- 整体进度条 -->
      <a-progress
        :percent="Math.round(progress * 100)"
        :status="progressStatus"
        class="mb-4"
      />

      <!-- 资料库挂载配置（大纲待确认时选择参与检索的文档） -->
      <a-card
        v-if="awaitingOutlineConfirm && !loadError"
        size="small"
        class="mb-4 kb-mount-card"
      >
        <template #title>
          <span class="kb-mount__title">
            <DatabaseOutlined />
            资料库挂载
          </span>
        </template>
        <template #extra>
          <a-tag
            v-if="!kbLoading && !kbError"
            color="blue"
          >
            已挂载 {{ mountedCount }} 份文档 · {{ mountedKbIds.length }} 个知识库
          </a-tag>
        </template>
        <a-alert
          v-if="kbError"
          type="warning"
          show-icon
          :message="kbError"
        />
        <LoadingSkeleton
          v-else-if="kbLoading"
          :rows="2"
        />
        <template v-else-if="kbDocs.length > 0 || kbBases.length > 0">
          <!-- 阶段 1：知识库级挂载（库内全部素材参与检索，与文档级并集生效） -->
          <div
            v-if="kbBases.length > 0"
            class="kb-mount__toolbar"
          >
            <span class="kb-mount__hint">挂载知识库：</span>
            <a-select
              v-model:value="mountedKbIds"
              mode="multiple"
              placeholder="选择知识库（库内素材全部参与检索）"
              style="min-width: 360px; flex: 1"
              allow-clear
              :max-tag-count="3"
              :options="kbBaseOptions"
            />
          </div>
          <div class="kb-mount__toolbar">
            <a-checkbox
              :checked="mountAllChecked"
              @change="onToggleMountAll"
            >
              全选
            </a-checkbox>
            <span class="kb-mount__hint">文档级细选：仅勾选的文档会参与方案生成检索（RAG）</span>
          </div>
          <a-checkbox-group
            v-model:value="mountedIds"
            class="kb-mount__list"
          >
            <a-checkbox
              v-for="doc in kbDocs"
              :key="doc.id"
              :value="doc.id"
              class="kb-mount__item"
            >
              {{ doc.title }}
            </a-checkbox>
          </a-checkbox-group>
        </template>
        <EmptyState
          v-else
          description="全局资料库暂无文档：上传公司资料后可挂载参与方案生成检索"
        >
          <template #action>
            <a-button
              type="link"
              @click="router.push({ name: 'Materials' })"
            >
              前往全局资料库
            </a-button>
          </template>
        </EmptyState>
      </a-card>

      <!-- 尚未确认评分点：引导回招标解析页（HITL 第一步） -->
      <EmptyState
        v-if="needConfirmScorePoints && !loadError"
        description="尚未确认评分点：请先在「招标解析」页确认智能解析的评分点，确认后自动生成方案大纲"
      >
        <template #action>
          <a-button
            type="primary"
            @click="router.push({ name: 'Parse', params: { projectId } })"
          >
            前往招标解析
          </a-button>
        </template>
      </EmptyState>

      <!-- 评分点已确认，大纲后台生成中：轮询等待 -->
      <a-card
        v-else-if="outlinePolling"
        class="mb-4 outline-polling-card"
      >
        <a-alert
          type="info"
          show-icon
          message="评分点已确认，方案大纲正在生成中，请稍候..."
        />
        <LoadingSkeleton
          class="outline-polling-skeleton"
          :rows="4"
        />
      </a-card>

      <EmptyState
        v-else-if="outline.length === 0 && !generating && !generated && !loadError"
        description="尚未开始生成，点击下方按钮开始生成技术方案"
      >
        <template #action>
          <a-button
            v-if="canEditOutlineNow"
            type="primary"
            :loading="generating"
            @click="handleStartGenerate"
          >
            开始生成
          </a-button>
        </template>
      </EmptyState>

      <template v-else>
        <a-layout
          class="gen-layout"
          has-sider
        >
          <!-- 章节树侧栏 -->
          <a-layout-sider
            v-model:collapsed="outlineCollapsed"
            :width="264"
            :collapsed-width="0"
            breakpoint="lg"
            theme="light"
            class="gen-sider"
          >
            <div class="gen-sider__title">
              方案大纲
              <a-tooltip :title="outlineCollapsed ? '展开大纲' : '收起大纲'">
                <a-button
                  size="small"
                  type="text"
                  @click="outlineCollapsed = !outlineCollapsed"
                >
                  <template #icon>
                    <MenuFoldOutlined v-if="!outlineCollapsed" />
                    <MenuUnfoldOutlined v-else />
                  </template>
                </a-button>
              </a-tooltip>
            </div>
            <div
              v-if="outlineCollapsed"
              class="gen-sider__collapsed-tip"
            >
              <a-button
                type="text"
                block
                @click="outlineCollapsed = false"
              >
                <template #icon>
                  <MenuUnfoldOutlined />
                </template>
              </a-button>
            </div>
            <a-tree
              v-else
              :tree-data="sideTreeData"
              :selected-keys="sideSelectedKeys"
              :default-expand-all="true"
              class="gen-outline"
              @select="onSideTreeSelect"
            >
              <!-- 生成态：节点标题后附分工信息（负责人 + 状态徽标）；确认态编辑树不加 -->
              <template #title="node">
                <span>{{ node.title }}</span>
                <template v-if="!awaitingOutlineConfirm && node.assigneeName">
                  <span class="gen-outline__assignee">{{ node.assigneeName }}</span>
                  <a-tag
                    v-if="node.assignStatus && ASSIGN_STATUS_META[node.assignStatus]"
                    class="gen-outline__tag"
                    :color="ASSIGN_STATUS_META[node.assignStatus].color"
                  >
                    {{ ASSIGN_STATUS_META[node.assignStatus].text }}
                  </a-tag>
                </template>
              </template>
            </a-tree>
          </a-layout-sider>

          <a-layout-content class="gen-content">
            <!-- 大纲已生成待确认：提示用户核对后启动生成 -->
            <a-alert
              v-if="awaitingOutlineConfirm"
              type="info"
              show-icon
              class="mb-4"
              :message="canEditOutlineNow
                ? '大纲已生成：可编辑章节标题/子节/覆盖评分点，确认后按此结构生成各章内容'
                : '大纲已生成（只读）：等待项目负责人确认大纲后按此结构生成各章内容'"
            />

            <!-- 大纲二次编辑（仅确认态）：树形编辑 → 草稿自动保存 → 确认后才进入章节生成 -->
            <a-card
              v-if="awaitingOutlineConfirm"
              class="mb-4 outline-edit-card"
              title="大纲编辑"
            >
              <template #extra>
                <a-space size="middle">
                  <a-tag color="orange">
                    待确认
                  </a-tag>
                  <a-tag
                    v-if="canEditOutlineNow && draftState !== 'idle'"
                    :color="draftTagColor"
                  >
                    {{ draftStatusText }}
                  </a-tag>
                  <a-button
                    v-if="canEditOutlineNow"
                    size="small"
                    :loading="draftState === 'saving'"
                    @click="saveDraftNow"
                  >
                    保存草稿
                  </a-button>
                  <a-button
                    v-if="canEditOutlineNow"
                    size="small"
                    type="primary"
                    :loading="generating"
                    @click="handleStartGenerate"
                  >
                    确认大纲
                  </a-button>
                </a-space>
              </template>
              <a-alert
                v-if="canEditOutlineNow"
                type="info"
                show-icon
                class="mb-4"
                message="标题编号按层级自动重算（1 / 1.1 / 1.1.1）；可增删子节、调整顺序与层级；编辑内容自动保存草稿，防刷新丢失"
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
                <template #icon>
                  <PlusOutlined />
                </template>
                添加章节
              </a-button>
            </a-card>

            <!-- AI 优化建议（仅确认态）：规则/LLM 建议 → 勾选 → 应用重建编辑树 → 最终仍走 confirm-outline -->
            <a-card
              v-if="awaitingOutlineConfirm"
              class="mb-4 outline-suggest-card"
              title="AI 优化建议"
            >
              <template #extra>
                <a-space size="middle">
                  <a-button
                    size="small"
                    :loading="outlineSuggestLoading"
                    @click="loadOutlineSuggestions"
                  >
                    <template #icon>
                      <BulbOutlined />
                    </template>
                    获取建议
                  </a-button>
                  <a-button
                    v-if="canEditOutlineNow"
                    size="small"
                    :loading="applyingSuggestions"
                    :disabled="adoptedSuggestionIds.length === 0"
                    @click="handleApplyOutlineSuggestions"
                  >
                    应用建议
                  </a-button>
                </a-space>
              </template>
              <a-empty
                v-if="outlineSuggestLoaded && outlineSuggestions.length === 0"
                description="未发现可优化项"
              />
              <a-checkbox-group
                v-else-if="outlineSuggestions.length > 0"
                v-model:value="adoptedSuggestionIds"
                class="outline-suggest__group"
              >
                <a-checkbox
                  v-for="s in outlineSuggestions"
                  :key="s.suggestion_id"
                  :value="s.suggestion_id"
                  class="outline-suggest__check"
                >
                  <div class="outline-suggest__body">
                    <div class="outline-suggest__title">
                      <a-tag :color="suggestTypeMeta[s.suggestion_type]?.color ?? 'default'">
                        {{ suggestTypeMeta[s.suggestion_type]?.label ?? s.suggestion_type }}
                      </a-tag>
                      <span>{{ s.reason }}</span>
                    </div>
                    <div class="outline-suggest__action">
                      {{ s.suggested_action }}
                    </div>
                  </div>
                </a-checkbox>
              </a-checkbox-group>
              <div
                v-else
                class="outline-suggest__hint"
              >
                点击「获取建议」，AI 将对照评分点覆盖矩阵分析大纲，给出补充/调整建议
              </div>
            </a-card>

            <!-- 草稿恢复确认（进入大纲编辑时发现未保存草稿） -->
            <a-modal
              v-model:open="draftRestoreVisible"
              title="恢复编辑草稿"
              :ok-text="'恢复草稿'"
              cancel-text="丢弃草稿"
              @ok="applyDraft"
              @cancel="discardDraft"
            >
              <p>
                检测到 {{ pendingDraftUpdatedAt }} 保存的未完成大纲编辑草稿，是否恢复继续编辑？
              </p>
            </a-modal>

            <!-- 当前章节名 + 状态徽标 -->
            <div class="gen-header">
              <a-space wrap>
                <a-tag
                  v-if="generating || generated"
                  color="blue"
                >
                  <DatabaseOutlined /> 资料库已挂载 {{ mountedCount }} 份
                </a-tag>
                <a-tag
                  v-if="currentChapter"
                  color="blue"
                >
                  生成中：章节 {{ currentChapter }}
                </a-tag>
                <a-tag
                  v-if="awaitingOutlineConfirm"
                  color="orange"
                >
                  大纲待确认
                </a-tag>
                <a-tag
                  v-else-if="generating || generated"
                  color="green"
                >
                  大纲已确认
                </a-tag>
                <a-badge
                  v-if="generating"
                  status="processing"
                  text="正在生成"
                />
                <a-badge
                  v-else-if="generated"
                  status="success"
                  text="已生成"
                />
                <a-badge
                  v-else
                  status="default"
                  text="待生成"
                />
              </a-space>
            </div>

            <!-- 章节内容（确认态被大纲编辑卡替代） -->
            <a-card
              v-if="!awaitingOutlineConfirm && selectedChapter"
              :title="`章节 ${selectedChapter}`"
              class="chapter-card"
            >
              <template #extra>
                <a-space size="small">
                  <a-button
                    v-if="canCompileSelectedChapter"
                    size="small"
                    @click="goToDivision"
                  >
                    去编制
                  </a-button>
                  <a-button
                    size="small"
                    @click="selectedChapter = ''"
                  >
                    关闭
                  </a-button>
                </a-space>
              </template>
              <MarkdownRenderer
                v-if="displayChapters[selectedChapter]"
                :source="displayChapters[selectedChapter]"
              />
              <LoadingSkeleton
                v-else
                :rows="6"
              />
            </a-card>
            <a-card
              v-if="!awaitingOutlineConfirm && !selectedChapter"
              class="chapter-card"
            >
              <EmptyState description="从左侧大纲选择章节查看内容" />
            </a-card>

            <!-- AI 改进建议（内容阶段）：建议 → 采纳重写（复用 rewrite-chapter，人工确认门禁） -->
            <a-card
              v-if="!awaitingOutlineConfirm && selectedChapter && generated"
              class="mt-4 section-suggest-card"
              size="small"
              title="AI 改进建议"
            >
              <template #extra>
                <a-button
                  size="small"
                  :loading="sectionSuggestLoading"
                  @click="loadSectionSuggestions"
                >
                  <template #icon>
                    <BulbOutlined />
                  </template>
                  获取建议
                </a-button>
              </template>
              <a-empty
                v-if="sectionSuggestLoaded && sectionSuggestions.length === 0"
                description="未发现可优化项"
              />
              <a-list
                v-else-if="sectionSuggestions.length > 0"
                size="small"
                :data-source="sectionSuggestions"
              >
                <template #renderItem="{ item }">
                  <a-list-item>
                    <a-list-item-meta>
                      <template #title>
                        <a-space size="small">
                          <a-tag :color="item.severity === 'high' ? 'red' : 'orange'">
                            {{ item.severity === 'high' ? '高优先级' : '中优先级' }}
                          </a-tag>
                          <span>章节 {{ item.chapter_no }}：{{ item.issue }}</span>
                        </a-space>
                      </template>
                      <template #description>
                        {{ item.suggestion }}
                      </template>
                    </a-list-item-meta>
                    <a-popconfirm
                      title="确认采纳该建议？将触发 AI 重写章节"
                      :ok-text="'确认重写'"
                      cancel-text="取消"
                      @confirm="handleAdoptSectionSuggestion(item)"
                    >
                      <a-button
                        size="small"
                        type="link"
                        :disabled="rewritingChapter"
                      >
                        采纳重写
                      </a-button>
                    </a-popconfirm>
                  </a-list-item>
                </template>
              </a-list>
              <div
                v-else
                class="section-suggest__hint"
              >
                点击「获取建议」，AI 将对照评分点分析章节内容，给出改进方向
              </div>
            </a-card>

            <!-- 操作按钮 -->
            <div class="actions">
              <a-popconfirm
                v-if="awaitingOutlineConfirm && !generating && !generated && canEditOutlineNow"
                title="重新生成将用最新提示词覆盖当前大纲，确认继续？"
                :ok-text="'重新生成'"
                cancel-text="取消"
                :confirm-loading="regeneratingOutline"
                @confirm="handleRegenerateOutline"
              >
                <a-button
                  :loading="regeneratingOutline"
                >
                  重新生成大纲
                </a-button>
              </a-popconfirm>
              <a-button
                v-if="!awaitingOutlineConfirm && !generating && !generated && canEditOutlineNow"
                type="primary"
                :loading="generating"
                @click="handleStartGenerate"
              >
                开始生成
              </a-button>
              <a-button
                v-if="generated"
                type="primary"
                @click="goToReview"
              >
                进入审阅
              </a-button>
            </div>
          </a-layout-content>
        </a-layout>

        <!-- 评分对标（阶段 D：大纲确认后展示；按 score × (1-coverage) 降序，owner 可编辑应对策略） -->
        <a-card
          v-if="benchmarkVisible && !loadError"
          class="mt-4 benchmark-card"
          title="评分对标"
        >
          <template #extra>
            <a-button
              v-if="benchmarkError"
              size="small"
              @click="loadBenchmark"
            >
              重试
            </a-button>
            <a-tag
              v-else-if="benchmarkLoaded && !benchmarkLoading"
              color="blue"
            >
              共 {{ benchmarkItems.length }} 项
            </a-tag>
          </template>
          <a-alert
            v-if="benchmarkError"
            type="warning"
            show-icon
            :message="benchmarkError"
          />
          <LoadingSkeleton
            v-else-if="benchmarkLoading || !benchmarkLoaded"
            :rows="5"
          />
          <a-empty
            v-else-if="benchmarkItems.length === 0"
            description="暂无已确认评分点，请先在招标解析中确认评分点"
          />
          <a-table
            v-else
            :columns="benchmarkColumns"
            :data-source="benchmarkItems"
            :pagination="false"
            :scroll="{ x: 1080 }"
            row-key="clause_no"
            size="middle"
          >
            <template #bodyCell="{ column, record }">
              <template v-if="column.key === 'coverage'">
                <a-progress
                  :percent="Math.round((record.coverage ?? 0) * 100)"
                  size="small"
                />
              </template>
              <template v-else-if="column.key === 'risk'">
                <a-tag :color="benchmarkRiskMeta[record.risk as BenchmarkRisk]?.color ?? 'default'">
                  {{ benchmarkRiskMeta[record.risk as BenchmarkRisk]?.text ?? '-' }}
                </a-tag>
              </template>
              <template v-else-if="column.key === 'strategy'">
                <a-textarea
                  v-if="canEditStrategy"
                  v-model:value="strategyDrafts[record.clause_no]"
                  :rows="2"
                  :maxlength="2000"
                  placeholder="填写应对策略，失焦自动保存"
                  :disabled="savingClause === record.clause_no"
                  @blur="handleStrategyBlur(record)"
                />
                <span
                  v-else
                  class="benchmark-strategy--readonly"
                >
                  {{ record.strategy || '—' }}
                </span>
              </template>
            </template>
          </a-table>
        </a-card>
      </template>
    </PageContainer>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, watch, nextTick, onMounted, onUnmounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { message } from 'ant-design-vue'
import { BulbOutlined, DatabaseOutlined, MenuFoldOutlined, MenuUnfoldOutlined, PlusOutlined } from '@ant-design/icons-vue'
import api from '@/api/client'
import { usePermission } from '@/composables/usePermission'
import PageContainer from '@/components/PageContainer.vue'
import EmptyState from '@/components/EmptyState.vue'
import ErrorState from '@/components/ErrorState.vue'
import LoadingSkeleton from '@/components/LoadingSkeleton.vue'
import MarkdownRenderer from '@/components/MarkdownRenderer.vue'
import OutlineTreeEditor from '@/components/outline/OutlineTreeEditor.vue'
import type { OutlineItem, OutlineSection, OutlineTreeNode } from '@/types/outline'

interface KbDocument {
  id: string
  title: string
  doc_type: string
  status: string
  created_at: string
}

interface KbBase {
  id: string
  name: string
  scope: 'personal' | 'project' | 'company'
  material_count: number
}

const route = useRoute()
const router = useRouter()
const projectId = route.params.projectId as string

/* ---------------- 权限与章节分工映射（阶段 B：大纲确认 / 去编制门禁） ---------------- */
const { isProjectOwner, canEditOutline, canEditChapter } = usePermission()
/** 项目 owner ID（项目详情返回；与 WorkspaceView/DivisionView 同源判定） */
const projectOwnerId = ref('')
/** 当前用户是否可操作大纲（确认 / 草稿 / 重新生成）：语义为项目 owner */
const canEditOutlineNow = computed(() => canEditOutline(isProjectOwner(projectOwnerId.value)))

/** 章节分工树节点（章级聚合行 id/assignee 可能为 null；子节分工在 children） */
interface AssignmentNode {
  id: string | null
  chapter_no: string
  title: string
  assignee_id: string | null
  assignee_name: string | null
  status: string | null
  children?: AssignmentNode[]
}

/** chapter_no → 分工记录（递归拍平，含子节） */
const assignmentMap = ref<Map<string, AssignmentNode>>(new Map())

/** 大纲树分工列状态徽标元信息（仅生成态展示） */
const ASSIGN_STATUS_META: Record<string, { text: string; color: string }> = {
  pending: { text: '待领取', color: 'default' },
  in_progress: { text: '编制中', color: 'processing' },
  rejected: { text: '被打回', color: 'error' },
  submitted: { text: '已提审', color: 'warning' },
  approved: { text: '已通过', color: 'success' },
}

const progress = ref(0)
const generating = ref(false)
const generated = ref(false)
const regeneratingOutline = ref(false)
const outline = ref<OutlineItem[]>([])
/** 编辑树（确认态可编辑副本）：大纲变化时重建；编辑操作直接改树并触发草稿防抖保存 */
const editedTree = ref<OutlineTreeNode[]>([])
/** 编辑区当前选中的节点（与左侧树联动） */
const activeNodeKey = ref('')
const chapters = ref<Record<string, string>>({})
const currentChapter = ref('')
const selectedChapter = ref('')
const outlineCollapsed = ref(false)
const wsError = ref('')
const loadError = ref('')

/* ---------------- 大纲二次编辑草稿（防抖自动保存 + 手动保存 + 恢复） ---------------- */
type DraftState = 'idle' | 'dirty' | 'saving' | 'saved' | 'error'
const draftState = ref<DraftState>('idle')
const draftRestoreVisible = ref(false)
const pendingDraft = ref<{
  outline: OutlineItem[]
  mounted_doc_ids: string[] | null
  mounted_kb_ids: string[] | null
} | null>(null)
const pendingDraftUpdatedAt = ref('')
/** 重建树等非用户编辑引起的变更不触发草稿保存 */
let suppressDraftWatch = false
let draftTimer: number | null = null
const DRAFT_DEBOUNCE_MS = 2000

/** 树节点本地 key（仅编辑态使用，提交时丢弃） */
let nodeKeySeed = 0
const nextNodeKey = (): string => `n${Date.now()}_${nodeKeySeed++}`

/* ---------------- 工作流状态（HITL：评分点确认 → 大纲生成 → 大纲确认） ---------------- */
const phase = ref('init')
const interruptType = ref('')
const outlinePolling = ref(false)
let outlinePollTimer: number | null = null
let outlinePollCount = 0

/** 尚未确认评分点：工作流未启动或停在评分点 interrupt → 引导回招标解析页 */
const needConfirmScorePoints = computed(
  () =>
    outline.value.length === 0 &&
    !generating.value &&
    !generated.value &&
    !outlinePolling.value &&
    (phase.value === 'init' || interruptType.value === 'confirm_score_points'),
)

/** 大纲已生成待人工确认（confirm_outline interrupt 挂起） */
const awaitingOutlineConfirm = computed(
  () => interruptType.value === 'confirm_outline' && !generating.value && !generated.value,
)

const stopOutlinePolling = () => {
  if (outlinePollTimer !== null) {
    clearInterval(outlinePollTimer)
    outlinePollTimer = null
  }
  outlinePolling.value = false
}

/* ---------------- 大纲树转换（OutlineItem[] ↔ 编辑树 OutlineTreeNode[]） ---------------- */

/** LLM 大纲 → 编辑树（sections 的 string[] 或嵌套树 → 子节点树） */
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

/** 编辑树 → 提交大纲（章节编号按位置重算 1/2/3…；sections 转嵌套树保留层级） */
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

/** 大纲就绪/变化 → 重建编辑树（抑制草稿保存；默认选中首章） */
const syncTreeFromOutline = () => {
  suppressDraftWatch = true
  editedTree.value = outlineToTree(outline.value)
  activeNodeKey.value = editedTree.value[0]?.key ?? ''
  nextTick(() => {
    suppressDraftWatch = false
  })
}

watch(outline, syncTreeFromOutline, { deep: true })

/* ---------------- 树操作（编号/层级/顺序；变更即触发草稿防抖保存） ---------------- */

/** DFS 查找节点索引路径（null = 不存在） */
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

/** 按索引路径取节点 */
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

/** 节点所在列表与下标（顶层章节列表或父节点 children） */
const nodeListAndIndex = (path: number[] | null): [OutlineTreeNode[], number] | null => {
  if (!path) return null
  const list = path.length > 1 ? nodeAt(path.slice(0, -1))?.children : editedTree.value
  if (!list) return null
  return [list, path[path.length - 1]]
}

/** 添加章节（顶层；编号提交时按位置重算） */
const handleAddChapter = () => {
  editedTree.value.push({ key: nextNodeKey(), title: '', covered_clauses: [] })
}

/** 添加子节（最深 4 级：章节/节/条/款） */
const handleAddChild = (key: string) => {
  const path = findNodePath(editedTree.value, key)
  const node = nodeAt(path)
  if (!node || !path) return
  if (path.length >= 4) {
    message.warning('最多支持 4 级层级（章节/节/条/款）')
    return
  }
  node.children = node.children ?? []
  node.children.push({ key: nextNodeKey(), title: '' })
}

/** 删除节点（含子树） */
const handleRemoveNode = (key: string) => {
  const pair = nodeListAndIndex(findNodePath(editedTree.value, key))
  if (!pair) return
  pair[0].splice(pair[1], 1)
  if (activeNodeKey.value === key) activeNodeKey.value = ''
}

/** 兄弟间上移/下移 */
const handleMoveNode = (key: string, dir: -1 | 1) => {
  const pair = nodeListAndIndex(findNodePath(editedTree.value, key))
  if (!pair) return
  const [list, idx] = pair
  const j = idx + dir
  if (j < 0 || j >= list.length) return
  const tmp = list[idx]
  list[idx] = list[j]
  list[j] = tmp
}

/** 降级：成为前一个兄弟的最后一个子节点（最深 4 级） */
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

/** 升级：移出父节点，成为父节点之后的兄弟 */
const handleDemoteNode = (key: string) => {
  const path = findNodePath(editedTree.value, key)
  if (!path || path.length <= 1) return
  const parent = nodeAt(path.slice(0, -1))
  const grand = nodeListAndIndex(path.slice(0, -1))
  if (!parent || !grand) return
  const node = parent.children!.splice(path[path.length - 1], 1)[0]
  grand[0].splice(grand[1] + 1, 0, node)
}

/** 标题实时编辑 */
const handleUpdateTitle = (key: string, title: string) => {
  const node = nodeAt(findNodePath(editedTree.value, key))
  if (node) node.title = title
}

/** 覆盖评分点：文本 → 数组存储 */
const handleUpdateClauses = (key: string, text: string) => {
  const node = nodeAt(findNodePath(editedTree.value, key))
  if (!node) return
  node.covered_clauses = text
    .split(/[,，、]/)
    .map((s) => s.trim())
    .filter(Boolean)
}

/* ---------------- 左侧大纲树（编辑态与编辑树同步；生成态展示大纲） ---------------- */

interface TreeDataItem {
  key: string
  title: string
  children?: TreeDataItem[]
  /** 分工负责人（生成态节点标题后展示） */
  assigneeName?: string
  /** 分工状态（生成态状态徽标） */
  assignStatus?: string | null
}

/** 节点附加分工信息（负责人 + 状态）；无分工 → 不附加（树节点不显示） */
const assignInfoOf = (chapterNo: string): { assigneeName?: string; assignStatus?: string | null } => {
  const a = assignmentMap.value.get(chapterNo)
  if (!a || !a.assignee_name) return {}
  return { assigneeName: a.assignee_name, assignStatus: a.status }
}

/** 编辑树 → a-tree 数据（title 前缀自动编号） */
const toEditTreeData = (nodes: OutlineTreeNode[], prefix = ''): TreeDataItem[] =>
  nodes.map((n, i) => {
    const no = prefix ? `${prefix}.${i + 1}` : `${i + 1}`
    return {
      key: n.key,
      title: `${no} ${n.title || '（未命名）'}`,
      children: n.children?.length ? toEditTreeData(n.children, no) : undefined,
    }
  })

/** 大纲 → a-tree 数据（章节 + 子节层级，key 带 ch-/sub- 前缀；附分工信息） */
const toOutlineTreeData = (items: OutlineItem[]): TreeDataItem[] =>
  items.map((c) => ({
    key: `ch-${c.chapter_no}`,
    title: `${c.chapter_no} ${c.title}`,
    ...assignInfoOf(c.chapter_no),
    children: toSectionTreeData(c.sections ?? [], c.chapter_no),
  }))

const toSectionTreeData = (sections: OutlineSection[], prefix: string): TreeDataItem[] => {
  if (!Array.isArray(sections)) return []
  return sections.map((s, i) => {
    const no = `${prefix}.${i + 1}`
    if (typeof s === 'string') {
      return { key: `sub-${no}`, title: `${no} ${s}`, ...assignInfoOf(no) }
    }
    return {
      key: `sub-${no}`,
      title: `${no} ${s.title}`,
      ...assignInfoOf(no),
      children: s.children?.length ? toSectionTreeData(s.children, no) : undefined,
    }
  })
}

const sideTreeData = computed(() =>
  awaitingOutlineConfirm.value ? toEditTreeData(editedTree.value) : toOutlineTreeData(outline.value),
)

const sideSelectedKeys = computed(() => {
  if (awaitingOutlineConfirm.value) return activeNodeKey.value ? [activeNodeKey.value] : []
  return selectedChapter.value ? [`ch-${selectedChapter.value}`] : []
})

const onSideTreeSelect = (keys: string[]) => {
  const key = keys[0]
  if (!key) return
  if (awaitingOutlineConfirm.value) {
    activeNodeKey.value = key
    document
      .querySelector(`[data-node-key="${key}"]`)
      ?.scrollIntoView({ behavior: 'smooth', block: 'center' })
    return
  }
  if (key.startsWith('ch-')) selectedChapter.value = key.slice(3)
  else if (key.startsWith('sub-')) selectedChapter.value = key.slice(4).split('.')[0]
}

const onEditSelect = (key: string) => {
  activeNodeKey.value = key
}

/* ---------------- 大纲二次编辑草稿（防抖自动保存 + 手动 + 恢复 + 确认清除） ---------------- */

const draftStatusText = computed(() => {
  switch (draftState.value) {
    case 'dirty':
      return '未保存'
    case 'saving':
      return '保存中'
    case 'saved':
      return '已自动保存'
    case 'error':
      return '保存失败'
    default:
      return ''
  }
})

const draftTagColor = computed(() => {
  switch (draftState.value) {
    case 'dirty':
      return 'warning'
    case 'saving':
      return 'processing'
    case 'saved':
      return 'green'
    case 'error':
      return 'red'
    default:
      return 'default'
  }
})

/** 编辑变化 → 防抖 2s 落库（仅确认态；重建树等程序变更被 suppressDraftWatch 抑制） */
const scheduleDraftSave = () => {
  // 草稿仅 owner 可读写（outline-draft 写接口已收紧 owner），非 owner 只读浏览不触发保存
  if (!awaitingOutlineConfirm.value || !canEditOutlineNow.value) return
  if (draftTimer !== null) clearTimeout(draftTimer)
  draftState.value = 'dirty'
  draftTimer = window.setTimeout(saveDraftNow, DRAFT_DEBOUNCE_MS)
}

const saveDraftNow = async () => {
  if (!awaitingOutlineConfirm.value) return
  if (draftTimer !== null) {
    clearTimeout(draftTimer)
    draftTimer = null
  }
  draftState.value = 'saving'
  try {
    await api.put(`/projects/${projectId}/workflow/outline-draft`, {
      outline: treeToOutline(editedTree.value),
      mounted_doc_ids: resolveMountedDocIds(),
      mounted_kb_ids: resolveMountedKbIds(),
    })
    draftState.value = 'saved'
  } catch {
    draftState.value = 'error'
  }
}

/** 清除草稿（确认成功/重新生成/丢弃恢复时调用；幂等） */
const clearDraft = async () => {
  try {
    await api.delete(`/projects/${projectId}/workflow/outline-draft`)
  } catch {
    // 幂等清除失败不影响主流程
  }
  draftState.value = 'idle'
}

/** 进入编辑态时读取历史草稿，有则弹窗询问恢复 */
const loadDraftIfAny = async () => {
  try {
    const res = await api.get(`/projects/${projectId}/workflow/outline-draft`)
    const d = res.data?.data
    if (d?.outline?.length) {
      pendingDraft.value = d
      pendingDraftUpdatedAt.value = d.updated_at
        ? new Date(d.updated_at).toLocaleString('zh-CN')
        : ''
      draftRestoreVisible.value = true
    }
  } catch {
    // 草稿读取失败不打扰编辑
  }
}

const applyDraft = () => {
  const d = pendingDraft.value
  if (!d) return
  suppressDraftWatch = true
  editedTree.value = outlineToTree(d.outline)
  if (Array.isArray(d.mounted_doc_ids)) {
    mountedIds.value = d.mounted_doc_ids
  }
  if (Array.isArray(d.mounted_kb_ids)) {
    mountedKbIds.value = d.mounted_kb_ids
  }
  nextTick(() => {
    suppressDraftWatch = false
  })
  draftRestoreVisible.value = false
  pendingDraft.value = null
  draftState.value = 'saved'
  message.success('已恢复上次未保存的编辑草稿')
}

const discardDraft = () => {
  draftRestoreVisible.value = false
  pendingDraft.value = null
  clearDraft()
}

/** 用户编辑（deep）→ 防抖保存草稿 */
watch(
  editedTree,
  () => {
    if (!suppressDraftWatch) scheduleDraftSave()
  },
  { deep: true },
)

/** 进入编辑态：读取草稿提示恢复；离开编辑态：停止未落库的防抖定时器 */
watch(awaitingOutlineConfirm, (v) => {
  if (v) {
    // 草稿恢复仅 owner（非 owner 确认态只读浏览，无草稿读写权限）
    if (canEditOutlineNow.value) loadDraftIfAny()
  } else if (draftTimer !== null) {
    clearTimeout(draftTimer)
    draftTimer = null
  }
})

/** 大纲后台生成中：每 2s 轮询 status，直到大纲就绪/异常（上限 4 分钟） */
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

/* ---------------- 资料库挂载配置（阶段 1：知识库级 + 文档级两级，并集生效） ---------------- */
const kbDocs = ref<KbDocument[]>([])
const mountedIds = ref<string[]>([])
const kbBases = ref<KbBase[]>([])
const mountedKbIds = ref<string[]>([])
const kbLoading = ref(false)
const kbError = ref('')

const scopeLabel: Record<KbBase['scope'], string> = {
  company: '公司',
  project: '项目',
  personal: '个人',
}
const kbBaseOptions = computed(() =>
  kbBases.value.map((b) => ({
    value: b.id,
    label: `${b.name}（${scopeLabel[b.scope]} · ${b.material_count} 份）`,
  })),
)

const mountedCount = computed(() => mountedIds.value.length)
const mountAllChecked = computed(
  () => kbDocs.value.length > 0 && mountedIds.value.length === kbDocs.value.length,
)

/** 挂载配置 → 草稿/提交载荷：全选或空资料库 → null（项目全量），否则勾选清单 */
const resolveMountedDocIds = (): string[] | null => {
  const mountAll = kbDocs.value.length > 0 && mountedIds.value.length === kbDocs.value.length
  return kbDocs.value.length === 0 || mountAll ? null : [...mountedIds.value]
}

/** 知识库级挂载 → 载荷：未选 → null（不参与限定），否则选中库清单 */
const resolveMountedKbIds = (): string[] | null => {
  return mountedKbIds.value.length > 0 ? [...mountedKbIds.value] : null
}

/** 挂载配置变化（编辑态）→ 防抖保存草稿 */
watch([mountedIds, mountedKbIds], () => {
  if (!suppressDraftWatch && awaitingOutlineConfirm.value) {
    scheduleDraftSave()
  }
})

const loadKbDocs = async () => {
  kbLoading.value = true
  kbError.value = ''
  try {
    // 全局资料库（独立管理）：方案生成时选择挂载
    const res = await api.get('/kb/materials', {
      params: { page_size: 100 },
    })
    const items = res.data?.data?.items ?? []
    kbDocs.value = items
    mountedIds.value = items.map((d: KbDocument) => d.id) // 默认全选
  } catch {
    kbError.value = '资料库加载失败，生成将按项目全量文档检索'
  } finally {
    kbLoading.value = false
  }
}

/** 知识库列表（项目上下文：公司库 + 本项目项目库 + 本人个人库） */
const loadKbBases = async () => {
  try {
    const res = await api.get('/kb-bases', { params: { project_id: projectId } })
    kbBases.value = res.data?.data?.items ?? []
  } catch {
    kbBases.value = []
  }
}

/** 全选/取消全选 */
const onToggleMountAll = (e: { target: { checked: boolean } }) => {
  mountedIds.value = e.target.checked ? kbDocs.value.map((d) => d.id) : []
}

const progressStatus = computed(() => {
  if (progress.value >= 1) return 'success'
  if (generating.value) return 'active'
  return 'normal'
})

/* ---------------- 章节展示（三期 S4：真流式，section_token 增量追加，去假打字机） ---------------- */
/** 每章展示内容：直接渲染 WS 增量累积的文本（section_done 全量兜底对齐） */
const displayChapters = computed(() => chapters.value)

/* ---------------- AI 优化建议（大纲确认态：规则/LLM → 勾选应用 → 重建编辑树） ---------------- */
interface OutlineSuggestion {
  suggestion_id: string
  suggestion_type: 'add_section' | 'add_chapter' | 'rename' | 'merge'
  target: Record<string, string>
  reason: string
  suggested_action: string
}

const outlineSuggestions = ref<OutlineSuggestion[]>([])
const adoptedSuggestionIds = ref<string[]>([])
const outlineSuggestLoading = ref(false)
const outlineSuggestLoaded = ref(false)
const applyingSuggestions = ref(false)

const suggestTypeMeta: Record<string, { color: string; label: string }> = {
  add_section: { color: 'blue', label: '补充小节' },
  add_chapter: { color: 'green', label: '新增章节' },
  rename: { color: 'orange', label: '修改标题' },
  merge: { color: 'purple', label: '合并章节' },
}

/** 获取大纲优化建议（瞬态数据；最终执行仍由 confirm-outline 人工确认） */
const loadOutlineSuggestions = async () => {
  outlineSuggestLoading.value = true
  try {
    const res = await api.post(`/projects/${projectId}/workflow/outline-suggest`)
    outlineSuggestions.value = res.data?.data?.suggestions ?? []
    outlineSuggestLoaded.value = true
    adoptedSuggestionIds.value = []
  } catch (err) {
    const msg = (err as { response?: { data?: { message?: string } } })?.response?.data?.message
    message.error(msg || '获取大纲优化建议失败')
  } finally {
    outlineSuggestLoading.value = false
  }
}

/** 应用建议：返回调整后大纲 → 重建编辑树（不写 state，仍需人工确认后生成） */
const handleApplyOutlineSuggestions = async () => {
  if (adoptedSuggestionIds.value.length === 0) return
  applyingSuggestions.value = true
  try {
    const res = await api.post(`/projects/${projectId}/workflow/outline-suggest/apply`, {
      adopted: adoptedSuggestionIds.value,
    })
    const newOutline = res.data?.data?.outline
    if (Array.isArray(newOutline)) {
      outline.value = newOutline // watch(outline) → syncTreeFromOutline 重建编辑树
      outlineSuggestions.value = []
      adoptedSuggestionIds.value = []
      outlineSuggestLoaded.value = false
      message.success('已生成调整后大纲，请核对后确认')
    }
  } catch (err) {
    const msg = (err as { response?: { data?: { message?: string } } })?.response?.data?.message
    message.error(msg || '应用建议失败')
  } finally {
    applyingSuggestions.value = false
  }
}

/* ---------------- AI 改进建议（内容阶段：规则/LLM → 采纳重写复用 rewrite-chapter） ---------------- */
interface SectionSuggestion {
  chapter_no: string
  issue: string
  suggestion: string
  severity: string
}

const sectionSuggestions = ref<SectionSuggestion[]>([])
const sectionSuggestLoading = ref(false)
const sectionSuggestLoaded = ref(false)
const rewritingChapter = ref(false)

/** 获取当前章节内容改进建议 */
const loadSectionSuggestions = async () => {
  sectionSuggestLoading.value = true
  try {
    const res = await api.post(`/projects/${projectId}/workflow/section-suggest`, {
      chapter_no: selectedChapter.value || undefined,
    })
    sectionSuggestions.value = res.data?.data?.suggestions ?? []
    sectionSuggestLoaded.value = true
  } catch (err) {
    const msg = (err as { response?: { data?: { message?: string } } })?.response?.data?.message
    message.error(msg || '获取内容改进建议失败')
  } finally {
    sectionSuggestLoading.value = false
  }
}

/** 采纳建议 → 触发单章 AI 重写（复用既有 rewrite-chapter 端点，同步返回新内容） */
const handleAdoptSectionSuggestion = async (item: SectionSuggestion) => {
  if (rewritingChapter.value) return
  rewritingChapter.value = true
  try {
    const res = await api.post(`/projects/${projectId}/workflow/rewrite-chapter`, null, {
      params: { chapter_no: item.chapter_no, comment: item.suggestion },
    })
    const content = res.data?.data?.content
    if (typeof content === 'string') chapters.value[item.chapter_no] = content
    message.success(`章节 ${item.chapter_no} 已按建议重写`)
  } catch (err) {
    const msg = (err as { response?: { data?: { message?: string } } })?.response?.data?.message
    message.error(msg || '章节重写失败')
  } finally {
    rewritingChapter.value = false
  }
}

/* ---------------- 评分对标（阶段 D：GET benchmark 只读对标表 + owner 应对策略失焦保存） ---------------- */
type BenchmarkRisk = 'high' | 'mid' | 'low'

/** 评分对标行（后端已按 score × (1 - coverage) 降序返回） */
interface BenchmarkItem {
  clause_no: string
  item: string
  score: number
  criteria: string
  strategy: string
  /** 素材覆盖度 0~1 */
  coverage: number
  risk: BenchmarkRisk
}

const benchmarkItems = ref<BenchmarkItem[]>([])
const benchmarkLoading = ref(false)
const benchmarkLoaded = ref(false)
const benchmarkError = ref('')
/** 应对策略编辑草稿（clause_no → 编辑值；失焦有变化才提交） */
const strategyDrafts = ref<Record<string, string>>({})
/** 正在保存策略的条款号（保存中禁用输入，防重复提交） */
const savingClause = ref('')

/** 风险标签元信息（high 红 / mid 橙 / low 灰） */
const benchmarkRiskMeta: Record<BenchmarkRisk, { text: string; color: string }> = {
  high: { text: '高', color: 'red' },
  mid: { text: '中', color: 'orange' },
  low: { text: '低', color: 'default' },
}

const benchmarkColumns = [
  { title: '条款号', dataIndex: 'clause_no', key: 'clause_no', width: 100 },
  { title: '评分项', dataIndex: 'item', key: 'item', width: 180 },
  { title: '分值', dataIndex: 'score', key: 'score', width: 70 },
  { title: '判定标准', dataIndex: 'criteria', key: 'criteria', ellipsis: { showTitle: true } },
  { title: '素材覆盖度', key: 'coverage', width: 160 },
  { title: '风险', key: 'risk', width: 80 },
  { title: '应对策略', key: 'strategy', width: 280 },
]

/** 应对策略是否可编辑（仅项目 owner；UI 门禁，后端 PUT 403 兜底） */
const canEditStrategy = computed(() => isProjectOwner(projectOwnerId.value))

/** 展示时机：大纲已确认，工作流进入 generate 及之后阶段（或本地 generating/generated 先行态） */
const benchmarkVisible = computed(
  () =>
    ['generate', 'review', 'export', 'done'].includes(phase.value) ||
    generating.value ||
    generated.value,
)

/** 拉取评分对标表（懒计算 coverage/risk；失败给提示可重试） */
const loadBenchmark = async () => {
  benchmarkLoading.value = true
  benchmarkError.value = ''
  try {
    const { data } = await api.get(`/projects/${projectId}/benchmark`)
    const items: BenchmarkItem[] = data?.data?.items ?? []
    benchmarkItems.value = items
    strategyDrafts.value = Object.fromEntries(
      items.map((it) => [it.clause_no, it.strategy ?? '']),
    )
    benchmarkLoaded.value = true
  } catch (err) {
    const msg = (err as { response?: { data?: { message?: string } } })?.response?.data?.message
    benchmarkError.value = msg || '评分对标加载失败'
  } finally {
    benchmarkLoading.value = false
  }
}

/** 应对策略失焦保存：值有变化才 PUT；失败回滚显示值（403 = 非 owner） */
const handleStrategyBlur = async (item: BenchmarkItem) => {
  const draft = (strategyDrafts.value[item.clause_no] ?? '').trim()
  if (draft === (item.strategy ?? '')) return
  savingClause.value = item.clause_no
  try {
    const res = await api.put(
      `/projects/${projectId}/benchmark/${encodeURIComponent(item.clause_no)}/strategy`,
      { strategy: draft },
    )
    const saved: string = res.data?.data?.strategy ?? draft
    item.strategy = saved
    strategyDrafts.value[item.clause_no] = saved
    message.success('应对策略已保存')
  } catch (err) {
    const status = (err as { response?: { status?: number } })?.response?.status
    const msg = (err as { response?: { data?: { message?: string } } })?.response?.data?.message
    // 保存失败：回滚显示值为已保存值，避免脏数据误导
    strategyDrafts.value[item.clause_no] = item.strategy ?? ''
    message.error(
      status === 403 ? '无权限编辑：仅项目负责人可修改应对策略' : msg || '应对策略保存失败',
    )
  } finally {
    savingClause.value = ''
  }
}

/** 进入 generate 及之后阶段 → 拉取对标表（仅拉一次；失败后可点「重试」） */
watch(
  benchmarkVisible,
  (visible) => {
    if (visible && !benchmarkLoaded.value && !benchmarkLoading.value) loadBenchmark()
  },
  { immediate: true },
)

// 当前生成章节切换 → 自动选中查看
watch(currentChapter, (no) => {
  if (no && generating.value && !selectedChapter.value) {
    selectedChapter.value = no
  }
})

/* ---------------- WebSocket 流式（三期 S4：section_token 增量 + section_done 全量兜底） ---------------- */
let ws: WebSocket | null = null
let reconnectTimer: number | null = null
let reconnectAttempts = 0

const clearReconnect = () => {
  if (reconnectTimer !== null) {
    clearTimeout(reconnectTimer)
    reconnectTimer = null
  }
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
      if (data.chapters) {
        chapters.value = data.chapters
      }
      if (data.current_chapter && generating.value && !selectedChapter.value) {
        selectedChapter.value = data.current_chapter
      }
      if (wsError.value) wsError.value = ''
    } else if (data.type === 'section_token') {
      // 真流式增量：逐块追加（展示随内容增长自然呈现，无需假打字机）
      const no = data.chapter_no
      if (no) {
        chapters.value[no] = (chapters.value[no] ?? '') + (data.delta ?? '')
        if (generating.value && !selectedChapter.value) selectedChapter.value = no
      }
    } else if (data.type === 'section_done') {
      // 全量兜底：覆盖为全文（断线重连/丢块后对齐）
      const no = data.chapter_no
      if (no && typeof data.content === 'string') {
        chapters.value[no] = data.content
      }
    } else if (data.type === 'done') {
      markGenerated()
    } else if (typeof data.type === 'string' && data.type.startsWith('task_')) {
      // 分工状态变化（领取/提审/审核）→ 刷新大纲树分工列
      fetchAssignments()
    }
  }
  ws.onclose = (event) => {
    if (event.code === 4001) {
      // 未认证：清除失效 token 并跳转登录
      clearReconnect()
      localStorage.removeItem('access_token')
      message.warning('登录已过期，请重新登录')
      router.push({ name: 'Login' })
    } else if (event.code === 4003) {
      // 非项目成员
      clearReconnect()
      generating.value = false
      message.error('无权限访问该项目')
    } else {
      // 断线自动重连（最多 3 次），并在顶部给出规范化提示
      reconnectAttempts += 1
      if (reconnectAttempts <= 3) {
        wsError.value = '连接已断开，正在自动重连...'
        reconnectTimer = window.setTimeout(() => {
          wsError.value = ''
          connectWebSocket()
        }, 3000)
      } else {
        wsError.value = '连接已断开，请刷新页面重试'
      }
    }
  }
}

/* ---------------- 生成完成兜底（WS done 事件可能丢失：连接晚于后台任务完成/断线） ---------------- */
let genPollTimer: number | null = null
let genPollCount = 0

const markGenerated = () => {
  generated.value = true
  generating.value = false
  progress.value = 1
  wsError.value = ''
  stopGenPolling()
}

const stopGenPolling = () => {
  if (genPollTimer !== null) {
    clearInterval(genPollTimer)
    genPollTimer = null
  }
}

/** 生成中每 3s 轮询 status 兜底：progress≥0.75 或 phase=review/done 即视为完成（上限 5 分钟） */
const startGenPolling = () => {
  if (genPollTimer !== null) return
  genPollTimer = window.setInterval(async () => {
    genPollCount += 1
    if (genPollCount > 100) {
      stopGenPolling()
      generating.value = false
      wsError.value = '生成状态同步超时，请刷新页面查看结果'
      return
    }
    try {
      const res = await api.get(`/projects/${projectId}/workflow/status`)
      const data = res.data?.data
      if (data?.progress >= 0.75 || ['review', 'done'].includes(data?.phase)) {
        if (data?.chapters) chapters.value = data.chapters
        markGenerated()
      }
    } catch {
      // 单次轮询失败忽略，下轮重试
    }
  }, 3000)
}

const handleRegenerateOutline = async () => {
  regeneratingOutline.value = true
  try {
    await api.post(`/projects/${projectId}/workflow/regenerate-outline`)
    message.success('大纲已重新生成')
    // 重新生成后旧编辑草稿作废：清除，防止下次误恢复
    await clearDraft()
    await loadInitial()
  } catch (err) {
    const msg = (err as { response?: { data?: { message?: string } } })?.response?.data?.message
    message.error(msg || '重新生成大纲失败')
  } finally {
    regeneratingOutline.value = false
  }
}

const handleStartGenerate = async () => {
  // 确认态提交前校验编辑树（至少 1 章、章节标题非空）
  if (awaitingOutlineConfirm.value) {
    if (editedTree.value.length === 0) {
      message.warning('大纲不能为空，请至少保留一个章节')
      return
    }
    for (const c of editedTree.value) {
      if (!c.title.trim()) {
        message.warning('章节存在空标题，请补充后再确认')
        return
      }
    }
  }
  generating.value = true
  try {
    // 挂载配置：全选或空资料库 → null（后端按项目全量检索）；否则传勾选清单（[] = 不挂载）
    const body: Record<string, unknown> = {
      mounted_doc_ids: resolveMountedDocIds(),
      mounted_kb_ids: resolveMountedKbIds(),
    }
    // 二次编辑产物：仅确认态提交（后端 resume payload 传递，不经 update_state）
    if (awaitingOutlineConfirm.value) {
      body.outline = treeToOutline(editedTree.value)
    }
    await api.post(`/projects/${projectId}/workflow/confirm-outline`, body)
    // 确认成功：清除草稿（后端 confirm 节点同步清除，此处幂等兜底）
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

/** 拉取项目详情取 owner_id（owner 判定依据；失败不阻断，后端 403 兜底） */
const fetchProjectOwner = async () => {
  try {
    const { data } = await api.get(`/projects/${projectId}`)
    if (data.code === 0) {
      projectOwnerId.value = data.data?.owner_id || ''
    }
  } catch {
    // 详情获取失败不阻断：owner 专属入口统一隐藏，后端 403 兜底
  }
}

/** 分工树递归入 map（章 "1" 与子节 "1.1" 均按 chapter_no 索引） */
const collectAssignments = (items: AssignmentNode[], map: Map<string, AssignmentNode>) => {
  for (const item of items) {
    if (item.chapter_no) map.set(item.chapter_no, item)
    if (item.children?.length) collectAssignments(item.children, map)
  }
}

/** 拉取章节分工映射（「去编制」入口 + 大纲树分工列依据） */
const fetchAssignments = async () => {
  try {
    const { data } = await api.get(`/projects/${projectId}/chapter-assignments`)
    if (data.code === 0) {
      const map = new Map<string, AssignmentNode>()
      collectAssignments(data.data?.items ?? [], map)
      assignmentMap.value = map
    }
  } catch {
    // 无分工/无权限时静默：相关入口不展示即可
  }
}

/** 当前选中章节是否可编制：项目 owner 或章节（含任一子节）assignee */
const canCompileSelectedChapter = computed(() => {
  const no = selectedChapter.value
  if (!no) return false
  const own = assignmentMap.value.get(no)
  const ids: Array<string | null> = [own?.assignee_id ?? null]
  for (const child of own?.children ?? []) ids.push(child.assignee_id)
  return canEditChapter(ids, isProjectOwner(projectOwnerId.value))
})

/** 跳转分工协作页（「去编制」入口） */
const goToDivision = () => {
  router.push({ name: 'Division', params: { projectId } })
}

const goToReview = () => {
  router.push({ name: 'Review', params: { projectId } })
}

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
      // 默认选中第一个章节
      if (!selectedChapter.value && outline.value.length > 0) {
        selectedChapter.value = outline.value[0].chapter_no
      }
    } else if (
      !generated.value &&
      phase.value !== 'init' &&
      interruptType.value !== 'confirm_score_points'
    ) {
      // 工作流已启动但大纲未就绪（后台生成中）→ 轮询等待
      startOutlinePolling()
    }
  } catch {
    loadError.value = '方案状态加载失败'
  }
}

onMounted(() => {
  loadInitial()
  loadKbDocs()
  loadKbBases()
  fetchProjectOwner()
  fetchAssignments()
})

onUnmounted(() => {
  clearReconnect()
  stopOutlinePolling()
  stopGenPolling()
  if (draftTimer !== null) {
    clearTimeout(draftTimer)
    draftTimer = null
  }
  ws?.close()
})
</script>

<style scoped>
.generate-view { max-width: 1200px; }
.mb-4 { margin-bottom: 16px; }

.gen-layout {
  background: transparent;
}

.gen-sider {
  background: var(--card-bg);
  border-radius: 8px;
  overflow: hidden;
  margin-right: 16px;
}

.gen-sider__title {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 12px 16px;
  font-weight: 600;
  border-bottom: 1px solid var(--border-color, #e8e8e8);
}

.gen-sider__collapsed-tip {
  padding: 12px;
}

.gen-outline {
  max-height: 520px;
  overflow-y: auto;
  padding: 8px;
}

.gen-content {
  background: transparent;
  min-width: 0;
}

.gen-header {
  margin-bottom: 12px;
  padding: 4px 2px;
}

.chapter-card {
  background: var(--card-bg);
  min-height: 320px;
}

.actions { display: flex; gap: 12px; justify-content: flex-end; margin-top: 24px; }

.kb-mount-card {
  background: var(--card-bg);
}

.outline-polling-card {
  background: var(--card-bg);
}

.outline-polling-skeleton {
  margin-top: 16px;
}

.kb-mount__title {
  font-size: 14px;
  font-weight: 600;
}

.kb-mount__toolbar {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 8px;
}

.kb-mount__hint {
  font-size: 12px;
  color: var(--text-secondary, #999);
}

.kb-mount__list {
  display: flex;
  flex-wrap: wrap;
  gap: 4px 24px;
  max-height: 132px;
  overflow-y: auto;
}

.kb-mount__item {
  max-width: 320px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.outline-edit-card {
  background: var(--card-bg);
}

.gen-outline__assignee {
  margin-left: 8px;
  font-size: 12px;
  color: var(--text-secondary, #999);
}

.gen-outline__tag {
  margin-left: 4px;
  padding: 0 4px;
  font-size: 11px;
  line-height: 16px;
}

.outline-suggest-card,
.section-suggest-card {
  background: var(--card-bg);
}

.outline-suggest__group {
  display: flex;
  flex-direction: column;
  gap: 8px;
  width: 100%;
}

.outline-suggest__check {
  display: flex;
  align-items: flex-start;
  padding: 8px 12px;
  border: 1px solid var(--border-color, #f0f0f0);
  border-radius: 6px;
  width: 100%;
}

.outline-suggest__body {
  margin-left: 4px;
  min-width: 0;
}

.outline-suggest__title {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 13px;
  flex-wrap: wrap;
}

.outline-suggest__action,
.section-suggest__hint {
  margin-top: 2px;
  font-size: 12px;
  color: var(--text-secondary, #999);
}

.section-suggest__hint {
  padding: 4px 0;
}

.mt-4 {
  margin-top: 16px;
}

.benchmark-card {
  background: var(--card-bg);
}

.benchmark-strategy--readonly {
  white-space: pre-wrap;
  word-break: break-word;
}
</style>
