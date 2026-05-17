<!--
  任务管理 — 只读视图，显示当前启用方案的任务

  接口:
    fetchCurrentLightScheduleTasks  GET  /api/light/current-schedule-tasks
        → 远端 /action/gettaskinfo，仅返回当前启用作息方案下的任务

  说明:
    - 任务的执行/停止/编辑/删除请到「作息管理」页面操作
    - 这里只做查看、搜索、按状态筛选
-->
<template>
  <div class="light-page">
    <page-header
      title="每日任务"
      subtitle="只读视图：当前启用方案下的任务列表（执行 / 停止 / 编辑请到「作息管理」页面）"
    >
      <template #status>
        <el-tag size="small" type="info" effect="plain">
          共 {{ taskRows.length }} 条
        </el-tag>
      </template>
      <el-button size="small" icon="el-icon-refresh" :loading="loading" @click="loadTasks">
        刷新
      </el-button>
    </page-header>

    <!-- 大日期 -->
    <el-card shadow="never" class="lt-date-card">
      <div class="lt-date-display">
        <div class="lt-date-display__label">当前查看日期</div>
        <div class="lt-date-display__main">
          <span class="lt-date-display__month">{{ todayMonth }}月</span>
          <span class="lt-date-display__day">{{ todayDay }}</span>
          <span class="lt-date-display__suffix">日</span>
        </div>
        <div class="lt-date-display__meta">
          <span>{{ todayWeekday }}</span>
          <span class="lt-date-display__sep">·</span>
          <span>{{ taskRows.length ? `${taskRows.length} 个任务` : '当前暂无任务' }}</span>
        </div>
      </div>
    </el-card>

    <!-- 时间线 -->
    <el-card shadow="never" class="lt-timeline-card">
      <div slot="header" class="lt-timeline-card__header">
        <span class="lt-timeline-card__title">时间线</span>
        <span class="lt-timeline-card__count">{{ timelineTasks.length }} 个可见任务</span>
      </div>
      <Timeline :tasks="timelineTasks" mode="full" />
    </el-card>

    <el-card shadow="never">
      <task-filter-bar
        :tab.sync="tab"
        :search.sync="search"
        :counts="counts"
      />

      <el-table
        v-loading="loading"
        :data="filteredRows"
        border
        size="mini"
        empty-text="暂无任务数据"
        class="lt-task-mgmt-table"
      >
        <el-table-column type="index" width="44" />

        <el-table-column label="任务 ID" width="80">
          <template slot-scope="{ row }">
            <span class="lt-mono lt-muted">{{ taskId(row) || '-' }}</span>
          </template>
        </el-table-column>

        <el-table-column label="任务名称" min-width="110" show-overflow-tooltip>
          <template slot-scope="{ row }">{{ taskName(row) }}</template>
        </el-table-column>

        <el-table-column label="播放时间" width="110">
          <template slot-scope="{ row }">
            <span class="lt-mono">{{ row.playtime || row.time || '-' }}</span>
          </template>
        </el-table-column>

        <el-table-column label="音量" width="64" align="center">
          <template slot-scope="{ row }">
            <span class="lt-mono">{{ volumeOf(row) }}</span>
          </template>
        </el-table-column>

        <el-table-column label="分区" width="172">
          <template slot-scope="{ row }">
            <div class="lt-zone-dots">
              <span
                v-for="i in 6"
                :key="'z' + i"
                class="lt-zone-dot"
                :class="{ 'is-on': isZoneOn(row, i - 1) }"
                :title="'分区' + i"
              >{{ i }}</span>
            </div>
          </template>
        </el-table-column>

        <el-table-column label="功放电源" width="84" align="center">
          <template slot-scope="{ row }">
            <el-tag v-if="isAmpOn(row)" size="mini" type="success" effect="dark">开</el-tag>
            <span v-else class="lt-muted">—</span>
          </template>
        </el-table-column>

        <el-table-column label="外控电源" width="84" align="center">
          <template slot-scope="{ row }">
            <el-tag v-if="isExtOn(row)" size="mini" type="warning" effect="dark">开</el-tag>
            <span v-else class="lt-muted">—</span>
          </template>
        </el-table-column>

        <el-table-column label="预开" width="72" align="center">
          <template slot-scope="{ row }">
            <span class="lt-mono">{{ preStartOf(row) }}<span class="lt-muted">s</span></span>
          </template>
        </el-table-column>

        <el-table-column label="迟关" width="72" align="center">
          <template slot-scope="{ row }">
            <span class="lt-mono">{{ preStopOf(row) }}<span class="lt-muted">s</span></span>
          </template>
        </el-table-column>

        <el-table-column label="星期" width="148">
          <template slot-scope="{ row }">
            <div class="lt-day-dots">
              <span
                v-for="(d, i) in dayLabels"
                :key="'d' + i"
                class="lt-day-dot"
                :class="{ 'is-on': isDayOn(row, i) }"
                :title="dayFull[i]"
              >{{ d }}</span>
            </div>
          </template>
        </el-table-column>

        <el-table-column label="状态" width="100">
          <template slot-scope="{ row }">
            <task-status-tag :status="statusOf(row)" />
          </template>
        </el-table-column>

      </el-table>
    </el-card>

  </div>
