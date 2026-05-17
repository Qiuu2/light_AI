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

      <el-table-column label="任务名称" min-width="110" show-overflow-tooltip>
        <template slot-scope="{ row }">{{ taskName(row) }}</template>
      </el-table-column>

      <el-table-column label="播放时间" width="92">
        <template slot-scope="{ row }">
          <span class="lt-mono">{{ timeText(row) }}</span>
        </template>
      </el-table-column>

      <el-table-column label="时长" width="86">
        <template slot-scope="{ row }">
          <span class="lt-mono">{{ durationText(row) }}</span>
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

      <el-table-column label="操作" width="186" fixed="right">
        <template slot-scope="{ row }">
          <div class="lt-action-group">
            <el-tooltip content="执行" placement="top">
              <el-button
                circle
                plain
                type="success"
                size="mini"
                icon="el-icon-video-play"
                :loading="busyId === ('run-' + taskId(row))"
                @click="$emit('execute', row)"
              />
            </el-tooltip>
            <el-tooltip content="停止" placement="top">
              <el-button
                circle
                plain
                type="warning"
                size="mini"
                icon="el-icon-video-pause"
                :loading="busyId === ('stop-' + taskId(row))"
                @click="$emit('stop', row)"
              />
            </el-tooltip>
            <el-tooltip content="编辑" placement="top">
              <el-button
                circle
                plain
                type="primary"
                size="mini"
                icon="el-icon-edit"
                @click="$emit('edit', row)"
              />
            </el-tooltip>
            <el-tooltip content="删除" placement="top">
              <el-button
                circle
                plain
                type="danger"
                size="mini"
                icon="el-icon-delete"
                @click="$emit('delete', row)"
              />
            </el-tooltip>
          </div>
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
    error: { type: String, default: '' },
    busyId: { type: String, default: '' }
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
      if (v !== undefined && v !== null && v !== '') {
        return String(v) === '1'
      }
      // 兼容 schedules / opensech 返回的格式：
      // - 没有 area0..area7 单独字段，只有 area="11111110" 这种 8 位字符串
      const areaMatch = /^area([0-7])$/.exec(String(key || ''))
      if (areaMatch) {
        const idx = Number(areaMatch[1])
        const areaStr = String(row.area || '')
        if (areaStr.length >= idx + 1) {
          return areaStr.charAt(idx) === '1'
        }
      }
      return false
    },
    isDayOn(row, idx) {
      // 兼容两种字段格式：远端归一化后 day0-6，远端原始 mon/tue/.../sun
      if (this.isOn(row, 'day' + idx)) return true
      const remoteKeys = ['mon', 'tue', 'wed', 'thu', 'fri', 'sat', 'sun']
      const key = remoteKeys[idx]
      return key ? this.isOn(row, key) : false
    },
    randomOn(row) {
      // 远端原始字段叫 rand，归一化后可能叫 random
      return this.isOn(row, 'random') || this.isOn(row, 'rand')
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
  width: 18px;
  height: 18px;
  border-radius: 3px;
  font-size: 11px;
  font-weight: 600;
  line-height: 16px;
  text-align: center;
  background: #f5f7fa;
  border: 1px solid #c0c4cc;
  color: #909399;
  user-select: none;

  /* !important 防止被 element-ui 表格的 cell 样式覆盖 */
  &.is-on {
    background: #409eff !important;
    border-color: #409eff !important;
    color: #fff !important;
    box-shadow: 0 0 0 1px rgba(64, 158, 255, 0.18);
  }
  &.lt-dot-cell--day.is-on {
    background: #67c23a !important;
    border-color: #67c23a !important;
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

/* 操作列 — 4 个圆形 icon 按钮 */
.lt-action-group {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  white-space: nowrap;

  ::v-deep .el-button.is-circle {
    width: 28px;
    height: 28px;
    padding: 0;
    font-size: 13px;
  }
  ::v-deep .el-button + .el-button {
    margin-left: 0;
  }

  &__sep {
    display: inline-block;
    width: 1px;
    height: 12px;
    background: var(--lt-line-strong);
    margin: 0 6px;
  }
}
.lt-muted {
  color: var(--lt-t4);
}
.lt-mono {
  font-family: var(--lt-mono);
}
</style>
