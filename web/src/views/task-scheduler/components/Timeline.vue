<!--
  Timeline — 24 小时任务时间轴

  Props:
    tasks    Array  形如 [{ id, name, time: 'HH:MM:SS' }]
    mode     'full' | 'mini'   默认 full
    height   Number 单位 px (mini 默认 18, full 默认 64)

  full 模式: 顶部刻度 + 事件名标签, 用在方案详情头
  mini 模式: 纯条形, 用在 SchemeRail 卡片里
-->
<template>
  <div
    class="lt-timeline"
    :class="['lt-timeline--' + mode]"
    :style="{ height: heightPx }"
  >
    <!-- 小时刻度 -->
    <template v-if="mode === 'full'">
      <div
        v-for="h in 25"
        :key="'h-' + h"
        class="lt-timeline__tick"
        :class="{ 'lt-timeline__tick--major': ((h - 1) % 6) === 0 }"
        :style="{ left: percent(h - 1) }"
      >
        <span v-if="((h - 1) % 2) === 0" class="lt-timeline__hour">
          {{ pad(h - 1) }}
        </span>
      </div>
    </template>

    <!-- mini 模式的简化刻度 -->
    <template v-else>
      <div
        v-for="h in [0, 6, 12, 18, 24]"
        :key="'mh-' + h"
        class="lt-timeline__tick lt-timeline__tick--mini"
        :style="{ left: percent(h) }"
      />
    </template>

    <!-- 空态 -->
    <div v-if="!tasks.length && mode === 'mini'" class="lt-timeline__empty">空</div>

    <!-- 事件 -->
    <template v-for="(t, idx) in tasks">
      <!-- mini: 只画一条 -->
      <div
        v-if="mode === 'mini'"
        :key="'m-' + (taskId(t) || idx)"
        class="lt-timeline__bar"
        :style="{ left: percent(hours(t)) }"
        :title="eventTitle(t)"
      />

      <!-- full: 一条 + 名签 -->
      <div
        v-else
        :key="'f-' + (taskId(t) || idx)"
        class="lt-timeline__event"
        :style="eventStyle(t)"
        :title="eventTitle(t)"
      >
        <span class="lt-timeline__line" />
        <span class="lt-timeline__label">
          {{ shortTime(taskTime(t)) }} {{ taskName(t) }}
        </span>
      </div>
    </template>
  </div>
</template>

<script>
export default {
  name: 'LtTimeline',
  props: {
    tasks: { type: Array, default: () => [] },
    mode: {
      type: String,
      default: 'full',
      validator: (v) => ['full', 'mini'].includes(v)
    },
    height: { type: Number, default: 0 }
  },
  computed: {
    heightPx() {
      if (this.height) return this.height + 'px'
      return this.mode === 'mini' ? '18px' : '64px'
    }
  },
  methods: {
    dataAt(row, idx) {
      return row && Array.isArray(row.data) ? row.data[idx] : ''
    },
    taskId(t) {
      return t && (t.taskid || t.task_id || t.id || '')
    },
    taskName(t) {
      return (t && (t.taskname || t.name || t.title || this.dataAt(t, 0))) || ''
    },
    taskTime(t) {
      if (!t) return '00:00:00'
      if (t.playtime) return t.playtime
      if (t.time) return t.time
      const dataTime = this.dataAt(t, 1)
      if (dataTime) return dataTime
      const h = t.playhour
      const m = t.playminute
      const s = t.playsecond
      if (h === undefined && m === undefined && s === undefined) return '00:00:00'
      return `${String(h || 0).padStart(2, '0')}:${String(m || 0).padStart(2, '0')}:${String(s || 0).padStart(2, '0')}`
    },
    eventTitle(t) {
      const time = this.taskTime(t)
      const name = this.taskName(t)
      return name ? `${time} ${name}` : time
    },
    hours(t) {
      const time = String(this.taskTime(t) || '00:00:00')
      const parts = time.split(':')
      const h = Number(parts[0]) || 0
      const m = Number(parts[1]) || 0
      const s = Number(parts[2]) || 0
      return h + m / 60 + s / 3600
    },
    percent(h) {
      const ratio = Math.max(0, Math.min(24, h)) / 24
      return (ratio * 100).toFixed(2) + '%'
    },
    eventStyle(t) {
      // 根据事件的左偏百分比智能选择 transform，避免最左/最右的 label 溢出容器
      const ratio = Math.max(0, Math.min(24, this.hours(t))) / 24
      const pct = ratio * 100
      let transform
      if (pct < 8) transform = 'translateX(0)'           // 最左：左对齐展开
      else if (pct > 92) transform = 'translateX(-100%)'  // 最右：右对齐展开
      else transform = 'translateX(-50%)'                 // 中间：居中
      return { left: pct.toFixed(2) + '%', transform }
    },
    pad(n) {
      return String(n).padStart(2, '0')
    },
    shortTime(t) {
      const s = String(t || '')
      return s ? s.slice(0, 5) : ''
    }
  }
}
</script>

<style lang="scss" scoped>
.lt-timeline {
  position: relative;
  width: 100%;
  background: var(--lt-surface-2, #fafbfc);
  border: 1px solid var(--lt-line-soft, #ebeef2);
  border-radius: var(--lt-r, 4px);

  &--mini {
    background: var(--lt-surface-2, #f4f5f7);
    border-radius: 2px;
  }

  &__tick {
    position: absolute;
    top: 0;
    bottom: 0;
    border-left: 1px dashed var(--lt-line-soft, #ebeef2);
    pointer-events: none;

    &--major {
      border-left: 1px solid var(--lt-line, #e4e7ed);
    }
    &--mini {
      border-left: 1px dashed rgba(0, 0, 0, 0.08);
    }
  }
  &__hour {
    position: absolute;
    top: 3px;
    left: -10px;
    font-size: 10px;
    color: var(--lt-t4, #c0c4cc);
    font-family: var(--lt-mono);
  }

  &__empty {
    position: absolute;
    inset: 0;
    display: flex;
    align-items: center;
    justify-content: center;
    font-size: 10px;
    color: var(--lt-t4, #c0c4cc);
  }

  /* mini 模式 bar */
  &__bar {
    position: absolute;
    top: 2px;
    bottom: 2px;
    width: 3px;
    background: var(--lt-p, #409eff);
    border-radius: 1px;
    transform: translateX(-50%);
  }

  /* full 模式事件 — transform 由 eventStyle 根据位置百分比智能给出，
     避免最左/最右的 label 溢出容器，所以这里不写死 translateX(-50%) */
  &__event {
    position: absolute;
    top: 22px;
    display: flex;
    flex-direction: column;
    align-items: flex-start;
    gap: 2px;
    pointer-events: none;
  }
  &__line {
    width: 2px;
    height: 12px;
    background: var(--lt-p, #409eff);
  }
  &__label {
    background: var(--lt-p, #409eff);
    color: #fff;
    font-size: 10px;
    padding: 1px 5px;
    border-radius: 2px;
    white-space: nowrap;
    line-height: 1.4;
    font-family: var(--lt-font);
    max-width: 120px;
    overflow: hidden;
    text-overflow: ellipsis;
  }
}
</style>
