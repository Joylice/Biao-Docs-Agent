<template>
  <a-card
    class="tender-card"
    size="small"
  >
    <!-- 收起态头部：一行摘要（文件名 + 状态 + 操作）.
         招标文件上传是第一步动作，页面上它必须出现在「评分点」tab 之上；
         有解析数据时默认收起，避免大拖拽区把评分点表格挤出首屏。 -->
    <div
      v-if="collapsible"
      class="tender-card__head"
    >
      <div class="tender-card__summary">
        <span class="tender-card__label">招标文件</span>
        <template v-if="primary">
          <span
            class="tender-card__name"
            :title="primary.title"
          >{{ primary.title }}</span>
          <a-tag :color="tenderStatusColor(primary.status)">
            {{ tenderStatusText(primary.status) }}
          </a-tag>
          <a-tag
            v-if="isTenderStale(primary)"
            color="warning"
          >
            超时
          </a-tag>
        </template>
        <span
          v-else
          class="tender-card__name tender-card__name--empty"
        >尚未上传</span>
        <a-tag
          v-if="pendingCount > 0"
          color="processing"
        >
          解析中，页面将自动刷新
        </a-tag>
      </div>

      <a-space :size="4">
        <a-button
          v-if="primary && canReparseTender(primary)"
          size="small"
          type="link"
          :loading="reparseId === primary.id"
          @click="emit('reparse', primary.id)"
        >
          重新解析
        </a-button>
        <a-button
          v-if="primary"
          size="small"
          type="link"
          danger
          @click="emit('delete', primary.id, primary.title)"
        >
          删除
        </a-button>
        <a-button
          size="small"
          :aria-expanded="expanded"
          @click="emit('update:expanded', !expanded)"
        >
          <template #icon>
            <DownOutlined v-if="!expanded" />
            <UpOutlined v-else />
          </template>
          {{ expanded ? '收起' : '上传 / 文件列表' }}
        </a-button>
      </a-space>
    </div>

    <!-- 主体：无解析数据时恒显（整页即上传入口）；有数据时随展开态显示 -->
    <div
      v-if="!collapsible || expanded"
      class="tender-card__body"
    >
      <!-- 公司资料引导：二期起公司素材统一在全局资料库管理 -->
      <a-alert
        type="info"
        show-icon
        class="tender-card__hint"
        message="公司资料（产品手册/历史方案/资质证书）已迁移至「全局资料库」统一管理"
      >
        <template #action>
          <a-button
            size="small"
            type="link"
            @click="emit('goto-materials')"
          >
            前往全局资料库
          </a-button>
        </template>
      </a-alert>

      <!-- 招标文件上传（tender_file：上传后自动入队解析） -->
      <a-upload-dragger
        :file-list="fileList"
        :multiple="false"
        accept=".pdf,.doc,.docx"
        :before-upload="beforeUpload"
        :custom-request="forwardUpload"
        :show-upload-list="true"
        @update:file-list="(list: UploadFile[]) => emit('update:fileList', list)"
      >
        <p class="ant-upload-drag-icon">
          <InboxOutlined />
        </p>
        <p class="ant-upload-text">
          点击或拖拽招标文件到此区域上传
        </p>
        <p class="ant-upload-hint">
          支持 PDF / Word 格式，单文件不超过 50MB，上传后自动解析评分点
        </p>
      </a-upload-dragger>

      <!-- 已上传招标文件列表（解析状态跟踪） -->
      <a-table
        v-if="docs.length > 0"
        :columns="columns"
        :data-source="docs"
        :pagination="false"
        row-key="id"
        size="middle"
      >
        <template #bodyCell="{ column, record }">
          <template v-if="column.key === 'status'">
            <a-tag :color="tenderStatusColor(record.status)">
              {{ tenderStatusText(record.status) }}
            </a-tag>
            <a-tag
              v-if="isTenderStale(record)"
              color="warning"
              class="tender-card__stale-tag"
            >
              超时
            </a-tag>
          </template>
          <template v-if="column.key === 'created_at'">
            {{ formatTenderTime(record.created_at) }}
          </template>
          <template v-if="column.key === 'action'">
            <a-space>
              <a-button
                v-if="canReparseTender(record)"
                size="small"
                type="link"
                :loading="reparseId === record.id"
                @click="emit('reparse', record.id)"
              >
                重新解析
              </a-button>
              <a-button
                size="small"
                type="link"
                danger
                @click="emit('delete', record.id, record.title)"
              >
                删除
              </a-button>
            </a-space>
          </template>
        </template>
      </a-table>

      <div
        v-if="docs.length > 0"
        class="tender-card__refresh"
      >
        <a-space>
          <a-tag
            v-if="pendingCount > 0"
            color="processing"
          >
            解析中，页面将自动刷新
          </a-tag>
          <a-button
            :loading="loading"
            @click="emit('refresh')"
          >
            刷新
          </a-button>
        </a-space>
      </div>
    </div>
  </a-card>
