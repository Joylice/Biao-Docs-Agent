<template>
  <div class="overview-panel">
    <!-- 头部 -->
    <div class="overview-panel__header">
      <div>
        <h3 class="overview-panel__title">{{ title }}</h3>
        <p class="overview-panel__desc">{{ desc }}</p>
      </div>
      <a-button size="small" :loading="loading" @click="load">
        <template #icon><ReloadOutlined /></template>
        刷新
      </a-button>
    </div>

    <a-spin :spinning="loading">
      <template v-if="snapshot">
        <!-- ── LLM 提供方 ── -->
        <div class="overview-panel__section">
          <div class="overview-panel__section-title">语言模型提供方</div>
          <div class="overview-panel__grid">
            <button
              v-for="p in snapshot.providers"
              :key="p.entryId"
              class="overview-card"
              type="button"
              @click="store.selectItem(p.entryId)"
            >
              <div class="overview-card__head">
                <span class="overview-card__name">{{ p.title }}</span>
                <a-tag :color="p.configured ? 'success' : 'warning'" class="overview-card__tag">
                  {{ p.configured ? '已配置' : '未配置' }}
                </a-tag>
              </div>
              <div class="overview-card__row">
                <code class="overview-card__mono">{{ p.apiKeyMasked || '密钥未配置' }}</code>
              </div>
              <div class="overview-card__row overview-card__row--muted">
                最近测试：{{ p.lastTestOk === null ? '—' : p.lastTestOk ? '通过' : '失败' }}
              </div>
            </button>
          </div>
        </div>

        <!-- ── 阶段路由 ── -->
        <div class="overview-panel__section">
          <div class="overview-panel__section-title">
            阶段路由
            <a-button type="link" size="small" @click="store.selectItem('llm:routes')">
              前往配置
            </a-button>
          </div>
          <div class="overview-panel__grid overview-panel__grid--wide">
            <div v-for="r in snapshot.routes" :key="r.stageKey" class="overview-card overview-card--static">
              <div class="overview-card__head">
                <span class="overview-card__name">{{ r.stageName }}</span>
                <a-tag v-if="!r.enabled" color="default" class="overview-card__tag">已停用</a-tag>
              </div>
              <div class="overview-card__row">
                <code class="overview-card__mono">{{ r.model || '（回退全局配置）' }}</code>
              </div>
            </div>
          </div>
        </div>

        <!-- ── 检索（Embedding / Rerank）── -->
        <div class="overview-panel__section">
          <div class="overview-panel__section-title">
            知识库检索
            <a-button type="link" size="small" @click="store.selectItem('retrieval:params')">
              前往配置
            </a-button>
          </div>
          <div class="overview-panel__grid overview-panel__grid--wide">
            <button class="overview-card" type="button" @click="store.selectItem('retrieval:params')">
              <div class="overview-card__head">
                <span class="overview-card__name">Embedding</span>
                <a-tag :color="snapshot.retrieval.embeddingConfigured ? 'success' : 'warning'" class="overview-card__tag">
                  {{ snapshot.retrieval.embeddingConfigured ? '已配置' : '未配置' }}
                </a-tag>
              </div>
              <div class="overview-card__row">
                <code class="overview-card__mono">{{ snapshot.retrieval.embeddingModel || '未配置模型' }}</code>
              </div>
            </button>
            <button class="overview-card" type="button" @click="store.selectItem('retrieval:params')">
              <div class="overview-card__head">
                <span class="overview-card__name">Rerank</span>
                <a-tag
                  :color="snapshot.retrieval.rerankEnabled ? 'success' : 'default'"
                  class="overview-card__tag"
                >
                  {{ snapshot.retrieval.rerankEnabled ? '已启用' : '未启用' }}
                </a-tag>
              </div>
              <div class="overview-card__row overview-card__row--muted">
                {{ snapshot.retrieval.rerankConfigured ? '密钥已配置' : '密钥未配置（可复用 Embedding）' }}
              </div>
            </button>
          </div>
        </div>

        <!-- ── 外部工具 ── -->
        <div class="overview-panel__section">
          <div class="overview-panel__section-title">外部搜索工具</div>
          <div class="overview-panel__grid overview-panel__grid--wide">
            <button
              v-for="t in snapshot.tools"
              :key="t.preset"
              class="overview-card"
              type="button"
              @click="store.selectItem(`websearch:${t.preset}`)"
            >
              <div class="overview-card__head">
                <span class="overview-card__name">{{ t.name }}</span>
                <a-tag
                  :color="!t.exists ? 'default' : t.enabled ? 'success' : 'warning'"
                  class="overview-card__tag"
                >
                  {{ !t.exists ? '未创建' : t.enabled ? '已启用' : '已停用' }}
                </a-tag>
              </div>
              <div class="overview-card__row overview-card__row--muted">
                {{ t.configured ? '密钥已配置' : '密钥未配置' }}
              </div>
            </button>
          </div>
        </div>
      </template>
      <a-empty v-else-if="!loading" description="暂无概览数据" />
    </a-spin>
  </div>