</template>

<script>
import { fetchCurrentLightScheduleTasks } from '@/api/lightService'
import PageHeader from '@/components/PageHeader'
import TaskStatusTag from './components/TaskStatusTag.vue'
import TaskFilterBar from './components/TaskFilterBar.vue'
import Timeline from '@/views/task-scheduler/components/Timeline.vue'

function listFromPayload(payload) {
  if (Array.isArray(payload)) return payload
  if (!payload || typeof payload !== 'object') return []
  // current-schedule-tasks 的返回结构是 { data: { tasks: [...] } }
  if (payload.data && Array.isArray(payload.data.tasks)) return payload.data.tasks
  if (Array.isArray(payload.data)) return payload.data
  if (payload.data && Array.isArray(payload.data.data)) return payload.data.data
  if (Array.isArray(payload.rows)) return payload.rows
  if (Array.isArray(payload.list)) return payload.list
  return []
}

const RUNNING_PATTERNS = ['运行', '播放', 'running', 'playing', 'active', '执行中']
const FAILED_PATTERNS = ['失败', 'fail', 'error', '异常']
const ENDED_PATTERNS = ['结束', 'done', 'finished', 'completed', 'idle', '已停止']

function bucket(status) {
  const s = String(status || '').toLowerCase()
  if (RUNNING_PATTERNS.some((p) => s.includes(p.toLowerCase()))) return 'running'
  if (FAILED_PATTERNS.some((p) => s.includes(p.toLowerCase()))) return 'failed'
  if (ENDED_PATTERNS.some((p) => s.includes(p.toLowerCase()))) return 'done'
  if (s === '1') return 'running'
  if (s === '0') return 'done'
  return 'other'
}

export default {
  name: 'TaskManagement',
  components: { PageHeader, TaskStatusTag, TaskFilterBar, Timeline },

  data() {
    return {
      loading: false,
      tasksPayload: null,
      tab: 'all',
      search: '',
      now: new Date(),
      dayLabels: ['一', '二', '三', '四', '五', '六', '日'],
      dayFull: ['周一', '周二', '周三', '周四', '周五', '周六', '周日'],
      // 远端可能用 mon/tue/wed/thu/fri/sat/sun，归一化后可能叫 day0..day6。两者都认。
      dayKeyMap: [
        ['mon', 'day0'],
        ['tue', 'day1'],
        ['wed', 'day2'],
        ['thu', 'day3'],
        ['fri', 'day4'],
        ['sat', 'day5'],
        ['sun', 'day6']
      ]
    }
  },

  computed: {
    todayMonth() { return this.now.getMonth() + 1 },
    todayDay() { return this.now.getDate() },
    todayWeekday() {
      const names = ['周日', '周一', '周二', '周三', '周四', '周五', '周六']
      return names[this.now.getDay()]
    },
    timelineTasks() {
      return this.taskRows
        .map((row, idx) => ({
          id: this.taskId(row) || `t${idx}`,
          name: this.taskName(row),
          time: String(row.playtime || row.time || '').trim()
        }))
        .filter((t) => t.time)
    },
    taskRows() {
      return listFromPayload(this.tasksPayload)
    },
    counts() {
      const out = { all: this.taskRows.length, running: 0, failed: 0, done: 0 }
      this.taskRows.forEach((r) => {
        const b = bucket(this.statusOf(r))
        if (b in out) out[b] += 1
      })
      return out
    },
    filteredRows() {
      const q = String(this.search || '').trim().toLowerCase()
      return this.taskRows.filter((r) => {
        if (this.tab !== 'all' && bucket(this.statusOf(r)) !== this.tab) return false
        if (!q) return true
        const id = String(this.taskId(r) || '').toLowerCase()
        const name = String(this.taskName(r) || '').toLowerCase()
        return id.includes(q) || name.includes(q)
      })
    }
  },

  created() { this.loadTasks() },

  methods: {
    async loadTasks() {
      this.loading = true
      try {
        this.tasksPayload = await fetchCurrentLightScheduleTasks()
      } catch (err) {
        this.$message.error(this.errorText(err, '加载任务失败'))
      } finally {
        this.loading = false
      }
    },
    taskId(row) { return String(row.taskid || row.task_id || row.id || '').trim() },
    taskName(row) { return row.taskname || row.name || row.title || '-' },
    statusOf(row) { return row.status || row.state || row.enableordis || '' },
    isDayOn(row, idx) {
      if (!row || idx < 0 || idx >= this.dayKeyMap.length) return false
      const pair = this.dayKeyMap[idx]
      for (const key of pair) {
        const v = row[key]
        if (v === '1' || v === 1 || v === true) return true
      }
      return false
    },
    isZoneOn(row, idx) {
      // idx: 0..5 对应分区1-6（即 area0-area5）
      if (!row || idx < 0 || idx > 5) return false
      // 1) 优先看独立字段 area0..area5
      const direct = row['area' + idx]
      if (direct === '1' || direct === 1 || direct === true) return true
      // 2) 回退：远端原始返回的 area 是个 "11111110" 这种 8 位字符串
      const areaStr = String(row.area || '')
      if (areaStr.length >= idx + 1) {
        return areaStr.charAt(idx) === '1'
      }
      return false
    },
    isAmpOn(row) {
      // area6 = 功放电源
      if (!row) return false
      const direct = row.area6
      if (direct === '1' || direct === 1 || direct === true) return true
      const areaStr = String(row.area || '')
      return areaStr.length >= 7 && areaStr.charAt(6) === '1'
    },
    isExtOn(row) {
      // area7 = 外控电源
      if (!row) return false
      const direct = row.area7
      if (direct === '1' || direct === 1 || direct === true) return true
      const areaStr = String(row.area || '')
      return areaStr.length >= 8 && areaStr.charAt(7) === '1'
    },
    volumeOf(row) {
      if (!row) return '-'
      const v = row.volume
      if (v === undefined || v === null || v === '') return '-'
      return String(v)
    },
    preStartOf(row) {
      // 远端原始字段：Pre-Start；归一化后可能叫 pretime
      if (!row) return '-'
      const v = row['Pre-Start'] ?? row.preStart ?? row.pretime
      if (v === undefined || v === null || v === '') return '-'
      return String(v)
    },
    preStopOf(row) {
      // 远端原始字段：Pre-Stop；归一化后可能叫 delaytime
      if (!row) return '-'
      const v = row['Pre-Stop'] ?? row.preStop ?? row.delaytime
      if (v === undefined || v === null || v === '') return '-'
      return String(v)
    },
    errorText(err, fallback) {
      return err && err.response && err.response.data && err.response.data.detail
        ? err.response.data.detail
        : fallback
    }
  }
}
</script>

