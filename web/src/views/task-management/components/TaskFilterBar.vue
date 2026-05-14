<!--
  TaskFilterBar — 任务管理顶部筛选条

  Props:
    tab        String  当前选中的状态 tab (all / running / failed / done)
    counts     Object  各 tab 的计数 { all, running, failed, done }
    search     String  搜索关键词
  Events:
    update:tab
    update:search
-->
<template>
  <div class="lt-task-filter-bar">
    <div class="lt-seg">
      <button
        v-for="t in tabs"
        :key="t.value"
        :class="['lt-seg__btn', { 'is-active': tab === t.value }]"
        @click="$emit('update:tab', t.value)"
      >
        {{ t.label }}
        <span v-if="counts[t.value] !== undefined" class="lt-seg__count">{{ counts[t.value] }}</span>
      </button>
    </div>

    <div class="lt-task-filter-bar__search">
      <el-input
        :value="search"
        size="small"
        clearable
        prefix-icon="el-icon-search"
        placeholder="按 ID 或任务名搜索"
        @input="$emit('update:search', $event)"
      />
    </div>

    <div class="lt-task-filter-bar__spacer" />

    <slot name="actions" />
  </div>
</template>

<script>
export default {
  name: 'TaskFilterBar',
  props: {
    tab: { type: String, default: 'all' },
    counts: { type: Object, default: () => ({}) },
    search: { type: String, default: '' }
  },
  data() {
    return {
      tabs: [
        { value: 'all',     label: '全部' },
        { value: 'running', label: '运行中' },
        { value: 'failed',  label: '失败' },
        { value: 'done',    label: '已结束' }
      ]
    }
  }
}
</script>

<style lang="scss" scoped>
.lt-task-filter-bar {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 10px 12px;
  border-bottom: 1px solid var(--lt-line-soft);

  &__search {
    width: 220px;
  }
  &__spacer { flex: 1; }
}

.lt-seg {
  display: inline-flex;
  border: 1px solid var(--lt-line-strong);
  border-radius: var(--lt-r);
  overflow: hidden;
  background: #fff;

  &__btn {
    border: 0;
    background: transparent;
    height: 28px;
    padding: 0 12px;
    cursor: pointer;
    font-size: 12px;
    color: var(--lt-t2);
    font-family: inherit;
    border-right: 1px solid var(--lt-line-soft);
    display: inline-flex;
    align-items: center;
    gap: 4px;
    transition: background .12s, color .12s;

    &:last-child { border-right: 0; }
    &:hover { color: var(--lt-p); }

    &.is-active {
      background: var(--lt-p-soft);
      color: var(--lt-p);
    }
  }
  &__count {
    color: var(--lt-t4);
    font-family: var(--lt-mono);
    font-size: 11px;
  }
  &__btn.is-active &__count {
    color: var(--lt-p);
  }
}
</style>
