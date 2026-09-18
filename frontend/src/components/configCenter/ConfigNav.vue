<template>
  <nav class="config-nav">
    <section
      v-for="cat in categories"
      :key="cat.id"
      class="config-nav__group"
      :class="{ 'config-nav__group--active': cat.id === store.activeCategoryId }"
    >
      <button
        type="button"
        class="config-nav__cat"
        :aria-label="`切换到 ${cat.title}`"
        @click="selectCategory(cat.id)"
      >
        <span class="config-nav__cat-icon">
          <component :is="cat.icon" />
        </span>
        <span class="config-nav__cat-title">{{ cat.title }}</span>
      </button>
      <ul class="config-nav__items">
        <li v-for="entry in getEntriesByCategory(cat.id)" :key="entry.id">
          <button
            type="button"
            class="config-nav__item"
            :class="{ 'config-nav__item--active': entry.id === store.activeItemId }"
            :aria-current="entry.id === store.activeItemId ? 'true' : undefined"
            @click="store.selectItem(entry.id)"
          >
            <span class="config-nav__item-text">
              <span class="config-nav__item-title">{{ entry.title }}</span>
              <span class="config-nav__item-desc">{{ entry.desc }}</span>
            </span>
            <span
              v-if="store.dirtyItems.has(entry.id)"
              class="config-nav__dirty-dot"
              title="有未保存改动"
            />
          </button>
        </li>
      </ul>
    </section>
  </nav>
</template>

<script setup lang="ts">
/**
 * 配置中心弹窗左侧两级导航（registry 驱动，ARCH §1.3）。
 *
 * 一级：6 个分类（点击选中该分类的首个条目）；二级：分类下条目
 * （点击 selectItem，active 高亮，dirty 条目显示圆点角标）。
 * 样式沿用旧 SettingsLayout 的 nav-item 视觉规范；<1024px 时折叠为
 * 顶部横向分类条（与弹窗 body 的纵向布局联动，见 ConfigCenterModal 全局样式）。
 */
import { useConfigCenterStore } from '@/stores/configCenter'
import {
  getConfigCategories,
  getEntriesByCategory,
  resolveEntry,
} from '@/config/configRegistry'

const store = useConfigCenterStore()
const categories = getConfigCategories()

/** 点击一级分类：定位该分类首个条目（分类本身不承载内容） */
const selectCategory = (categoryId: string) => {
  const first = getEntriesByCategory(categoryId)[0]
  if (resolveEntry(first?.id)) {
    store.selectItem(first.id)
  }
}
</script>

<style scoped>
.config-nav {
  display: flex;
  flex-direction: column;
  gap: 2px;
  padding: var(--space-2) var(--space-2);
  overflow-y: auto;
  scrollbar-width: thin;
  scrollbar-color: var(--border-color-strong) transparent;
}

.config-nav::-webkit-scrollbar {
  width: 5px;
}

.config-nav::-webkit-scrollbar-thumb {
  background: var(--border-color-strong);
  border-radius: 3px;
}

.config-nav::-webkit-scrollbar-track {
  background: transparent;
}

/* === 一级分类 === */
.config-nav__group + .config-nav__group {
  margin-top: 4px;
}

.config-nav__cat {
  display: flex;
  align-items: center;
  gap: 10px;
  width: 100%;
  padding: 7px 10px;
  border: none;
  border-radius: var(--radius-md);
  background: transparent;
  cursor: pointer;
  text-align: left;
  transition: background var(--transition-fast);
}

.config-nav__cat:hover {
  background: var(--bg-surface-hover);
}

.config-nav__cat-icon {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 26px;
  height: 26px;
  border-radius: 8px;
  background: var(--fill);
  color: var(--text-secondary);
  font-size: 14px;
  flex-shrink: 0;
  transition:
    background var(--transition-fast),
    color var(--transition-fast);
}

/* 分类激活：浅主色底 + 主色图标 */
.config-nav__group--active .config-nav__cat-icon {
  background: var(--color-primary-light);
  color: var(--color-primary);
}

.config-nav__cat-title {
  font-size: 13px;
  font-weight: 600;
  letter-spacing: 0.2px;
  color: var(--text-primary);
  transition: color var(--transition-fast);
}

.config-nav__group--active .config-nav__cat-title {
  color: var(--color-primary);
  font-weight: 700;
}

/* === 二级条目 === */
.config-nav__items {
  position: relative;
  margin: 0;
  padding: 2px 0 4px 36px;
  list-style: none;
}

.config-nav__items::before {
  content: '';
  position: absolute;
  left: 23px;
  top: 0;
  bottom: 10px;
  width: 1px;
  background: var(--border-color);
}

.config-nav__item {
  position: relative;
  display: flex;
  align-items: center;
  gap: 8px;
  width: 100%;
  padding: 6px 10px;
  border: none;
  border-radius: var(--radius-md);
  background: transparent;
  cursor: pointer;
  text-align: left;
  transition: background var(--transition-fast);
}

.config-nav__item:hover {
  background: var(--bg-surface-hover);
}

.config-nav__item--active {
  background: var(--color-primary-light);
}

.config-nav__item-text {
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: 1px;
  min-width: 0;
}

.config-nav__item-title {
  font-size: 13px;
  font-weight: 500;
  color: var(--text-primary);
  line-height: 1.4;
  transition: color var(--transition-fast);
}

.config-nav__item--active .config-nav__item-title {
  color: var(--color-primary);
  font-weight: 600;
}

.config-nav__item-desc {
  font-size: 11px;
  color: var(--text-tertiary);
  line-height: 1.3;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

/* 未保存圆点角标 */
.config-nav__dirty-dot {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: var(--color-warning);
  flex-shrink: 0;
}
</style>
