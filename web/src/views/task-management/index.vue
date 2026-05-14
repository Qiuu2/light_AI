<template>
  <div class="light-page">
    <div class="page-head">
      <div>
        <h2>任务管理</h2>
        <p>查看快捷任务，执行或停止已有任务。</p>
      </div>
      <el-button size="small" icon="el-icon-refresh" :loading="loading" @click="loadTasks">刷新</el-button>
    </div>

    <el-card shadow="never" class="table-card">
      <el-table v-loading="loading" :data="taskRows" border size="small" empty-text="暂无任务数据">
        <el-table-column type="index" width="48" />
        <el-table-column label="任务ID" width="110">
          <template slot-scope="{ row }">{{ taskId(row) || '-' }}</template>
        </el-table-column>
        <el-table-column label="任务名称" min-width="180">
          <template slot-scope="{ row }">{{ row.taskname || row.name || row.title || '-' }}</template>
        </el-table-column>
        <el-table-column label="播放时间" width="130">
          <template slot-scope="{ row }">{{ row.playtime || row.time || '-' }}</template>
        </el-table-column>
        <el-table-column label="状态" width="110">
          <template slot-scope="{ row }">
            <el-tag size="mini">{{ row.status || row.state || row.enableordis || '未知' }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="原始字段" min-width="260">
          <template slot-scope="{ row }">
            <span class="raw-preview">{{ compactRow(row) }}</span>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="160" fixed="right">
          <template slot-scope="{ row }">
            <el-button type="text" size="mini" :loading="busyId === `run-${taskId(row)}`" @click="execute(row)">执行</el-button>
            <el-button type="text" size="mini" class="danger-link" :loading="busyId === `stop-${taskId(row)}`" @click="stop(row)">停止</el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-card>

    <el-card v-if="lastRaw" shadow="never" class="raw-card">
      <div slot="header">最近一次接口响应</div>
      <pre>{{ lastRaw }}</pre>
    </el-card>
  </div>
</template>

<script>
import { executeLightTask, fetchLightTasks, stopLightTask } from '@/api/lightService'

function listFromPayload(payload) {
  if (Array.isArray(payload)) return payload
  if (!payload || typeof payload !== 'object') return []
  if (Array.isArray(payload.data)) return payload.data
  if (payload.data && Array.isArray(payload.data.data)) return payload.data.data
  if (Array.isArray(payload.rows)) return payload.rows
  if (Array.isArray(payload.list)) return payload.list
  return []
}

export default {
  name: 'TaskManagement',
  data() {
    return {
      loading: false,
      busyId: '',
      tasksPayload: null,
      lastRaw: ''
    }
  },
  computed: {
    taskRows() {
      return listFromPayload(this.tasksPayload)
    }
  },
  created() {
    this.loadTasks()
  },
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
      if (!id) return this.$message.warning('未找到任务ID')
      this.busyId = `run-${id}`
      try {
        const resp = await executeLightTask(id)
        this.showResult(resp, '执行请求已提交')
      } catch (err) {
        this.$message.error(this.errorText(err, '执行失败'))
      } finally {
        this.busyId = ''
      }
    },
    async stop(row) {
      const id = this.taskId(row)
      if (!id) return this.$message.warning('未找到任务ID')
      this.busyId = `stop-${id}`
      try {
        const resp = await stopLightTask(id)
        this.showResult(resp, '停止请求已提交')
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
    taskId(row) {
      return String(row.taskid || row.task_id || row.id || '').trim()
    },
    compactRow(row) {
      return JSON.stringify(row).slice(0, 220)
    },
    errorText(err, fallback) {
      return err && err.response && err.response.data && err.response.data.detail
        ? err.response.data.detail
        : fallback
    }
  }
}
</script>

<style scoped>
.light-page {
  padding: 20px;
}
.page-head {
  display: flex;
  justify-content: space-between;
  gap: 16px;
  margin-bottom: 14px;
}
.page-head h2 {
  margin: 0;
  font-size: 22px;
  color: #1f2d3d;
}
.page-head p {
  margin: 6px 0 0;
  color: #606266;
  font-size: 13px;
}
.table-card,
.raw-card {
  border-radius: 8px;
}
.raw-card {
  margin-top: 14px;
}
.raw-card pre {
  margin: 0;
  white-space: pre-wrap;
  word-break: break-word;
  font-size: 12px;
}
.raw-preview {
  display: inline-block;
  max-width: 100%;
  color: #606266;
  font-size: 12px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.danger-link {
  color: #f56c6c;
}
</style>
