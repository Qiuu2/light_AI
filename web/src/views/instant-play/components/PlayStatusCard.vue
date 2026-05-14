<!--
  PlayStatusCard — 即时播放状态卡片
  显示当前播放状态 + 分区状态网格

  Props:
    playing    Boolean  是否正在播放（来自父组件，目前根据最近一次提交结果推断）
    activeZones Array   勾选的分区 key（用于分区状态展示）
    mediaLabel String   已选媒体的展示文本
    terminalLabel String  已选终端
    durationLabel String  时长/次数显示
-->
<template>
  <div class="lt-play-status">
    <el-card shadow="never">
      <div slot="header" class="lt-play-status__h">
        <span>当前状态</span>
      </div>
      <div v-if="playing" class="lt-play-status__live">
        <div class="lt-play-status__live-row">
          <span class="lt-play-status__dot" />
          <span class="lt-play-status__live-text">正在播放</span>
        </div>
        <div class="lt-play-status__kv">
          <div><label>媒体</label><span>{{ mediaLabel || '—' }}</span></div>
          <div><label>终端</label><span>{{ terminalLabel || '—' }}</span></div>
          <div><label>分区</label><span>{{ zoneSummary || '—' }}</span></div>
          <div v-if="durationLabel"><label>规则</label><span>{{ durationLabel }}</span></div>
        </div>
      </div>
      <div v-else class="lt-play-status__idle">
        <div>当前未在播放</div>
        <div class="lt-play-status__hint">填写左侧参数后点击「执行即时播放」</div>
      </div>
    </el-card>

    <el-card shadow="never" class="lt-play-status__zones-card">
      <div slot="header" class="lt-play-status__h">
        <span>分区状态</span>
        <span class="lt-muted lt-tiny">本机 · 6 个分区</span>
      </div>
      <div class="lt-play-status__zones">
        <div
          v-for="i in 6"
          :key="i"
          class="lt-zone-cell"
          :class="zoneClass(i)"
        >
          <div class="lt-zone-cell__label">分区{{ i }}</div>
          <div class="lt-zone-cell__state">{{ zoneState(i) }}</div>
        </div>
      </div>
    </el-card>
  </div>
</template>

<script>
export default {
  name: 'PlayStatusCard',
  props: {
    playing: { type: Boolean, default: false },
    activeZones: { type: Array, default: () => [] },
    mediaLabel: { type: String, default: '' },
    terminalLabel: { type: String, default: '' },
    durationLabel: { type: String, default: '' }
  },
  computed: {
    zoneSummary() {
      const on = [1, 2, 3, 4, 5, 6].filter((i) => this.isZoneOn(i))
      return on.length ? on.map((i) => `分区${i}`).join('、') : ''
    }
  },
  methods: {
    isZoneOn(i) { return this.activeZones.includes('area' + (i - 1)) },
    zoneClass(i) {
      const on = this.isZoneOn(i)
      if (this.playing && on) return 'is-live'
      if (on) return 'is-ready'
      return 'is-off'
    },
    zoneState(i) {
      const on = this.isZoneOn(i)
      if (this.playing && on) return '播放中'
      if (on) return '就绪'
      return '未选'
    }
  }
}
</script>

<style lang="scss" scoped>
.lt-play-status {
  display: flex;
  flex-direction: column;
  gap: 12px;

  &__h {
    display: flex;
    justify-content: space-between;
    align-items: center;
    font-size: 13px;
    font-weight: 600;
    color: var(--lt-t1);
  }

  &__live {
    display: flex;
    flex-direction: column;
    gap: 10px;
  }
  &__live-row {
    display: flex;
    align-items: center;
    gap: 8px;
  }
  &__live-text {
    font-weight: 600;
  }
  &__dot {
    display: inline-block;
    width: 8px;
    height: 8px;
    border-radius: 50%;
    background: var(--lt-ok);
    animation: lt-ps-pulse 1.4s infinite;
  }
  &__kv {
    display: flex;
    flex-direction: column;
    gap: 6px;
    font-size: 12px;
    line-height: 1.6;
    color: var(--lt-t2);

    label {
      display: inline-block;
      width: 48px;
      color: var(--lt-t3);
    }
    span { color: var(--lt-t1); }
  }
  &__idle {
    text-align: center;
    padding: 16px 0;
    color: var(--lt-t3);
    font-size: 13px;
  }
  &__hint {
    margin-top: 4px;
    color: var(--lt-t4);
    font-size: 12px;
  }

  &__zones {
    display: grid;
    grid-template-columns: repeat(3, 1fr);
    gap: 6px;
  }
}

.lt-zone-cell {
  text-align: center;
  padding: 8px 4px;
  border-radius: var(--lt-r);
  border: 1px solid var(--lt-line);
  background: var(--lt-surface-2);

  &__label {
    font-size: 11px;
    color: var(--lt-t3);
  }
  &__state {
    margin-top: 2px;
    font-size: 12px;
    font-weight: 600;
    color: var(--lt-t4);
  }

  &.is-ready {
    background: var(--lt-p-soft);
    border-color: var(--lt-p-line);
    .lt-zone-cell__state { color: var(--lt-p); }
  }
  &.is-live {
    background: var(--lt-ok-soft);
    border-color: var(--lt-ok);
    .lt-zone-cell__state { color: var(--lt-ok); }
  }
}

.lt-muted { color: var(--lt-t3); }
.lt-tiny { font-size: 11px; }

@keyframes lt-ps-pulse {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.4; }
}
</style>
