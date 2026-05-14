<!--
  TaskStatusTag — 任务状态彩色 tag

  原状态字段可能是: row.status / row.state / row.enableordis (后端不固定)
  本组件做启发式判断，把字符串映射成 success / warning / danger / info 四色

  Props:
    status  String  原始状态值
  Slot:
    -      显示文本（默认显示 props 值）
-->
<template>
  <el-tag
    size="mini"
    effect="plain"
    :type="type"
    class="lt-task-status-tag"
  >
    <span v-if="showDot" class="lt-task-status-tag__dot" />
    <slot>{{ label }}</slot>
  </el-tag>
</template>

<script>
const RUNNING_PATTERNS = ['运行', '播放', 'running', 'playing', 'active', '启用', '执行中']
const FAILED_PATTERNS = ['失败', 'fail', 'error', '异常', 'offline']
const ENDED_PATTERNS = ['结束', 'done', 'finished', 'completed', 'idle', '已停止', 'stopped']
const PENDING_PATTERNS = ['待', 'pending', 'wait', '排队', 'queue']

function match(text, list) {
  if (!text) return false
  const t = String(text).toLowerCase()
  return list.some((kw) => t.includes(kw.toLowerCase()))
}

export default {
  name: 'TaskStatusTag',
  props: {
    status: { type: [String, Number], default: '' }
  },
  computed: {
    text() {
      const s = this.status
      if (s === '' || s === undefined || s === null) return '未知'
      // enableordis 常见是 0/1
      if (String(s) === '0') return '停用'
      if (String(s) === '1') return '启用'
      return String(s)
    },
    type() {
      const s = this.text
      if (match(s, RUNNING_PATTERNS) || s === '启用') return 'success'
      if (match(s, FAILED_PATTERNS)) return 'danger'
      if (match(s, PENDING_PATTERNS)) return 'warning'
      if (match(s, ENDED_PATTERNS) || s === '停用') return 'info'
      return 'info'
    },
    showDot() {
      return this.type === 'success' || this.type === 'warning'
    },
    label() {
      return this.text
    }
  }
}
</script>

<style lang="scss" scoped>
.lt-task-status-tag {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  &__dot {
    width: 6px;
    height: 6px;
    border-radius: 50%;
    background: currentColor;
    display: inline-block;
    animation: lt-pulse 1.8s ease-in-out infinite;
  }
}
@keyframes lt-pulse {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.45; }
}
</style>
