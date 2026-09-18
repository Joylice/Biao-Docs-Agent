<template>
  <div class="parse-confirm">
    <PageContainer
      title="招标解析确认"
      subtitle="确认评分点，确认后生成方案大纲"
      :show-header="!embedded"
    >
      <LoadingSkeleton
        v-if="loading"
        :rows="5"
      />
      <ErrorState
        v-else-if="loadError"
        :description="loadError"
      >
        <template #action>
          <a-button
            type="primary"
            @click="fetchData"
          >
            重试
          </a-button>
        </template>
      </ErrorState>
      <EmptyState
        v-else-if="scorePoints.length === 0"
        description="暂无解析数据，请先在「招标解析」页上传招标文件"
      />

      <template v-else>
        <!-- 顶部统计 -->
        <ParseSummaryCard
          :confirmed-percent="confirmedPercent"
          :confirmed-count="confirmedCount"
          :total="scorePoints.length"
          :total-score="totalScore"
          :high-risk-count="highRiskCount"
          class="mb-4"
        />

        <!-- 招标文件区块插槽：位于统计卡与 tab 栏之间.
             招标解析页把「招标文件上传 / 文件列表」注入此处，使其落在「评分点」tab 之上
             （上传是第一步动作，不应排在页面最底部）。独立使用本组件时不渲染。 -->
        <slot name="before-tabs" />

        <!-- Tab 面板 -->
        <a-tabs
          v-model:activeKey="activeTab"
          class="parse-confirm__tabs"
        >
          <a-tab-pane
            key="score"
            tab="评分点"
          >
            <ParseScoreTable
              :score-points="scorePoints"
              :selected-row-keys="selectedRowKeys"
              :reparse-loading="reparseLoading"
              :download-tender-loading="downloadTenderLoading"
              :tender-doc="tenderDoc"
              :can-reparse="canReparse"
              @update:selected-row-keys="selectedRowKeys = $event"
              @auto-save="handleAutoSave"
              @open-batch-strategy="batchStrategyOpen = true"
              @reparse="handleReparse"
              @download-tender="handleDownloadTender"
            />
          </a-tab-pane>

          <a-tab-pane
            v-if="tenderDoc"
            key="format"
            tab="格式与术语"
          >
            <ParseFormatPanel
              :format-requirements="formatRequirements"
              :format-saving="formatSaving"
              @add-item="handleAddFormatItem"
              @remove-item="handleRemoveFormatItem"
              @save="handleSaveFormat"
            />
            <ParseGlossaryPanel
              v-if="glossaryItems.length > 0"
              :glossary="glossaryItems"
            />
          </a-tab-pane>

          <a-tab-pane
            v-if="tenderDoc"
            key="disqualification"
            tab="废标风险"
          >
            <ParseDisqualificationPanel
              :clauses="disqualificationClauses"
              :saving="disqualificationSaving"
              @checked="handleDisqualificationConfirm"
            />
          </a-tab-pane>
        </a-tabs>

        <!-- 固定底部操作栏 -->
        <div class="parse-confirm__footer">
          <div class="parse-confirm__footer-left">
            <!-- 确认进度 -->
            <div class="parse-confirm__progress">
              <span class="parse-confirm__progress-label">确认进度</span>
              <a-progress
                :percent="confirmedPercent"
                :show-info="false"
                size="small"
                class="parse-confirm__progress-bar"
              />
              <span class="parse-confirm__progress-text">
                {{ confirmedCount }} / {{ scorePoints.length }} 条
              </span>
            </div>

            <!-- 风险提示 -->
            <a-alert
              v-if="unconfirmedHighRiskCount > 0"
              type="warning"
              :show-icon="true"
              class="parse-confirm__risk-alert"
              :message="`还有 ${unconfirmedHighRiskCount} 条高分值（≥20分）评分点未确认`"
            />
            <a-alert
              v-else-if="confirmedCount === scorePoints.length && scorePoints.length > 0"
              type="success"
              :show-icon="true"
              class="parse-confirm__risk-alert"
              message="所有评分点已确认，可以生成大纲了"
            />
            <a-alert
              v-else
              type="info"
              :show-icon="true"
              class="parse-confirm__risk-alert"
              message="请先确认评分点，确认后可生成大纲"
            />
          </div>

          <div class="parse-confirm__footer-right">
            <!-- 第一步：保存确认（技术需求生成后才能点击） -->
            <a-tooltip :title="canSaveConfirm ? '保存当前所有评分点的确认状态和应对策略' : '请先确认至少一条评分点'">
              <a-button
                :loading="savingAll"
                :disabled="!canSaveConfirm"
                @click="handleSaveAll"
              >
                <template #icon>
                  <SaveOutlined />
                </template>
                保存确认
              </a-button>
            </a-tooltip>

            <!-- 第二步：生成大纲 -->
            <a-tooltip :title="canGenerate ? '确认评分点并跳转到大纲生成页面' : '请先确认至少一条评分点'">
              <a-button
                type="primary"
                :loading="confirming"
                :disabled="!canGenerate"
                @click="handleConfirm"
              >
                <template #icon>
                  <ThunderboltOutlined />
                </template>
                生成大纲
              </a-button>
            </a-tooltip>
          </div>
        </div>
      </template>
    </PageContainer>

    <!-- 批量修改策略 -->
    <a-modal
      v-model:open="batchStrategyOpen"
      title="批量修改应对策略"
      :ok-text="`应用到全部 ${scorePoints.length} 条`"
      :confirm-loading="batchStrategyLoading"
      @ok="handleApplyBatchStrategy"
    >
      <a-textarea
        v-model:value="batchStrategy"
        :rows="4"
        placeholder="输入统一的应对策略模板，将应用到所有评分点"
      />
    </a-modal>

    <!-- 批量操作浮动栏：评分点 Tab 且有勾选时浮现 -->
    <transition name="batch-bar">
      <BatchActionBar
        v-if="activeTab === 'score' && selectedRowKeys.length > 0"
        :count="selectedRowKeys.length"
        :loading="confirmAllLoading"
        :success="confirmSuccess"
        @confirm="handleConfirmAll"
        @clear="selectedRowKeys = []"
      />
    </transition>
  </div>
