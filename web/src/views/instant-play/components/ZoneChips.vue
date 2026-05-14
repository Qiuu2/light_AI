<!--
  ZoneChips — 分区选择 chip 组

  Props:
    value     Array  选中的分区 key 数组 (例如 ['area0', 'area1', ...])
    keys      Array  分区 key (默认 area0~area5)
    labels    Array  显示文本 (默认 分区1 ~ 分区6)
    show-actions Boolean 是否显示"全选/清空"
  Events:
    update:value
-->
<template>
  <div class="lt-zone-chips">
    <span
      v-for="(k, i) in keys"
      :key="k"
      class="lt-chip"
      :class="{ 'is-on': value.includes(k) }"
      @click="toggle(k)"
    >
      <i v-if="value.includes(k)" class="el-icon-check lt-chip__check" />
      {{ labels[i] }}
    </span>
    <template v-if="showActions">
      <el-button type="text" size="mini" class="lt-link" @click="setAll(true)">全选</el-button>
      <el-button type="text" size="mini" class="lt-link lt-link--muted" @click="setAll(false)">清空</el-button>
    </template>
  </div>
</template>

<script>
export default {
  name: 'ZoneChips',
  props: {
    value: { type: Array, default: () => [] },
    keys: { type: Array, default: () => ['area0', 'area1', 'area2', 'area3', 'area4', 'area5'] },
    labels: { type: Array, default: () => ['分区1', '分区2', '分区3', '分区4', '分区5', '分区6'] },
    showActions: { type: Boolean, default: true }
  },
  methods: {
    toggle(k) {
      const next = this.value.slice()
      const idx = next.indexOf(k)
      if (idx === -1) next.push(k)
      else next.splice(idx, 1)
      this.$emit('update:value', next)
    },
    setAll(on) {
      const next = on
        ? this.keys.slice()
        : this.value.filter((v) => !this.keys.includes(v))
      // 保留 keys 外的 area（功放/外控）不被清掉
      const outside = this.value.filter((v) => !this.keys.includes(v))
      this.$emit('update:value', on ? [...outside, ...this.keys] : outside)
    }
  }
}
</script>

<style lang="scss" scoped>
.lt-zone-chips {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  align-items: center;
}
.lt-chip {
  display: inline-flex;
  align-items: center;
  gap: 3px;
  padding: 4px 11px;
  border-radius: var(--lt-r);
  border: 1px solid var(--lt-line-strong);
  background: #fff;
  color: var(--lt-t2);
  font-size: 12px;
  cursor: pointer;
  user-select: none;
  transition: border-color .12s, color .12s, background .12s;
  line-height: 1.4;

  &:hover { border-color: var(--lt-p); color: var(--lt-p); }
  &.is-on {
    background: var(--lt-p-soft);
    border-color: var(--lt-p);
    color: var(--lt-p);
  }
  &__check { font-size: 10px; font-weight: 700; }
}
.lt-link { color: var(--lt-p) !important; }
.lt-link--muted { color: var(--lt-t3) !important; }
</style>
