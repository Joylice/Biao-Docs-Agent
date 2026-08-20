<template>
  <a-card
    class="version-panel"
    title="版本库"
  >
    <template #extra>
      <a-button
        v-if="isOwner"
        size="small"
        :loading="snapshotting"
        @click="$emit('open-snapshot')"
      >
        手动快照
      </a-button>
    </template>

    <a-empty
      v-if="versions.length === 0"
      description="暂无版本：全部章节审核通过后将自动快照，owner 也可手动创建"
    />

    <a-list
      v-else
      :data-source="versions"
      size="small"
    >
      <template #renderItem="{ item }">
        <a-list-item>
          <div class="version-panel__item">
            <div class="version-panel__main">
              <a-tag color="blue">
                v{{ item.version }}
              </a-tag>
              <a-tag
                v-if="item.auto"
                color="default"
              >
                自动快照
              </a-tag>
              <span class="version-panel__note">{{ item.snapshot_note || '—' }}</span>
              <span class="version-panel__meta">
                {{ item.created_by_name || '系统' }} · {{ formatTime(item.created_at) }}
              </span>
            </div>
            <a-space>
              <a-button
                size="small"
                @click="$emit('download', item, 'docx')"
              >
                下载 Word
              </a-button>
              <a-button
                size="small"
                @click="$emit('download', item, 'source')"
              >
                Markdown 源
              </a-button>
              <a-button
                v-if="isOwner"
                size="small"
                @click="$emit('archive', item)"
              >
                归档
              </a-button>
              <a-button
                v-if="isOwner"
                size="small"
                danger
                :loading="rollingBackId === item.id"
                @click="$emit('rollback', item)"
              >
                回滚
              </a-button>
            </a-space>
          </div>
        </a-list-item>
      </template>
    </a-list>
  </a-card>
</template>

<script setup lang="ts">
interface VersionItem {
  id: string
  version: number
  snapshot_note: string | null
  created_by: string | null
  created_by_name: string | null
  auto: boolean
  created_at: string | null
}

defineProps<{
  versions: VersionItem[]
  isOwner: boolean
  snapshotting: boolean
  rollingBackId: string
}>()

defineEmits<{
  (e: 'open-snapshot'): void
  (e: 'download', item: VersionItem, type: 'docx' | 'source'): void
  (e: 'archive', item: VersionItem): void
  (e: 'rollback', item: VersionItem): void
}>()

const formatTime = (iso: string | null): string => {
  if (!iso) return '—'
  const d = new Date(iso)
  return Number.isNaN(d.getTime()) ? '—' : d.toLocaleString('zh-CN', { hour12: false })
}
</script>

<style scoped>
.version-panel {
  margin-top: 24px;
  background: var(--bg-surface);
}

.version-panel__item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  width: 100%;
}

.version-panel__main {
  display: flex;
  align-items: center;
  gap: 8px;
  min-width: 0;
  flex-wrap: wrap;
}

.version-panel__note {
  font-size: 13px;
}

.version-panel__meta {
  font-size: 12px;
  color: var(--text-tertiary);
}
</style>
