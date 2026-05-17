<!--
  SchemeRail — 左侧方案目录卡片列表

  Props:
    schemes      Array   原始方案数据 (从 scheduleSchemes computed 来)
                         每个元素 { id, name, tasks: [], task_error?: String }
    selectedId   String  当前选中的方案 id (用于高亮)
    currentId    String  远端启用方案的 id (用于显示"启用中"tag)
    activatingId String  正在切换的方案 id (用于 loading 状态, 暂未使用，预留)
    loading      Boolean 加载中
    error        String  加载失败信息

  Events:
    select(id)   点击某个方案 — 父组件把它设为选中
-->
<template>
  <el-card shadow="never" class="lt-scheme-rail">
    <div slot="header" class="lt-scheme-rail__header">
      <span class="lt-scheme-rail__title">方案目录</span>
      <span class="lt-scheme-rail__count">共 {{ schemes.length }} 套</span>
    </div>

    <el-alert
      v-if="error"
      :title="error"
      type="warning"
      show-icon
      :closable="false"
      class="lt-scheme-rail__alert"
    />

    <div v-if="loading && !schemes.length" class="lt-scheme-rail__empty">加载中…</div>
    <el-empty v-else-if="!schemes.length && !error" description="暂无方案" :image-size="60" />

    <div v-else class="lt-scheme-rail__list">
      <div
        v-for="s in schemes"
        :key="s.id"
        class="lt-scheme-item"
        :class="{
          'is-selected': String(s.id) === String(selectedId),
          'is-current': isCurrent(s),
          'is-empty': !taskCount(s)
        }"
        @click="$emit('select', s.id)"
      >
        <div class="lt-scheme-item__row">
          <div class="lt-scheme-item__name">
            <el-tooltip :content="schemeTitle(s)" placement="top" :disabled="!schemeTitle(s)">
              <span class="lt-scheme-item__title-text">{{ schemeTitle(s) }}</span>
            </el-tooltip>
            <el-tag v-if="isCurrent(s)" size="mini" type="success">启用中</el-tag>
          </div>
          <span class="lt-scheme-item__count lt-mono">{{ taskCount(s) }} 项</span>
        </div>

        <div class="lt-scheme-item__row lt-scheme-item__row--timeline">
          <timeline :tasks="schemeTasks(s)" mode="mini" />
        </div>

        <div v-if="s.task_error" class="lt-scheme-item__error">详情加载失败</div>
      </div>
    </div>
  </el-card>
</template>

<script>
import Timeline from './Timeline.vue'

export default {
  name: 'SchemeRail',
  components: { Timeline },
  props: {
    schemes: { type: Array, default: () => [] },
    selectedId: { type: [String, Number], default: '' },
    currentId: { type: [String, Number], default: '' },
    activatingId: { type: [String, Number], default: '' },
    loading: { type: Boolean, default: false },
    error: { type: String, default: '' }
  },
  methods: {
    schemeTitle(s) {
      const name = s && s.name ? String(s.name).trim() : ''
      if (name) return name
      return s && s.id ? `方案 ${s.id}` : '未命名方案'
    },
    schemeTasks(s) {
      return Array.isArray(s && s.tasks) ? s.tasks : []
    },
    taskCount(s) {
      return this.schemeTasks(s).length
    },
    isCurrent(s) {
      return Boolean(
        this.currentId &&
        s &&
        String(s.id) === String(this.currentId)
      )
    }
  }
}
</script>

<style lang="scss" scoped>
.lt-scheme-rail {
  display: flex;
  flex-direction: column;
  height: 100%;

  /* 让 card 内容滚动而不是整体 */
  ::v-deep .el-card__body {
    padding: 8px;
    overflow-y: auto;
    flex: 1;
  }

  &__header {
    display: flex;
    justify-content: space-between;
    align-items: center;
  }
  &__title {
    font-size: 14px;
    font-weight: 600;
    color: var(--lt-t1);
  }
  &__count {
    font-size: 12px;
    color: var(--lt-t3);
  }

  &__alert {
    margin-bottom: 8px;
  }
  &__empty {
    padding: 24px 0;
    text-align: center;
    font-size: 12px;
    color: var(--lt-t3);
  }
  &__list {
    display: flex;
    flex-direction: column;
    gap: 6px;
  }
}

.lt-scheme-item {
  padding: 8px 10px;
  border: 1px solid var(--lt-line);
  background: #fff;
  border-radius: var(--lt-r);
  cursor: pointer;
  transition: border-color .15s, background .15s;

  &:hover {
    border-color: var(--lt-p-line);
    background: #fafcff;
  }
  &.is-selected {
    border-color: var(--lt-p);
    background: var(--lt-p-soft);
  }
  &.is-current {
    border-left: 3px solid var(--lt-ok);
    padding-left: 7px;
  }
  &.is-empty .lt-scheme-item__count {
    color: var(--lt-t4);
  }

  &__row {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 8px;

    &--timeline {
      margin-top: 6px;
    }
  }
  &__name {
    display: flex;
    align-items: center;
    gap: 6px;
    min-width: 0;
    flex: 1;
  }
  &__title-text {
    display: inline-block;
    min-width: 0;
    flex: 1;
    font-size: 13px;
    font-weight: 600;
    color: var(--lt-t1);
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }
  &__count {
    font-size: 11px;
    color: var(--lt-t3);
    flex-shrink: 0;
  }
  &__error {
    margin-top: 4px;
    font-size: 11px;
    color: var(--lt-danger);
  }
}
</style>
