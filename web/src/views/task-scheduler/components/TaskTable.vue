<!--
  TaskTable — 紧凑任务表格

  把现有 row 里的字段渲染成色块组：
    分区: area0-area5 → 6 个 14×14 色块
    电源: area6 (功放) / area7 (外控) → 两个小 tag
    星期: day0-day6 → 7 个色块
    随机: random === '1' ? ✓ : —

  Props:
    tasks   Array   原始任务列表
    loading Boolean 加载中
    error   String  加载错误信息
  Events:
    edit(row)
    delete(row)
-->
<template>
  <div class="lt-task-table">
    <el-alert
      v-if="error"
      :title="error"
      type="warning"
      show-icon
      :closable="false"
      class="lt-task-table__alert"
    />

    <el-table
      v-if="!error"
      v-loading="loading"
      :data="tasks"
      border
      size="mini"
      empty-text="该作息暂无任务"
    >
      <el-table-column label="ID" width="68">
        <template slot-scope="{ row }">
          <span class="lt-mono lt-muted">{{ taskId(row) || '-' }}</span>
        </template>
      </el-table-column>

      <el-table-column label="任务名称" min-width="140">
        <template slot-scope="{ row }">{{ taskName(row) }}</template>
      </el-table-column>

      <el-table-column label="播放时间" width="92">
        <template slot-scope="{ row }">
          <span class="lt-mono">{{ timeText(row) }}</span>
        </template>
      </el-table-column>

      <el-table-column label="时长" width="86">
        <template slot-scope="{ row }">
          <span class="lt-mono lt-muted">{{ durationText(row) }}</span>
        </template>
      </el-table-column>

      <el-table-column label="音量" width="60" align="right">
        <template slot-scope="{ row }">
          <span class="lt-mono">{{ volumeText(row) }}</span>
        </template>
      </el-table-column>

      <el-table-column label="分区" width="124">
        <template slot-scope="{ row }">
          <div class="lt-cell-dots">
            <span
              v-for="i in 6"
              :key="'z' + i"
              class="lt-dot-cell"
              :class="{ 'is-on': isOn(row, 'area' + (i - 1)) }"
              :title="'分区' + i"
            >{{ i }}</span>
          </div>
        </template>
      </el-table-column>

      <el-table-column label="电源" width="92">
        <template slot-scope="{ row }">
          <el-tag
            v-if="isOn(row, 'area6')"
            size="mini"
            effect="plain"
            type="info"
            class="lt-cell-tag"
          >功放</el-tag>
          <el-tag
            v-if="isOn(row, 'area7')"
            size="mini"
            effect="plain"
            class="lt-cell-tag"
          >外控</el-tag>
          <span v-if="!isOn(row, 'area6') && !isOn(row, 'area7')" class="lt-muted">—</span>
        </template>
      </el-table-column>

      <el-table-column label="星期" width="138">
        <template slot-scope="{ row }">
          <div class="lt-cell-dots">
            <span
              v-for="(d, i) in dayLabels"
              :key="'d' + i"
              class="lt-dot-cell lt-dot-cell--day"
              :class="{ 'is-on': isDayOn(row, i) }"
              :title="dayFull[i]"
            >{{ d }}</span>
          </div>
        </template>
      </el-table-column>

      <el-table-column label="随机" width="54" align="center">
        <template slot-scope="{ row }">
          <span :class="randomOn(row) ? 'lt-check-on' : 'lt-muted'">
            {{ randomOn(row) ? '✓' : '—' }}
          </span>
        </template>
      </el-table-column>

      <el-table-column label="操作" width="100" fixed="right">
        <template slot-scope="{ row }">
          <el-button type="text" size="mini" @click="$emit('edit', row)">
            <i class="el-icon-edit" />
          </el-button>
          <el-button type="text" size="mini" class="lt-danger-link" @click="$emit('delete', row)">
            <i class="el-icon-delete" />
          </el-button>
        </template>
      </el-table-column>
    </el-table>
  </div>
</template>

<script>
export default {
  name: 'TaskTable',
  props: {
    tasks: { type: Array, default: () => [] },
    loading: { type: Boolean, default: false },
    error: { type: String, default: '' }
  },
  data() {
    return {
      dayLabels: ['一', '二', '三', '四', '五', '六', '日'],
      dayFull: ['周一', '周二', '周三', '周四', '周五', '周六', '周日']
    }
  },
  methods: {
    dataAt(row, idx) {
      return row && Array.isArray(row.data) ? row.data[idx] : ''
    },
    taskId(row) {
      return row && (row.taskid || row.task_id || row.id || '')
    },
    taskName(row) {
      return (row && (row.taskname || row.name || row.title || this.dataAt(row, 0))) || '-'
    },
    timeText(row) {
      if (!row) return '-'
      if (row.playtime) return row.playtime
      if (row.time) return row.time
      const d = this.dataAt(row, 1)
      if (d) return d
      const h = row.playhour
      const m = row.playminute
      const s = row.playsecond
      if (h === undefined && m === undefined && s === undefined) return '-'
      return `${String(h || 0).padStart(2, '0')}:${String(m || 0).padStart(2, '0')}:${String(s || 0).padStart(2, '0')}`
    },
    durationText(row) {
      if (!row) return '-'
      // 优先 duration / playlength, 否则按 timehour:timeminute:timesecond 组合
      if (row.duration) return row.duration
      if (row.playlength) return row.playlength
      const d2 = this.dataAt(row, 2)
      if (d2) return d2
      const h = row.timehour
      const m = row.timeminute
      const s = row.timesecond
      if (h === undefined && m === undefined && s === undefined) return '-'
      return `${String(h || 0).padStart(2, '0')}:${String(m || 0).padStart(2, '0')}:${String(s || 0).padStart(2, '0')}`
    },
    volumeText(row) {
      if (!row) return '-'
      const v = row.volume !== undefined && row.volume !== null && row.volume !== ''
        ? row.volume
        : this.dataAt(row, 4)
      return v === undefined || v === null || v === '' ? '-' : v
    },
    isOn(row, key) {
      if (!row) return false
      const v = row[key]
      if (v === undefined || v === null || v === '') return false
      return String(v) === '1'
    },
    isDayOn(row, idx) {
      return this.isOn(row, 'day' + idx)
    },
    randomOn(row) {
      return this.isOn(row, 'random')
    }
  }
}
</script>

<style lang="scss" scoped>
.lt-task-table {
  &__alert {
    margin-bottom: 10px;
  }
}

/* 色块组单元格 */
.lt-cell-dots {
  display: inline-flex;
  gap: 2px;
}
.lt-dot-cell {
  width: 14px;
  height: 14px;
  border-radius: 2px;
  font-size: 9px;
  line-height: 12px;
  text-align: center;
  background: var(--lt-surface-hover);
  border: 1px solid var(--lt-line);
  color: var(--lt-t4);
  user-select: none;

  &.is-on {
    background: var(--lt-p);
    border-color: var(--lt-p);
    color: #fff;
  }
  &.lt-dot-cell--day.is-on {
    background: var(--lt-t2);
    border-color: var(--lt-t2);
  }
}

.lt-cell-tag {
  margin-right: 4px;
}
.lt-check-on {
  color: var(--lt-ok);
  font-weight: 600;
}
.lt-danger-link {
  color: var(--lt-danger) !important;
}
.lt-muted {
  color: var(--lt-t4);
}
.lt-mono {
  font-family: var(--lt-mono);
}
</style>