</template>

<script setup lang="ts">
/**
 * TenderFileCard：招标文件上传 / 列表卡片（纯展示，状态与请求由父组件持有）.
 *
 * 两种形态：
 * - collapsible=false（无解析数据）：整页即上传入口，头部不渲染，主体恒显；
 * - collapsible=true（有解析数据）：默认收起为一行摘要（文件名 + 状态 + 操作），
 *   展开后出现拖拽区与文件列表。收起态置于「评分点」tab 之上，不挤占表格首屏。
 *
 * 状态口径全部来自 utils/tenderDoc（纯函数，另有单测锁定），不在此重复实现。
 */
import { computed } from 'vue'
import { InboxOutlined, DownOutlined, UpOutlined } from '@ant-design/icons-vue'
import type { UploadFile, UploadProps } from 'ant-design-vue'
import {
  canReparseTender,
  formatTenderTime,
  isTenderStale,
  pendingTenderDocs,
  pickPrimaryTender,
  tenderStatusColor,
  tenderStatusText,
  type TenderDoc,
} from '@/utils/tenderDoc'

/** a-upload customRequest 入参（从 antd 类型派生，避免深路径导入） */
type UploadOption = Parameters<NonNullable<UploadProps['customRequest']>>[0]

const props = withDefaults(
  defineProps<{
    docs: TenderDoc[]
    loading: boolean
    reparseId: string | null
    fileList: UploadFile[]
    /** true=有数据态（可收起）；false=无数据态（整页上传入口，恒展开） */
    collapsible?: boolean
    expanded?: boolean
    beforeUpload?: UploadProps['beforeUpload']
  }>(),
  { collapsible: false, expanded: false, beforeUpload: undefined },
)

const emit = defineEmits<{
  'update:fileList': [UploadFile[]]
  'update:expanded': [boolean]
  upload: [UploadOption]
  reparse: [string]
  delete: [string, string]
  refresh: []
  'goto-materials': []
}>()

const columns = [
  { title: '文件名', dataIndex: 'title', key: 'title' },
  { title: '状态', key: 'status', width: 140 },
  { title: '上传时间', dataIndex: 'created_at', key: 'created_at', width: 180 },
  { title: '操作', key: 'action', width: 100 },
]

/** 收起态摘要展示的文档：列表首条（后端按 created_at DESC 返回） */
const primary = computed(() => pickPrimaryTender(props.docs))
/** 进行中且未超时的文档数（超时的不再轮询，由用户手动重新解析） */
const pendingCount = computed(() => pendingTenderDocs(props.docs).length)

const forwardUpload = (options: UploadOption) => emit('upload', options)
</script>

<style scoped>
.tender-card {
  background: var(--bg-surface);
}

/* 收起态头部：一行摘要 + 操作，窄屏自动换行 */
.tender-card__head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  flex-wrap: wrap;
}

.tender-card__summary {
  display: flex;
  align-items: center;
  gap: 8px;
  min-width: 0;
  flex-wrap: wrap;
}

.tender-card__label {
  font-size: var(--font-size-sm);
  color: var(--text-secondary);
}

.tender-card__name {
  max-width: 340px;
  overflow: hidden;
  color: var(--text-primary);
  font-weight: 500;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.tender-card__name--empty {
  color: var(--text-disabled);
  font-weight: 400;
}

.tender-card__body {
  margin-top: 12px;
}

.tender-card__hint {
  margin-bottom: 16px;
}

.tender-card__stale-tag {
  margin-left: 4px;
}

.tender-card__refresh {
  margin-top: 16px;
  text-align: right;
}
</style>
