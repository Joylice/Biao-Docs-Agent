<template>
  <div class="skill-panel">
    <!-- 头部：标题 + 刷新 + 导入导出 -->
    <div class="skill-panel__header">
      <div>
        <h3 class="skill-panel__title">{{ title }}</h3>
        <p class="skill-panel__desc">
          {{ desc || '行为准则（SKILL.md 契约）：内置准则只读，用户准则可增删改、启停与导入导出。' }}
        </p>
      </div>
      <a-space>
        <a-upload
          :show-upload-list="false"
          :before-upload="onImportFile"
          accept=".zip"
        >
          <a-button size="small">
            <template #icon><UploadOutlined /></template>
            导入
          </a-button>
        </a-upload>
        <a-button size="small" @click="onExport">
          <template #icon><DownloadOutlined /></template>
          导出
        </a-button>
        <a-button size="small" type="primary" @click="openCreate">
          <template #icon><PlusOutlined /></template>
          新建
        </a-button>
        <a-button size="small" :loading="loading" @click="load">
          <template #icon><ReloadOutlined /></template>
          刷新
        </a-button>
      </a-space>
    </div>

    <a-spin :spinning="loading">
      <div class="skill-panel__list">
        <div
          v-for="row in rows"
          :key="row.name"
          class="skill-card"
          :class="{ 'skill-card--off': !row.effective }"
        >
          <div class="skill-card__head">
            <span class="skill-card__name">{{ row.title }}</span>
            <code class="skill-card__key">{{ row.name }}</code>
            <a-tag class="skill-card__stage" color="blue">{{ row.stageKey }}</a-tag>
            <a-tag v-if="row.builtin" class="skill-card__src" color="purple">内置</a-tag>
            <a-tag v-else-if="row.createdBy === 'llm'" class="skill-card__src" color="orange">
              LLM 生成
            </a-tag>
            <a-tag
              v-if="!row.builtin"
              class="skill-card__state"
              :color="row.enabled ? 'green' : 'default'"
            >{{ row.enabled ? '已启用' : '已停用' }}</a-tag>
            <a-tag v-if="row.shadowsBuiltin" class="skill-card__src" color="cyan">覆盖内置</a-tag>
            <a-tag v-if="row.builtin && row.editable === false" color="red">系统固化</a-tag>
          </div>

          <p class="skill-card__desc">{{ row.description }}</p>

          <div class="skill-card__actions">
            <span v-if="!row.builtin" class="skill-card__ver">v{{ row.optimisticVersion }}</span>
            <a-switch
              v-if="!row.builtin"
              :checked="row.enabled"
              size="small"
              checked-children="启用"
              un-checked-children="停用"
              @change="(c: unknown) => onToggle(row, !!c)"
            />
            <a-button
              v-if="!row.builtin"
              size="small"
              @click="openEdit(row)"
            >编辑</a-button>
            <a-popconfirm
              v-if="row.shadowsBuiltin"
              :title="`恢复准则「${row.name}」为内置默认？覆盖行将被删除。`"
              ok-text="恢复"
              cancel-text="取消"
              @confirm="onReset(row)"
            >
              <a-button size="small">恢复内置</a-button>
            </a-popconfirm>
            <a-button
              v-if="row.builtin && row.editable !== false"
              size="small"
              @click="onPreviewBuiltin(row)"
            >查看</a-button>
            <a-button
              v-if="!row.builtin"
              size="small"
              @click="onPreview(row)"
            >预览</a-button>
            <a-popconfirm
              v-if="!row.builtin"
              :title="`删除准则「${row.title}」？`"
              ok-text="删除"
              cancel-text="取消"
              @confirm="onDelete(row)"
            >
              <a-button size="small" danger>删除</a-button>
            </a-popconfirm>
          </div>
        </div>
      </div>
      <a-empty v-if="!loading && rows.length === 0" description="暂无行为准则" />
    </a-spin>

    <!-- 新建 / 编辑 抽屉 -->
    <a-drawer
      v-model:open="editorOpen"
      :title="editingName ? `编辑准则：${editingName}` : '新建行为准则'"
      width="560"
      destroy-on-close
    >
      <a-form layout="vertical">
        <a-form-item label="名称（小写字母开头，3~64 字符）" required>
          <a-input
            v-model:value="form.name"
            :disabled="!!editingName"
            placeholder="如 my_review_rule"
          />
        </a-form-item>
        <a-form-item label="标题" required>
          <a-input v-model:value="form.title" placeholder="展示名" />
        </a-form-item>
        <a-form-item label="描述（选择契约）" required>
          <a-input v-model:value="form.description" placeholder="这条准则用于什么场景" />
        </a-form-item>
        <a-form-item label="所属阶段" required>
          <a-select v-model:value="form.stage_key" :options="stageOptions" />
        </a-form-item>
        <a-form-item required>
          <template #label>
            行为指令正文
            <span class="skill-panel__counter">
              {{ form.body_md.length }} / {{ bodyMaxChars }}
            </span>
          </template>
          <a-textarea
            v-model:value="form.body_md"
            :rows="12"
            :maxlength="bodyMaxChars"
            placeholder="你是……（写给模型的行为指令）"
          />
        </a-form-item>
      </a-form>
      <template #footer>
        <a-space>
          <a-button @click="editorOpen = false">取消</a-button>
          <a-button type="primary" :loading="saving" @click="onSave">
            {{ editingName ? '保存' : '创建' }}
          </a-button>
        </a-space>
      </template>
    </a-drawer>

    <!-- 预览 抽屉 -->
    <a-drawer
      v-model:open="previewOpen"
      :title="`渲染预览：${previewData?.name ?? ''}`"
      width="640"
      destroy-on-close
    >
      <template v-if="previewData">
        <a-alert
          class="skill-panel__preview-meta"
          :message="`来源：${previewData.resolvedFrom === 'registry' ? '注册表（线上契约 metadata）' : '草稿'} · system ${previewData.systemChars} 字 / user ${previewData.userChars} 字`"
          type="info"
          show-icon
        />
        <h4 class="skill-panel__preview-h">System Prompt</h4>
        <pre class="skill-panel__pre">{{ previewData.systemPrompt }}</pre>
        <h4 class="skill-panel__preview-h">User Prompt</h4>
        <pre class="skill-panel__pre">{{ previewData.userPrompt || '（空 —— 本契约不渲染数据注入区）' }}</pre>
      </template>
    </a-drawer>

    <!-- 导入回执 -->
    <a-modal
      v-model:open="importReportOpen"
      title="导入回执"
      :footer="null"
      width="520"
    >
      <ul class="skill-panel__report">
        <li v-for="item in importReport" :key="item.name">
          <a-tag :color="item.created ? 'green' : 'orange'">
            {{ item.created ? '已导入' : '未导入' }}
          </a-tag>
          <code>{{ item.name }}</code>
          <span class="skill-panel__report-msg">{{ item.message }}</span>
        </li>
      </ul>
    </a-modal>
  </div>