</template>

<script setup lang="ts">
import { useRoute, useRouter } from 'vue-router'
import { message } from 'ant-design-vue'
import { SaveOutlined, ThunderboltOutlined } from '@ant-design/icons-vue'
import {
  fetchScorePoints,
  updateScorePoint,
  downloadProjectDocument,
  reparseDocument,
  fetchDocFormatRequirements,
  saveDocFormatRequirements,
  fetchDocDisqualificationClauses,
  saveDocDisqualificationClauses,
  fetchDocGlossary,
  fetchProjectDocuments,
  fetchWorkflowStatus,
  startWorkflow,
  confirmScorePoints,
} from '@/api'
import PageContainer from '@/components/PageContainer.vue'
import EmptyState from '@/components/EmptyState.vue'
import ErrorState from '@/components/ErrorState.vue'
import LoadingSkeleton from '@/components/LoadingSkeleton.vue'
import ParseSummaryCard from './components/ParseSummaryCard.vue'
import ParseScoreTable from './components/ParseScoreTable.vue'
import ParseFormatPanel from './components/ParseFormatPanel.vue'
import ParseGlossaryPanel from './components/ParseGlossaryPanel.vue'
import ParseDisqualificationPanel from './components/ParseDisqualificationPanel.vue'
import BatchActionBar from './components/BatchActionBar.vue'
import { useParseConfirm } from './composables/useParseConfirm'

withDefaults(defineProps<{ embedded?: boolean }>(), { embedded: false })

const route = useRoute()
const router = useRouter()
const projectId = route.params.projectId as string

