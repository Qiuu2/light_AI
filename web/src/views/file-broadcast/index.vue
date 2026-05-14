<template>
  <div class="page">
    <div class="page-header">
      <div>
        <h2>文件广播</h2>
        <p>数据由“任务编排”保存上传，支持紧急状态和音量查看。</p>
      </div>
      <el-button size="small" icon="el-icon-refresh" @click="loadData">刷新</el-button>
    </div>
    <el-table :data="broadcasts" border size="small">
      <el-table-column prop="name" label="任务名称" />
      <el-table-column prop="volume" label="音量" width="80" />
      <el-table-column prop="status" label="状态" width="90">
        <template slot-scope="{ row }">
          <el-tag :type="tagType(row)" size="mini">
            {{ row.status }}
          </el-tag>
          <el-tag v-if="row.emergency" type="danger" size="mini">紧急</el-tag>
        </template>
      </el-table-column>
    </el-table>
  </div>
</template>

<script>
import { fetchBroadcasts } from '@/api/dataService'
import { offAssistantRefresh, onAssistantRefresh } from '@/utils/assistantRefreshBus'

export default {
  name: 'FileBroadcast',
  data() {
    return {
      broadcasts: []
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
        const payload = await fetchBroadcasts()
        this.broadcasts = Array.isArray(payload?.broadcasts) ? payload.broadcasts : []
        if (!silent) {
          this.$message.success('已从后端同步文件广播')
        }
      } catch (err) {
        this.broadcasts = []
        this.$message.error('加载文件广播失败，请检查后端接口')
      }
    },
    handleAssistantRefresh(payload = {}) {
      if (String(payload?.runtime_scope || '').trim() === 'temp_task') return
      this.loadData(true)
    },
    tagType(row) {
      if (row.emergency || row.status === '紧急') return 'danger'
      if (row.status === '执行中' || row.status === '启用') return 'success'
      if (row.status === '暂停') return 'warning'
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