<style lang="scss" scoped>
.lt-task-mgmt-table {
  ::v-deep .el-table__cell { font-size: 12px; }
}
.lt-mono { font-family: var(--lt-mono); }
.lt-muted { color: var(--lt-t3); }
.lt-raw {
  display: inline-block;
  max-width: 100%;
  color: var(--lt-t3);
  font-size: 12px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  font-family: var(--lt-mono);
}
.lt-danger-link { color: var(--lt-danger) !important; }

/* 分区 + 星期色块（跟作息管理 TaskTable 风格一致：分区深蓝、星期橙色） */
.lt-zone-dots,
.lt-day-dots {
  display: inline-flex;
  gap: 2px;
}
.lt-zone-dot,
.lt-day-dot {
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
}
.lt-zone-dot.is-on {
  background: #409eff !important;
  border-color: #409eff !important;
  color: #fff !important;
  box-shadow: 0 0 0 1px rgba(64, 158, 255, 0.18);
}
.lt-day-dot.is-on {
  background: #67c23a !important;
  border-color: #67c23a !important;
  color: #fff !important;
  box-shadow: 0 0 0 1px rgba(103, 194, 58, 0.18);
}

.lt-date-card {
  margin-bottom: 12px;
}
.lt-date-display {
  display: flex;
  flex-direction: column;
  align-items: center;
  padding: 16px 0 8px;
  gap: 6px;

  &__label {
    font-size: 12px;
    color: var(--lt-t3);
    letter-spacing: 1px;
  }
  &__main {
    display: flex;
    align-items: baseline;
    gap: 6px;
    line-height: 1;
  }
  &__month {
    font-size: 24px;
    font-weight: 600;
    color: var(--lt-t3);
  }
  &__day {
    font-size: 72px;
    font-weight: 700;
    color: var(--lt-t1);
    line-height: 0.9;
    letter-spacing: -2px;
  }
  &__suffix {
    font-size: 24px;
    font-weight: 600;
    color: var(--lt-t3);
  }
  &__meta {
    display: flex;
    align-items: center;
    gap: 6px;
    font-size: 13px;
    color: var(--lt-t2);
  }
  &__sep {
    color: var(--lt-line-strong);
  }
}

.lt-timeline-card {
  margin-bottom: 12px;

  &__header {
    display: flex;
    justify-content: space-between;
    align-items: center;
  }
  &__title {
    font-size: 14px;
    font-weight: 600;
    color: var(--lt-t1);
  }
  &__count {
    font-size: 12px;
    color: var(--lt-t3);
  }
}

.lt-raw-card {
  margin-top: 12px;

  &__header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    font-size: 13px;
  }
  &__pre {
    margin: 0;
    white-space: pre-wrap;
    word-break: break-word;
    font-size: 12px;
    font-family: var(--lt-mono);
    color: var(--lt-t2);
    max-height: 280px;
    overflow: auto;
  }
}
</style>
