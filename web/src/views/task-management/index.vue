<!--
  任务管理 — 紧凑表格 + 状态筛选 + 搜索

  接口（不动）:
    fetchLightTasks      GET    /api/light/tasks
    executeLightTask     POST   /api/light/tasks/{id}/execute   (重放)
    stopLightTask        POST   /api/light/tasks/{id}/stop      (停止)
-->
<template>
  <div class="light-page">
    <page-header
      title="任务管理"
      subtitle="查看快捷任务、状态、运行情况；支持搜索与按状态筛选"
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

        <el-table-column label="任务名称" min-width="160">
          <template slot-scope="{ row }">{{ taskName(row) }}</template>
        </el-table-column>

        <el-table-column label="播放时间" width="110">
          <template slot-scope="{ row }">
            <span class="lt-mono">{{ row.playtime || row.time || '-' }}</span>
          </template>
        </el-table-column>

        <el-table-column label="状态" width="100">
          <template slot-scope="{ row }">
            <task-status-tag :status="statusOf(row)" />
          </template>
        </el-table-column>

        <el-table-column label="原始字段" min-width="240">
          <template slot-scope="{ row }">
            <span class="lt-raw">{{ compactRow(row) }}</span>
          </template>
        </el-table-column>

        <el-table-column label="操作" width="140" fixed="right">
          <template slot-scope="{ row }">
            <el-button
              type="text"
              size="mini"
              :loading="busyId === `run-${taskId(row)}`"
              @click="execute(row)"
            >
              <i class="el-icon-video-play" /> 执行
            </el-button>
            <el-button
              type="text"
              size="mini"
              class="lt-danger-link"
              :loading="busyId === `stop-${taskId(row)}`"
              @click="stop(row)"
            >
              <i class="el-icon-video-pause" /> 停止
            </el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-card>

    <el-card v-if="lastRaw" shadow="never" class="lt-raw-card">
      <div slot="header" class="lt-raw-card__header">
        <span>最近一次接口响应</span>
        <el-button type="text" size="mini" @click="lastRaw = ''">关闭</el-button>
      </div>
      <pre class="lt-raw-card__pre">{{ lastRaw }}</pre>
    </el-card>
  </div>
</template>

<script>
import { executeLightTask, fetchLightTasks, stopLightTask } from '@/api/lightService'
import PageHeader from '@/components/PageHeader'
import TaskStatusTag from './components/TaskStatusTag.vue'
import TaskFilterBar from './components/TaskFilterBar.vue'

function listFromPayload(payload) {
  if (Array.isArray(payload)) return payload
  if (!payload || typeof payload !== 'object') return []
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
  components: { PageHeader, TaskStatusTag, TaskFilterBar },

  data() {
    return {
      loading: false,
      busyId: '',
      tasksPayload: null,
      lastRaw: '',
      tab: 'all',
      search: ''
    }
  },

  computed: {
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
        this.tasksPayload = await fetchLightTasks()
      } catch (err) {
        this.$message.error(this.errorText(err, '加载任务失败'))
      } finally {
        this.loading = false
      }
    },
    async execute(row) {
      const id = this.taskId(row)
      if (!id) return this.$message.warning('未找到任务 ID')
      this.busyId = `run-${id}`
      try {
        const resp = await executeLightTask(id)
        this.showResult(resp, '执行请求已提交')
        if (resp && resp.success !== false) await this.loadTasks()
      } catch (err) {
        this.$message.error(this.errorText(err, '执行失败'))
      } finally {
        this.busyId = ''
      }
    },
    async stop(row) {
      const id = this.taskId(row)
      if (!id) return this.$message.warning('未找到任务 ID')
      this.busyId = `stop-${id}`
      try {
        const resp = await stopLightTask(id)
        this.showResult(resp, '停止请求已提交')
        if (resp && resp.success !== false) await this.loadTasks()
      } catch (err) {
        this.$message.error(this.errorText(err, '停止失败'))
      } finally {
        this.busyId = ''
      }
    },
    showResult(resp, fallback) {
      this.lastRaw = JSON.stringify(resp, null, 2)
      const ok = resp && resp.success !== false
      this.$message[ok ? 'success' : 'warning']((resp && resp.message) || fallback)
    },
    taskId(row) { return String(row.taskid || row.task_id || row.id || '').trim() },
    taskName(row) { return row.taskname || row.name || row.title || '-' },
    statusOf(row) { return row.status || row.state || row.enableordis || '' },
    compactRow(row) { return JSON.stringify(row).slice(0, 220) },
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
