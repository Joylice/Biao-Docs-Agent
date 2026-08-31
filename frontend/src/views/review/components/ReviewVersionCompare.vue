<template>
  <div class="version-compare">
    <!-- 版本选择 -->
    <div class="version-compare__selector">
      <div class="version-compare__select-group">
        <span class="version-compare__select-label">版本 A（当前）</span>
        <a-select
          v-model:value="versionA"
          size="small"
          style="width: 100%"
          :options="versionOptions"
          placeholder="选择版本 A"
        />
      </div>
      <div class="version-compare__arrow">
        <SwapOutlined />
      </div>
      <div class="version-compare__select-group">
        <span class="version-compare__select-label">版本 B（历史）</span>
        <a-select
          v-model:value="versionB"
          size="small"
          style="width: 100%"
          :options="versionOptions"
          placeholder="选择版本 B"
          @change="loadAndCompare"
        />
      </div>
    </div>

    <!-- 统计信息 -->
    <div v-if="diffResult" class="version-compare__stats">
      <a-tag color="green">+{{ diffResult.added }} 行新增</a-tag>
      <a-tag color="red">-{{ diffResult.removed }} 行删除</a-tag>
      <a-tag color="blue">{{ diffResult.modified }} 处修改</a-tag>
    </div>

    <!-- 差异导航 -->
    <div v-if="diffResult && diffResult.changes.length > 0" class="version-compare__nav">
      <a-button
        size="small"
        :disabled="currentChangeIndex <= 0"
        @click="prevChange"
      >
        <UpOutlined /> 上一处
      </a-button>
      <span class="version-compare__nav-count">
        {{ currentChangeIndex + 1 }} / {{ diffResult.changes.length }}
      </span>
      <a-button
        size="small"
        :disabled="currentChangeIndex >= diffResult.changes.length - 1"
        @click="nextChange"
      >
        下一处 <DownOutlined />
      </a-button>
    </div>

    <!-- 加载状态 -->
    <div v-if="loading" class="version-compare__loading">
      <a-spin tip="正在比对版本差异..." />
    </div>

    <!-- 差异内容 -->
    <div v-else-if="diffResult" class="version-compare__content" ref="contentRef">
      <div v-if="diffResult.changes.length === 0" class="version-compare__empty">
        <a-empty description="两个版本内容完全一致" :image="Empty.PRESENTED_IMAGE_SIMPLE" />
      </div>
      <div
        v-for="(line, idx) in diffResult.lines"
        :key="idx"
        class="version-compare__line"
        :class="{
          'version-compare__line--added': line.type === 'added',
          'version-compare__line--removed': line.type === 'removed',
          'version-compare__line--context': line.type === 'context',
          'version-compare__line--active': isActiveChange(idx),
        }"
      >
        <span class="version-compare__line-num">{{ line.num }}</span>
        <span class="version-compare__line-sign">
          {{ line.type === 'added' ? '+' : line.type === 'removed' ? '-' : ' ' }}
        </span>
        <span class="version-compare__line-text">{{ line.text || '\u00A0' }}</span>
      </div>
    </div>

    <!-- 未选择版本 -->
    <div v-else class="version-compare__placeholder">
      <a-empty description="请选择版本 B 进行差异比对" :image="Empty.PRESENTED_IMAGE_SIMPLE" />
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, nextTick } from 'vue'
import { Empty } from 'ant-design-vue'
import { SwapOutlined, UpOutlined, DownOutlined } from '@ant-design/icons-vue'
import { fetchVersionContent } from '@/api'
import type { VersionItem } from '@/types'

interface DiffLine {
  type: 'added' | 'removed' | 'context'
  num: number
  text: string
}

interface DiffResult {
  lines: DiffLine[]
  changes: number[] // 变化行的索引
  added: number
  removed: number
  modified: number
}

const props = defineProps<{
  projectId: string
  versions: VersionItem[]
  currentContent: string
}>()

const versionA = ref<string>('current')
const versionB = ref<string>('')
const loading = ref(false)
const diffResult = ref<DiffResult | null>(null)
const currentChangeIndex = ref(0)
const contentRef = ref<HTMLElement | null>(null)

const versionOptions = computed(() => {
  const opts = [{ label: '当前版本', value: 'current' }]
  props.versions.forEach((v) => {
    const note = v.snapshot_note ? ` - ${v.snapshot_note}` : ''
    const auto = v.auto ? '（自动）' : ''
    opts.push({
      label: `v${v.version}${auto}${note}`,
      value: v.id,
    })
  })
  return opts
})