</template>

<script setup lang="ts">
/**
 * SkillPanel：行为准则（SKILL.md 契约）管理面板（S4）.
 *
 * 🔴 命名说明：本文件名在 S4 之前被「外部工具」面板占用（已更名
 * ToolBindingsPanel.vue）；S4 起「skill」= 行为准则资产，本面板为其专属 UI。
 *
 * 交互口径：
 * - 双源列表：内置（builtin=true）只读 —— 不渲染启停/编辑/删除；
 *   `user-invocable=false` 的内置（「系统固化」）连查看都不提供覆盖入口；
 * - 用户准则：启停/编辑/删除即时提交（乐观锁），无表单 dirty 语义
 *   → registry entry.save 为 no-op；
 * - zip 导入：后端同名不覆盖，逐条回执在弹窗中显式呈现（防静默覆盖误解）；
 * - zip 导出：默认只导用户层（内置随代码分发，导出无意义）。
 */
import { computed, onMounted, reactive, ref } from 'vue'
import {
  DownloadOutlined,
  PlusOutlined,
  ReloadOutlined,
  UploadOutlined,
} from '@ant-design/icons-vue'
import { message } from 'ant-design-vue'
import { useSkillsConfig } from '@/composables/useSkillsConfig'
import { exportSkills } from '@/api/skills'
import type { SkillImportItem, SkillPreviewResult, SkillView } from '@/api/skills'
import { getApiErrorMessage } from '@/composables/apiErrorMessage'

withDefaults(
  defineProps<{
    title?: string
    desc?: string
  }>(),
  { title: '行为准则', desc: '' },
)

const config = useSkillsConfig()
const { loading, rows, stageKeys, bodyMaxChars, load, create, update, remove, reset, importZip, preview } =
  config

/* ── 编辑器 ── */
const editorOpen = ref(false)
const saving = ref(false)
/** 非空 = 编辑既有行；空 = 新建 */
const editingName = ref<string | null>(null)
/** 编辑行的乐观锁版本（仅编辑态使用） */
const editingVersion = ref<number | null>(null)

const form = reactive({
  name: '',
  title: '',
  description: '',
  stage_key: '',
  body_md: '',
})

const stageOptions = computed(() =>
  stageKeys.value.map((k) => ({ label: k, value: k })),
)

function openCreate(): void {
  editingName.value = null
  editingVersion.value = null
  form.name = ''
  form.title = ''
  form.description = ''
  form.stage_key = stageKeys.value[0] ?? ''
  form.body_md = ''
  editorOpen.value = true
}

function openEdit(row: SkillView): void {
  editingName.value = row.name
  editingVersion.value = row.optimisticVersion
  form.name = row.name
  form.title = row.title
  form.description = row.description
  form.stage_key = row.stageKey
  form.body_md = row.bodyMd
  editorOpen.value = true
}

