<!--
  TaskDetailHeader — 方案详情头部

  显示当前选中方案的：
    - 名称 + 启用中 tag
    - 元信息 (方案 ID / 任务数)
    - 操作按钮组 (复制 / 重命名 / 设为当前作息)
    - 时间轴预览 (Timeline mode=full)

  Props:
    scheme        Object   选中的方案 { id, name, tasks }
    isCurrent     Boolean  这个方案是否远端正在用
    tasks         Array    任务列表 (用于时间轴 + 任务数)
    activating    Boolean  正在切换为当前作息
    syncMessage   String   切换中的提示 (例 "切换请求已提交…")
    canActivate   Boolean  是否允许切换 (默认 true，空方案应禁用)

  Events:
    activate       点击"设为当前作息"
    copy           点击"复制" (暂时无后端接口，禁用)
    rename         点击"重命名" (暂时无后端接口，禁用)
-->
<template>
  <div v-if="scheme" class="lt-task-detail-header">
    <div class="lt-task-detail-header__row">
      <div class="lt-task-detail-header__text">
        <div class="lt-task-detail-header__title">
          <span class="lt-task-detail-header__name">{{ schemeName }}</span>
          <el-tag v-if="isCurrent" size="mini" type="success">当前启用</el-tag>
        </div>
        <div class="lt-task-detail-header__meta">
          <span>方案 ID</span>
          <span class="lt-mono">{{ scheme.id }}</span>
          <span class="lt-task-detail-header__sep">·</span>
          <span>{{ tasks.length }} 个任务</span>
          <span v-if="timeRangeLabel" class="lt-task-detail-header__sep">·</span>
          <span v-if="timeRangeLabel" class="lt-mono">{{ timeRangeLabel }}</span>
        </div>
      </div>

      <div class="lt-task-detail-header__actions">
        <el-tooltip content="复制方案（即将支持）" placement="top">
          <span>
            <el-button size="mini" icon="el-icon-document-copy" disabled @click="$emit('copy')">
              复制
            </el-button>
          </span>
        </el-tooltip>
        <el-tooltip content="重命名（即将支持）" placement="top">
          <span>
            <el-button size="mini" icon="el-icon-edit-outline" disabled @click="$emit('rename')">
              重命名
            </el-button>
          </span>
        </el-tooltip>
        <el-button
          v-if="!isCurrent"
          size="mini"
          type="primary"
          icon="el-icon-position"
          :loading="activating"
          :disabled="!canActivate"
          @click="$emit('activate')"
        >
          设为当前作息
        </el-button>
      </div>
    </div>

    <el-alert
      v-if="syncMessage"
      :title="syncMessage"
      type="info"
      show-icon
      :closable="false"
      class="lt-task-detail-header__alert"
    />

    <!-- 时间轴预览 -->
    <div v-if="tasks.length" class="lt-task-detail-header__timeline-block">
      <div class="lt-task-detail-header__timeline-label">时间轴预览</div>
      <timeline :tasks="tasks" mode="full" />
    </div>
  </div>
</template>

<script>
import Timeline from './Timeline.vue'

export default {
  name: 'TaskDetailHeader',
  components: { Timeline },
  props: {
    scheme: { type: Object, default: null },
    isCurrent: { type: Boolean, default: false },
    tasks: { type: Array, default: () => [] },
    activating: { type: Boolean, default: false },
    syncMessage: { type: String, default: '' },
    canActivate: { type: Boolean, default: true }
  },
  computed: {
    schemeName() {
      const name = this.scheme && this.scheme.name ? String(this.scheme.name).trim() : ''
      if (name) return name
      return this.scheme && this.scheme.id ? `方案 ${this.scheme.id}` : '—'
    },
    timeRangeLabel() {
      if (!this.tasks.length) return ''
      const times = this.tasks
        .map((t) => String(t.playtime || t.time || '').slice(0, 5))
        .filter(Boolean)
        .sort()
      if (!times.length) return ''
      return times[0] === times[times.length - 1]
        ? times[0]
        : `${times[0]} – ${times[times.length - 1]}`
    }
  }
}
</script>

<style lang="scss" scoped>
.lt-task-detail-header {
  padding: 12px 16px;
  border-bottom: 1px solid var(--lt-line-soft);

  &__row {
    display: flex;
    justify-content: space-between;
    align-items: flex-start;
    gap: 16px;
  }
  &__text {
    min-width: 0;
    flex: 1;
  }
  &__title {
    display: flex;
    align-items: center;
    gap: 8px;
    flex-wrap: wrap;
  }
  &__name {
    font-size: 15px;
    font-weight: 600;
    color: var(--lt-t1);
  }
  &__meta {
    margin-top: 3px;
    display: flex;
    align-items: center;
    gap: 6px;
    font-size: 12px;
    color: var(--lt-t3);
    flex-wrap: wrap;
  }
  &__sep {
    color: var(--lt-line-strong);
  }
  &__actions {
    display: flex;
    gap: 6px;
    flex-shrink: 0;
  }
  &__alert {
    margin-top: 8px;
  }

  &__timeline-block {
    margin-top: 10px;
  }
  &__timeline-label {
    font-size: 12px;
    color: var(--lt-t2);
    font-weight: 500;
    margin-bottom: 6px;
  }
}
</style>