const {
  activeTab,
  loading,
  loadError,
  confirming,
  savingAll,
  confirmAllLoading,
  batchStrategyOpen,
  batchStrategyLoading,
  batchStrategy,
  scorePoints,
  tenderDoc,
  reparseLoading,
  selectedRowKeys,
  formatRequirements,
  formatSaving,
  disqualificationClauses,
  disqualificationSaving,
  downloadTenderLoading,
  glossaryItems,
  confirmSuccess,
  confirmedCount,
  confirmedPercent,
  totalScore,
  highRiskCount,
  unconfirmedHighRiskCount,
  canGenerate,
  canSaveConfirm,
  canReparse,
  handleAddFormatItem,
  handleRemoveFormatItem,
  handleSaveFormat,
  handleDownloadTender,
  handleDisqualificationConfirm,
  fetchData,
  handleReparse,
  handleAutoSave,
  handleConfirmAll,
  handleApplyBatchStrategy,
  handleSaveAll,
  handleConfirm,
} = useParseConfirm(projectId, {
  api: {
    fetchScorePoints,
    updateScorePoint,
    downloadProjectDocument,
    reparseDocument,
    fetchDocFormatRequirements,
    saveDocFormatRequirements,
    fetchDocDisqualificationClauses,
    saveDocDisqualificationClauses,
    fetchDocGlossary,
    fetchProjectDocuments,
    fetchWorkflowStatus,
    startWorkflow,
    confirmScorePoints,
  },
  notify: {
    error: (m) => message.error(m),
    success: (m) => message.success(m),
    warning: (m) => message.warning(m),
    info: (m) => message.info(m),
    loading: (m, d) => message.loading(m, d),
  },
  routerPush: (name, params) => router.push({ name, params }),
})
</script>

<style scoped>
.parse-confirm { width: 100%; }
.mb-4 { margin-bottom: 16px; }

.parse-confirm__tabs {
  background: var(--bg-surface);
  border-radius: var(--radius-lg);
  padding: 0 16px;
  margin-bottom: 16px;
}

.parse-confirm__actions {
  display: flex;
  gap: 12px;
  justify-content: flex-end;
  margin-top: 24px;
}

/* 固定底部操作栏 */
.parse-confirm__footer {
  position: sticky;
  bottom: 0;
  z-index: 100;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  padding: 12px 24px;
  margin-top: 24px;
  background: var(--bg-surface);
  border: 1px solid var(--border-color);
  border-radius: var(--radius-lg);
  box-shadow: 0 -4px 12px rgba(0, 0, 0, 0.08);
}

.parse-confirm__footer-left {
  display: flex;
  align-items: center;
  gap: 16px;
  flex: 1;
  min-width: 0;
}

.parse-confirm__footer-right {
  display: flex;
  align-items: center;
  gap: 12px;
  flex-shrink: 0;
}

/* 确认进度 */
.parse-confirm__progress {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-shrink: 0;
}

.parse-confirm__progress-label {
  font-size: var(--font-size-sm);
  color: var(--text-secondary);
  white-space: nowrap;
}

.parse-confirm__progress-bar {
  width: 120px;
  flex-shrink: 0;
}

.parse-confirm__progress-text {
  font-size: var(--font-size-sm);
  color: var(--text-primary);
  font-weight: 500;
  white-space: nowrap;
}

/* 风险提示 */
.parse-confirm__risk-alert {
  flex: 1;
  min-width: 0;
}

.parse-confirm__risk-alert :deep(.ant-alert-message) {
  font-size: var(--font-size-sm);
}

/* 批量操作浮动栏进入/退出过渡：淡入 + 上移（transform 需保留 translateX(-50%) 居中） */
.batch-bar-enter-active,
.batch-bar-leave-active {
  transition: opacity var(--transition-normal), transform var(--transition-normal);
}

.batch-bar-enter-from,
.batch-bar-leave-to {
  opacity: 0;
  transform: translate(-50%, 16px);
}

.batch-bar-enter-to,
.batch-bar-leave-from {
  opacity: 1;
  transform: translate(-50%, 0);
}
</style>