async function onSave(): Promise<void> {
  saving.value = true
  try {
    if (editingName.value) {
      const ok = await update(editingName.value, {
        title: form.title,
        description: form.description,
        body_md: form.body_md,
        expected_version: editingVersion.value ?? undefined,
      })
      if (ok) editorOpen.value = false
    } else {
      const ok = await create({
        name: form.name,
        title: form.title,
        description: form.description,
        stage_key: form.stage_key,
        body_md: form.body_md,
      })
      if (ok) editorOpen.value = false
    }
  } finally {
    saving.value = false
  }
}

/* ── 行内操作 ── */
async function onToggle(row: SkillView, enabled: boolean): Promise<void> {
  const ok = await config.toggleEnabled(row, enabled)
  if (!ok) await load() // 失败（如 409）→ 重新拉取对齐服务端真值
}

function onDelete(row: SkillView): void {
  void remove(row)
}

function onReset(row: SkillView): void {
  void reset(row)
}

/* ── 预览 ── */
const previewOpen = ref(false)
const previewData = ref<SkillPreviewResult | null>(null)

async function onPreview(row: SkillView): Promise<void> {
  const r = await preview(row.bodyMd, row.name)
  if (r) {
    previewData.value = r
    previewOpen.value = true
  }
}

/** 内置行「查看」= 用注册表契约渲染（body 未改动） */
function onPreviewBuiltin(row: SkillView): void {
  void onPreview(row)
}

/* ── 导入 / 导出 ── */
const importReportOpen = ref(false)
const importReport = ref<SkillImportItem[]>([])

/** before-upload 返回 false 阻止自动上传，改走手动流程 */
function onImportFile(file: File): boolean {
  void (async () => {
    const items = await importZip(file)
    if (items) {
      importReport.value = items
      importReportOpen.value = true
    }
  })()
  return false
}

async function onExport(): Promise<void> {
  try {
    const blob = await exportSkills(false)
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = 'skills.zip'
    a.click()
    URL.revokeObjectURL(url)
  } catch (error) {
    message.error(getApiErrorMessage(error, '导出失败（无用户层准则时后端拒绝导出）'))
  }
}

onMounted(load)
</script>

<style scoped>
.skill-panel {
  max-width: 760px;
}

.skill-panel__header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: var(--space-3);
  margin-bottom: var(--space-4);
  flex-wrap: wrap;
}

.skill-panel__title {
  margin: 0;
  font-size: 16px;
  font-weight: 700;
  color: var(--text-primary);
}

.skill-panel__desc {
  margin: 4px 0 0;
  font-size: 12px;
  color: var(--text-tertiary);
  line-height: 1.6;
}

.skill-panel__list {
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
}

.skill-card {
  padding: var(--space-3) var(--space-4);
  background: var(--bg-surface);
  border: 1px solid var(--border-color);
  border-radius: var(--radius-lg);
}

.skill-card--off {
  opacity: 0.6;
}

.skill-card__head {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  flex-wrap: wrap;
}

.skill-card__name {
  font-size: 13px;
  font-weight: 600;
  color: var(--text-primary);
}

.skill-card__key {
  font-size: 11px;
  color: var(--color-primary);
  background: var(--bg-muted, #f5f5f5);
  padding: 1px 6px;
  border-radius: var(--radius-sm);
}

.skill-card__src {
  font-size: 11px;
}

.skill-card__state {
  font-size: 11px;
}

.skill-card__stage {
  font-size: 11px;
}

.skill-card__desc {
  margin: 6px 0;
  font-size: 12px;
  color: var(--text-secondary, #666);
  line-height: 1.6;
}

.skill-card__actions {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  flex-wrap: wrap;
}

.skill-card__ver {
  font-size: 11px;
  color: var(--text-tertiary);
}

.skill-panel__counter {
  margin-left: 8px;
  font-size: 11px;
  color: var(--text-tertiary);
  font-weight: 400;
}

.skill-panel__preview-meta {
  margin-bottom: 12px;
}

.skill-panel__preview-h {
  margin: 12px 0 6px;
  font-size: 13px;
  color: var(--text-primary);
}

.skill-panel__pre {
  margin: 0;
  padding: 10px;
  max-height: 320px;
  overflow: auto;
  font-size: 12px;
  line-height: 1.6;
  background: var(--bg-muted, #f7f7f7);
  border: 1px solid var(--border-color);
  border-radius: var(--radius-sm);
  white-space: pre-wrap;
  word-break: break-word;
}

.skill-panel__report {
  margin: 0;
  padding: 0;
  list-style: none;
}

.skill-panel__report li {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 6px 0;
  border-bottom: 1px dashed var(--border-color);
}

.skill-panel__report li:last-child {
  border-bottom: none;
}

.skill-panel__report-msg {
  font-size: 12px;
  color: var(--text-tertiary);
}
</style>