</template>

<script setup lang="ts">
/**
 * OverviewPanel：配置概览（P1-1）——只读状态汇总 + 条目跳转.
 *
 * 数据源为 buildOverviewSnapshot 快照（providers/routes/llm/retrieval/tools
 * 并行拉取）；连通性口径 = composable 内存中最近一次测试结果（不做实时探测）。
 * 数据新鲜度：watch configCenterStore.overviewVersion（任一条目保存成功
 * bumpOverview）自动重取；本面板只读，registry save 为 no-op。
 */
import { onMounted, watch } from 'vue'
import { ReloadOutlined } from '@ant-design/icons-vue'
import { useConfigCenterStore } from '@/stores/configCenter'
import { useOverviewConfig } from '@/composables/useOverviewConfig'

withDefaults(
  defineProps<{
    title?: string
    desc?: string
  }>(),
  { title: '状态总览', desc: '' },
)

const store = useConfigCenterStore()
const config = useOverviewConfig()

const { loading, snapshot, load } = config

onMounted(load)

// 任一条目保存成功 → overviewVersion++ → 重取快照
watch(
  () => store.overviewVersion,
  () => {
    void load()
  },
)
</script>

<style scoped>
.overview-panel {
  max-width: 860px;
}

.overview-panel__header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: var(--space-3);
  margin-bottom: var(--space-4);
}

.overview-panel__title {
  margin: 0;
  font-size: 16px;
  font-weight: 700;
  color: var(--text-primary);
}

.overview-panel__desc {
  margin: 4px 0 0;
  font-size: 12px;
  color: var(--text-tertiary);
  line-height: 1.6;
}

.overview-panel__section {
  margin-bottom: var(--space-4);
}

.overview-panel__section-title {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  margin-bottom: var(--space-2);
  font-size: 13px;
  font-weight: 600;
  color: var(--text-secondary);
}

.overview-panel__grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: var(--space-3);
}

.overview-panel__grid--wide {
  grid-template-columns: repeat(4, minmax(0, 1fr));
}

.overview-card {
  display: flex;
  flex-direction: column;
  gap: 6px;
  padding: var(--space-3);
  background: var(--bg-surface);
  border: 1px solid var(--border-color);
  border-radius: var(--radius-lg);
  text-align: left;
  cursor: pointer;
  transition: border-color var(--transition-fast);
}

.overview-card:hover {
  border-color: var(--color-primary);
}

.overview-card--static {
  cursor: default;
}

.overview-card--static:hover {
  border-color: var(--border-color);
}

.overview-card__head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-2);
  min-width: 0;
}

.overview-card__name {
  font-size: 13px;
  font-weight: 600;
  color: var(--text-primary);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.overview-card__tag {
  flex-shrink: 0;
  margin-inline-end: 0;
}

.overview-card__row {
  min-width: 0;
}

.overview-card__row--muted {
  font-size: 11px;
  color: var(--text-tertiary);
}

.overview-card__mono {
  font-family: var(--font-family-mono);
  font-size: 11px;
  color: var(--text-secondary);
  background: var(--bg-app);
  padding: 1px 5px;
  border-radius: var(--radius-sm);
  word-break: break-all;
}

@media (max-width: 1024px) {
  .overview-panel__grid,
  .overview-panel__grid--wide {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}
</style>
