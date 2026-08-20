<template>
  <div class="ote">
    <div
      v-for="(node, idx) in nodes"
      :key="node.key"
      class="ote-node"
    >
      <div
        class="ote-row"
        :class="{ 'ote-row--active': node.key === activeKey }"
        :data-node-key="node.key"
        :style="{ paddingLeft: `${level * 20}px` }"
        @click="emit('select', node.key)"
      >
        <span class="ote-no">{{ nodeNo(idx) }}</span>
        <a-input
          :value="node.title"
          class="ote-title"
          size="small"
          :readonly="readonly"
          :placeholder="isChapter ? '章节标题' : '子节标题'"
          @input="onTitleInput(node, $event)"
          @click.stop
        />
        <a-input
          v-if="isChapter"
          :value="clausesOf(node)"
          class="ote-clauses"
          size="small"
          :readonly="readonly"
          placeholder="覆盖评分点，逗号分隔"
          @input="onClausesInput(node, $event)"
          @click.stop
        />
        <a-space
          v-if="!readonly"
          class="ote-ops"
          size="2"
          @click.stop
        >
          <a-tooltip title="添加子节">
            <a-button
              size="small"
              type="text"
              aria-label="添加子节"
              :disabled="level >= maxLevel - 1"
              @click="emit('add-child', node.key)"
            >
              <template #icon>
                <PlusOutlined />
              </template>
            </a-button>
          </a-tooltip>
          <a-tooltip title="上移">
            <a-button
              size="small"
              type="text"
              aria-label="上移"
              :disabled="idx === 0"
              @click="emit('move', node.key, -1)"
            >
              <template #icon>
                <ArrowUpOutlined />
              </template>
            </a-button>
          </a-tooltip>
          <a-tooltip title="下移">
            <a-button
              size="small"
              type="text"
              aria-label="下移"
              :disabled="idx === nodes.length - 1"
              @click="emit('move', node.key, 1)"
            >
              <template #icon>
                <ArrowDownOutlined />
              </template>
            </a-button>
          </a-tooltip>
          <a-tooltip title="升级（取消缩进）">
            <a-button
              v-if="!isChapter"
              size="small"
              type="text"
              aria-label="升级"
              @click="emit('demote', node.key)"
            >
              <template #icon>
                <VerticalLeftOutlined />
              </template>
            </a-button>
          </a-tooltip>
          <a-tooltip title="降级（缩进为上一项的子节）">
            <a-button
              v-if="!isChapter"
              size="small"
              type="text"
              aria-label="降级"
              :disabled="idx === 0 || level >= maxLevel - 1"
              @click="emit('promote', node.key)"
            >
              <template #icon>
                <VerticalRightOutlined />
              </template>
            </a-button>
          </a-tooltip>
          <a-tooltip :title="isChapter ? '删除章节' : '删除子节'">
            <a-button
              size="small"
              type="text"
              danger
              aria-label="删除节点"
              @click="emit('remove', node.key)"
            >
              <template #icon>
                <DeleteOutlined />
              </template>
            </a-button>
          </a-tooltip>
        </a-space>
      </div>
      <OutlineTreeEditor
        v-if="node.children && node.children.length > 0"
        :nodes="node.children"
        :active-key="activeKey"
        :level="level + 1"
        :prefix-no="nodeNo(idx)"
        :max-level="maxLevel"
        :readonly="readonly"
        @select="emit('select', $event)"
        @add-child="emit('add-child', $event)"
        @remove="emit('remove', $event)"
        @move="forwardMove"
        @promote="emit('promote', $event)"
        @demote="emit('demote', $event)"
        @update-title="forwardTitle"
        @update-clauses="forwardClauses"
      />
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import {
  ArrowDownOutlined,
  ArrowUpOutlined,
  DeleteOutlined,
  VerticalLeftOutlined,
  VerticalRightOutlined,
  PlusOutlined,
} from '@ant-design/icons-vue'
import type { OutlineTreeNode } from '@/types/outline'

/**
 * 大纲树形编辑组件（递归渲染）。
 * - 顶层为章节（编号 1/2/3…），子节点按位置推导编号（1.1 / 1.1.1…）
 * - 操作事件上抛由父组件执行（树结构在父组件持有，便于草稿联动）
 * - readonly=true 时仅只读浏览：输入框只读、隐藏全部操作按钮（非 owner 确认态用）
 */
defineOptions({ name: 'OutlineTreeEditor' })

const props = withDefaults(
  defineProps<{
    nodes: OutlineTreeNode[]
    activeKey: string
    level?: number
    prefixNo?: string
    maxLevel?: number
    /** 只读模式：禁用全部编辑控件（输入只读 + 隐藏操作按钮），递归透传子级 */
    readonly?: boolean
  }>(),
  {
    level: 0,
    prefixNo: '',
    maxLevel: 4,
    readonly: false,
  },
)

const emit = defineEmits<{
  select: [key: string]
  'add-child': [key: string]
  remove: [key: string]
  move: [key: string, dir: -1 | 1]
  promote: [key: string]
  demote: [key: string]
  'update-title': [key: string, title: string]
  'update-clauses': [key: string, text: string]
}>()

/** 子级事件转发（多参数事件按位转发，保持 emit 类型推导） */
const forwardMove = (key: string, dir: -1 | 1) => {
  emit('move', key, dir)
}

const forwardTitle = (key: string, title: string) => {
  emit('update-title', key, title)
}

const forwardClauses = (key: string, text: string) => {
  emit('update-clauses', key, text)
}

/** 顶层为章节：编号不带前缀，展示覆盖评分点 */
const isChapter = computed(() => props.level === 0)

/** 节点编号：1 / 1.1 / 1.1.1（按树位置推导，不落数据） */
const nodeNo = (idx: number): string =>
  props.level === 0 ? String(idx + 1) : `${props.prefixNo}.${idx + 1}`

/** 标题输入（实时上抛，父组件更新树并触发草稿防抖保存；只读态浏览器不触发 input） */
const onTitleInput = (node: OutlineTreeNode, e: Event) => {
  if (props.readonly) return
  emit('update-title', node.key, (e.target as HTMLInputElement).value)
}

/** 覆盖评分点展示：数组 → 顿号分隔文本 */
const clausesOf = (node: OutlineTreeNode): string =>
  (node.covered_clauses ?? []).join('、')

/** 覆盖评分点输入（文本 → 上抛由父组件拆分存储；只读态浏览器不触发 input） */
const onClausesInput = (node: OutlineTreeNode, e: Event) => {
  if (props.readonly) return
  emit('update-clauses', node.key, (e.target as HTMLInputElement).value)
}
</script>

<style scoped>
.ote-node {
  margin-bottom: var(--space-1);
}

.ote-row {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  padding: 6px var(--space-2);
  border: 1px solid var(--border-color);
  border-radius: 6px;
  cursor: pointer;
  transition: background 0.15s;
}

.ote-row:hover {
  background: var(--bg-surface-hover);
}

.ote-row--active {
  background: var(--bg-block);
  border-color: var(--color-primary);
}

.ote-no {
  flex-shrink: 0;
  min-width: 36px;
  font-weight: 600;
  font-size: 13px;
  color: var(--color-primary);
}

.ote-title {
  flex: 1;
  min-width: 0;
}

.ote-clauses {
  width: 200px;
  flex-shrink: 0;
}

.ote-ops {
  flex-shrink: 0;
}
</style>
