<template>
  <div class="page">
    <div class="page-header">
      <div>
        <h2>采播管理</h2>
        <p>数据由“任务编排”同步，包含启用状态与音量。</p>
      </div>
      <el-button size="small" icon="el-icon-refresh" @click="loadData">刷新</el-button>
    </div>
    <el-table :data="livecasts" border size="small">
      <el-table-column prop="name" label="采播名称" />
      <el-table-column prop="volume" label="音量" width="80" />
      <el-table-column prop="status" label="状态" width="90">
        <template slot-scope="{ row }">
          <el-tag :type="tagType(row.status)" size="mini">{{ row.status }}</el-tag>
        </template>
      </el-table-column>
    </el-table>
  </div>
</template>

<script>
import { fetchLivecasts } from '@/api/dataService'
import { offAssistantRefresh, onAssistantRefresh } from '@/utils/assistantRefreshBus'

export default {
  name: 'LiveCast',
  data() {
    return {
      livecasts: []
    }
  },
  created() {
    this.loadData()
    onAssistantRefresh(this.handleAssistantRefresh)
  },
  beforeDestroy() {
    offAssistantRefresh(this.handleAssistantRefresh)
  },
  methods: {
    async loadData(silent = false) {
      try {
        const payload = await fetchLivecasts()
        this.livecasts = Array.isArray(payload?.livecasts) ? payload.livecasts : []
        if (!silent) {
          this.$message.success('已从后端同步采播数据')
        }
      } catch (err) {
        this.livecasts = []
        this.$message.error('加载采播数据失败，请检查后端接口')
      }
    },
    handleAssistantRefresh(payload = {}) {
      if (String(payload?.runtime_scope || '').trim() === 'temp_task') return
      this.loadData(true)
    },
    tagType(status) {
      if (status === '执行中' || status === '启用') return 'success'
      if (status === '暂停') return 'warning'
      if (status === '停用' || status === '停止') return ''
      return 'info'
    }
  }
}
</script>

<style lang="scss" scoped>
.page {
  padding: 24px;
  background: #f5f7fb;
  min-height: 100%;
}

.page-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 12px;

  h2 {
    margin: 0;
    color: #1f2d3d;
  }

  p {
    margin: 4px 0 0;
    color: #5e6d82;
    font-size: 13px;
  }
}
</style>
