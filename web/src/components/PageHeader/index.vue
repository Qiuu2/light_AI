<!--
  PageHeader — 三个 light 页面共用的页头

  使用方式：
    <page-header title="作息管理" subtitle="…">
      <template #status>
        <el-tag size="mini" type="success">远端正常</el-tag>
      </template>
      <el-button size="mini" icon="el-icon-refresh">刷新</el-button>
      <el-button size="mini" type="primary" icon="el-icon-plus">新增任务</el-button>
    </page-header>

  - title / subtitle 为字符串
  - #status 槽：右侧操作区前的状态标签 (可选)
  - 默认槽：右侧操作按钮组
-->
<template>
  <div class="lt-page-header">
    <div class="lt-page-header__text">
      <h2 class="lt-page-header__title">{{ title }}</h2>
      <p v-if="subtitle" class="lt-page-header__subtitle">{{ subtitle }}</p>
    </div>

    <div class="lt-page-header__actions">
      <slot name="status" />
      <slot />
    </div>
  </div>
</template>

<script>
export default {
  name: 'PageHeader',
  props: {
    title: { type: String, required: true },
    subtitle: { type: String, default: '' }
  }
}
</script>

<style lang="scss" scoped>
.lt-page-header {
  display: flex;
  align-items: flex-end;
  justify-content: space-between;
  gap: 16px;
  margin-bottom: 14px;

  &__text {
    min-width: 0;
  }
  &__title {
    margin: 0;
    font-size: 18px;
    font-weight: 600;
    color: var(--lt-t1, #1f2329);
    line-height: 1.4;
  }
  &__subtitle {
    margin: 4px 0 0;
    color: var(--lt-t3, #86909c);
    font-size: 12px;
    line-height: 1.5;
  }
  &__actions {
    display: flex;
    align-items: center;
    gap: 8px;
    flex-shrink: 0;
  }
}

@media (max-width: 760px) {
  .lt-page-header {
    flex-direction: column;
    align-items: flex-start;

    &__actions {
      flex-wrap: wrap;
    }
  }
}
</style>