/** 简单行级 diff（LCS 算法） */
const lineDiff = (textA: string, textB: string): DiffResult => {
  const linesA = textA.split('\n')
  const linesB = textB.split('\n')
  const m = linesA.length
  const n = linesB.length

  // LCS DP
  const dp: number[][] = Array.from({ length: m + 1 }, () => new Array(n + 1).fill(0))
  for (let i = m - 1; i >= 0; i--) {
    for (let j = n - 1; j >= 0; j--) {
      dp[i][j] = linesA[i] === linesB[j] ? dp[i + 1][j + 1] + 1 : Math.max(dp[i + 1][j], dp[i][j + 1])
    }
  }

  // 回溯生成 diff
  const lines: DiffLine[] = []
  const changes: number[] = []
  let i = 0
  let j = 0
  let numA = 1
  let numB = 1
  let added = 0
  let removed = 0

  while (i < m && j < n) {
    if (linesA[i] === linesB[j]) {
      lines.push({ type: 'context', num: numB, text: linesA[i] })
      i++
      j++
      numA++
      numB++
    } else if (dp[i + 1][j] >= dp[i][j + 1]) {
      lines.push({ type: 'removed', num: numA, text: linesA[i] })
      changes.push(lines.length - 1)
      removed++
      i++
      numA++
    } else {
      lines.push({ type: 'added', num: numB, text: linesB[j] })
      changes.push(lines.length - 1)
      added++
      j++
      numB++
    }
  }
  while (i < m) {
    lines.push({ type: 'removed', num: numA, text: linesA[i] })
    changes.push(lines.length - 1)
    removed++
    i++
    numA++
  }
  while (j < n) {
    lines.push({ type: 'added', num: numB, text: linesB[j] })
    changes.push(lines.length - 1)
    added++
    j++
    numB++
  }

  // 统计修改（连续的 added+removed 对）
  let modified = 0
  let idx = 0
  while (idx < changes.length) {
    const line = lines[changes[idx]]
    if (line.type === 'removed' && idx + 1 < changes.length && lines[changes[idx + 1]].type === 'added') {
      modified++
      idx += 2
    } else {
      idx++
    }
  }

  return { lines, changes, added, removed, modified }
}

const getVersionContent = async (versionId: string): Promise<string> => {
  if (versionId === 'current') return props.currentContent
  const res = await fetchVersionContent(props.projectId, versionId)
  return res.data?.data?.content || ''
}

const loadAndCompare = async () => {
  if (!versionB.value) {
    diffResult.value = null
    return
  }
  loading.value = true
  try {
    const [contentA, contentB] = await Promise.all([
      getVersionContent(versionA.value),
      getVersionContent(versionB.value),
    ])
    diffResult.value = lineDiff(contentA, contentB)
    currentChangeIndex.value = 0
  } catch {
    diffResult.value = null
  } finally {
    loading.value = false
  }
}

const isActiveChange = (idx: number): boolean => {
  if (!diffResult.value) return false
  const changeIdx = diffResult.value.changes[currentChangeIndex.value]
  return changeIdx === idx
}

const scrollToChange = (idx: number) => {
  if (!contentRef.value || !diffResult.value) return
  const changeIdx = diffResult.value.changes[idx]
  const lineEl = contentRef.value.children[changeIdx] as HTMLElement
  if (lineEl) {
    lineEl.scrollIntoView({ behavior: 'smooth', block: 'center' })
  }
}

const prevChange = () => {
  if (currentChangeIndex.value > 0) {
    currentChangeIndex.value--
    nextTick(() => scrollToChange(currentChangeIndex.value))
  }
}

const nextChange = () => {
  if (diffResult.value && currentChangeIndex.value < diffResult.value.changes.length - 1) {
    currentChangeIndex.value++
    nextTick(() => scrollToChange(currentChangeIndex.value))
  }
}

defineExpose({ loadAndCompare })
</script>

<style scoped>
.version-compare {
  display: flex;
  flex-direction: column;
  gap: 12px;
  padding: 12px;
}

.version-compare__selector {
  display: flex;
  align-items: flex-end;
  gap: 8px;
}

.version-compare__select-group {
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.version-compare__select-label {
  font-size: 11px;
  color: var(--text-secondary, #999);
}

.version-compare__arrow {
  color: var(--text-tertiary, #666);
  padding-bottom: 4px;
}

.version-compare__stats {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
}

.version-compare__nav {
  display: flex;
  align-items: center;
  gap: 8px;
  justify-content: center;
}

.version-compare__nav-count {
  font-size: 12px;
  color: var(--text-secondary, #999);
  min-width: 60px;
  text-align: center;
}

.version-compare__loading {
  padding: 40px 0;
  text-align: center;
}

.version-compare__content {
  max-height: 500px;
  overflow-y: auto;
  background: var(--bg-surface, #1a1a1a);
  border-radius: 6px;
  font-family: 'Consolas', 'Monaco', monospace;
  font-size: 12px;
  line-height: 1.6;
}

.version-compare__line {
  display: flex;
  align-items: flex-start;
  padding: 1px 8px;
  white-space: pre-wrap;
  word-break: break-all;
}

.version-compare__line--added {
  background: rgba(82, 196, 26, 0.15);
}

.version-compare__line--removed {
  background: rgba(255, 77, 79, 0.15);
}

.version-compare__line--context {
  color: var(--text-tertiary, #666);
}

.version-compare__line--active {
  outline: 2px solid #1890ff;
  outline-offset: -2px;
}

.version-compare__line-num {
  width: 40px;
  flex-shrink: 0;
  text-align: right;
  color: var(--text-tertiary, #555);
  user-select: none;
  padding-right: 8px;
}

.version-compare__line-sign {
  width: 16px;
  flex-shrink: 0;
  font-weight: bold;
  user-select: none;
}

.version-compare__line--added .version-compare__line-sign {
  color: #52c41a;
}

.version-compare__line--removed .version-compare__line-sign {
  color: #ff4d4f;
}

.version-compare__line-text {
  flex: 1;
  min-width: 0;
}

.version-compare__line--added .version-compare__line-text {
  color: #95de64;
}

.version-compare__line--removed .version-compare__line-text {
  color: #ff7875;
}

.version-compare__empty,
.version-compare__placeholder {
  padding: 30px 0;
}
</style>
