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
        :key="'m-' + (t.id || idx)"
        class="lt-timeline__bar"
        :style="{ left: percent(hours(t)) }"
        :title="(t.time || '') + ' ' + (t.name || '')"
      />

      <!-- full: 一条 + 名签 -->
      <div
        v-else
        :key="'f-' + (t.id || idx)"
        class="lt-timeline__event"
        :style="{ left: percent(hours(t)) }"
      >
        <span class="lt-timeline__line" />
        <span class="lt-timeline__label">
          {{ shortTime(t.time) }} {{ t.name || '' }}
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
    hours(t) {
      const time = String((t && t.time) || '00:00:00')
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

  /* full 模式事件 */
  &__event {
    position: absolute;
    top: 22px;
    transform: translateX(-50%);
    display: flex;
    flex-direction: column;
    align-items: center;
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
  }
}
</style>
