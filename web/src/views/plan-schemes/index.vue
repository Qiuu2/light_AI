<template>
  <div class="page">
    <div class="page-header">
      <div>
        <h2>作息方案</h2>
        <p v-if="hasPlanDraft">当前显示本地草稿，仅当前浏览器可见。正式上传请前往“任务编排中心”。</p>
        <p v-else>数据来自“任务编排”保存的方案。需要修改请前往任务编排页调整。</p>
      </div>
      <div class="header-actions">
        <el-badge v-if="hasPlanDraft" :value="planDraftCount" type="warning">
          <el-tag size="small" type="warning" effect="dark">作息方案草稿</el-tag>
        </el-badge>
        <el-button
          v-if="hasPlanDraft"
          size="small"
          type="warning"
          plain
          icon="el-icon-delete"
          @click="discardPlanDraft"
        >放弃草稿</el-button>
        <el-button size="small" icon="el-icon-refresh" @click="loadData">刷新</el-button>
      </div>
    </div>
    <el-table :data="visiblePlans" border size="small">
      <el-table-column type="expand">
        <template slot-scope="{ row }">
          <el-table :data="row.tasks" size="mini" border>
            <el-table-column type="index" width="40" />
            <el-table-column label="任务名" min-width="140">
              <template slot-scope="{ row: task }">
                <span>{{ task.customName || task.audio || '—' }}</span>
                <el-tag v-if="task.is_once_ephemeral" size="mini" type="warning">一次性</el-tag>
                <el-tag v-if="task.is_once_ephemeral && task.once_action_label" size="mini" type="info">{{ task.once_action_label }}</el-tag>
                <el-tag v-if="task.is_once_ephemeral && task.once_date" size="mini">{{ task.once_date }}</el-tag>
              </template>
            </el-table-column>
            <el-table-column prop="audio" label="音频资源" />
            <el-table-column prop="time" label="时间" width="100" />
            <el-table-column prop="duration" label="时长(秒)" width="90" />
            <el-table-column prop="loop" label="循环" width="70" />
            <el-table-column label="周期" min-width="140">
              <template slot-scope="{ row: task }">
                {{ (task.weekdays || []).join('，') }}
              </template>
            </el-table-column>
            <el-table-column label="时效" min-width="160">
              <template slot-scope="{ row: task }">
                {{ (task.dateRange || []).join(' 至 ') }}
              </template>
            </el-table-column>
            <el-table-column prop="location" label="终端地点" />
            <el-table-column prop="volume" label="音量" width="80" />
          </el-table>
        </template>
      </el-table-column>
      <el-table-column prop="name" label="方案名称" />
      <el-table-column label="任务数" width="80">
        <template slot-scope="{ row }">
          {{ planTaskCountLabel(row) }}
        </template>
      </el-table-column>
      <el-table-column label="临时变更" min-width="150">
        <template slot-scope="{ row }">
          <el-button
            v-if="planOnceSummary(row).count"
            type="text"
            size="mini"
            @click="openPlanOncePanel(row)"
          >
            临时变更 {{ planOnceSummary(row).count }} 条
            <span v-if="planOnceSummary(row).dateLabel"> · {{ planOnceSummary(row).dateLabel }}</span>
          </el-button>
          <span v-else class="muted-text">无</span>
        </template>
      </el-table-column>
      <el-table-column prop="volume" label="音量" width="80" />
      <el-table-column prop="status" label="状态" width="90">
        <template slot-scope="{ row }">
          <el-tag :type="row.status === '启用' ? 'success' : 'info'" size="mini">{{ row.status }}</el-tag>
        </template>
      </el-table-column>
    </el-table>
  </div>
</template>

<script>
import { fetchBroadcastSchedules, fetchTaskOverrides } from '@/api/dataService'
import { offAssistantRefresh, onAssistantRefresh } from '@/utils/assistantRefreshBus'
import { summarizeOnceSpecs } from '@/utils/onceTaskSpecs'
import {
  clearPlanDraft,
  discardInvalidPlanDrafts,
  hasSchedulerDirtyScope,
  loadSchedulerDrafts,
  recoverInvalidPlanDrafts
} from '@/utils/schedulerStorage'

const WEEKDAY_ORDER = ['周一', '周二', '周三', '周四', '周五', '周六', '周日']

export default {
  name: 'PlanSchemes',
  data() {
    return {
      plans: [],
      taskOverrides: [],
      hidePlanCount: 0,
      draftState: loadSchedulerDrafts(),
      invalidPlanDraftPromptKey: ''
    }
  },
  computed: {
    visiblePlans() {
      const list = Array.isArray(this.plans) ? this.plans : []
      if (!this.hidePlanCount) return list
      return list.slice(this.hidePlanCount)
    },
    hasPlanDraft() {
      return hasSchedulerDirtyScope('plans', this.draftState)
    },
    planDraftCount() {
      const dirtyIds = Array.isArray(this.draftState?.planDirtyIds) ? this.draftState.planDirtyIds : []
      const deletedIds = Array.isArray(this.draftState?.planDeletedIds) ? this.draftState.planDeletedIds : []
      return new Set([...dirtyIds, ...deletedIds].map((item) => String(item || '').trim()).filter((item) => item)).size
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
        this.draftState = loadSchedulerDrafts()
        this.$nextTick(() => {
          this.promptInvalidPlanDrafts(this.draftState)
        })
        const [payload, overridesPayload] = await Promise.all([
          fetchBroadcastSchedules(),
          fetchTaskOverrides()
        ])
        this.taskOverrides = Array.isArray(overridesPayload?.overrides) ? overridesPayload.overrides : []
        this.plans = this.hasPlanDraft
          ? this.mapDraftPlans(this.draftState.plans)
          : this.mapPlans(payload)
        if (!silent) {
          this.$message.success(this.hasPlanDraft ? '当前显示本地草稿，正式数据已同步' : '已从后端同步方案数据')
        }
      } catch (err) {
        this.taskOverrides = []
        this.plans = this.hasPlanDraft ? this.mapDraftPlans(this.draftState.plans) : []
        this.$message.error(this.hasPlanDraft ? '后端加载失败，当前仅显示本地草稿' : '加载作息方案失败，请检查后端接口')
      }
    },
    invalidPlanDraftSummary(draftState = this.draftState) {
      const invalidPlans = Array.isArray(draftState?.invalidPlanDrafts) ? draftState.invalidPlanDrafts.length : 0
      const invalidBasePlans = Array.isArray(draftState?.invalidPlanBaseSnapshot) ? draftState.invalidPlanBaseSnapshot.length : 0
      return {
        invalidPlans,
        invalidBasePlans,
        total: invalidPlans + invalidBasePlans
      }
    },
    refreshPlansFromDraftState() {
      this.plans = this.hasPlanDraft
        ? this.mapDraftPlans(this.draftState.plans)
        : this.plans
    },
    async promptInvalidPlanDrafts(draftState = this.draftState) {
      const summary = this.invalidPlanDraftSummary(draftState)
      if (!summary.total) {
        this.invalidPlanDraftPromptKey = ''
        return
      }
      const promptKey = `${summary.invalidPlans}:${summary.invalidBasePlans}:${summary.total}`
      if (this.invalidPlanDraftPromptKey === promptKey) return
      this.invalidPlanDraftPromptKey = promptKey
      try {
        await this.$confirm(
          `发现 ${summary.total} 个异常作息草稿，已暂时隔离且不会显示。点击“恢复可识别草稿”会按兼容字段尝试恢复；完全无名称的数据仍会继续隔离。`,
          '检测到异常草稿',
          {
            confirmButtonText: '恢复可识别草稿',
            cancelButtonText: '丢弃异常草稿',
            distinguishCancelAndClose: true,
            type: 'warning'
          }
        )
        const nextDraftState = recoverInvalidPlanDrafts()
        const nextSummary = this.invalidPlanDraftSummary(nextDraftState)
        const recoveredCount = Math.max(0, summary.total - nextSummary.total)
        this.draftState = nextDraftState
        this.refreshPlansFromDraftState()
        if (recoveredCount > 0) {
          this.$message.success(`已恢复 ${recoveredCount} 个可识别的异常草稿`)
        } else {
          this.$message.info('未找到可恢复的异常草稿，已继续隔离')
        }
      } catch (action) {
        if (action !== 'cancel') return
        this.draftState = discardInvalidPlanDrafts()
        this.refreshPlansFromDraftState()
        this.$message.success('已丢弃异常作息草稿')
      }
    },
    handleAssistantRefresh() {
      this.loadData(true)
    },
    mapPlans(payload) {
      const schedules = payload && Array.isArray(payload.schedules) ? payload.schedules : []
      return schedules.map((schedule, index) => {
        const name = String(schedule?.schedule_name || schedule?.name || '').trim()
        if (!name) return null
        const tasks = Array.isArray(schedule?.tasks) ? schedule.tasks : []
        const mappedTasks = tasks.map((task, idx) => this.mapTask(task, idx))
        return {
          id: schedule?.schedule_id || schedule?.schedule_name || `plan-${index + 1}`,
          name,
          status: schedule?.status || '启用',
          tasks: mappedTasks
        }
      }).filter((plan) => plan)
    },
    mapDraftPlans(plans) {
      const list = Array.isArray(plans) ? plans : []
      return list.map((plan, index) => {
        const name = String(plan?.name || '').trim()
        if (!name) return null
        const tasks = Array.isArray(plan?.tasks) ? plan.tasks : []
        const mappedTasks = tasks.map((task, idx) => this.mapDraftTask(task, idx))
        return {
          id: plan?.id || `draft-plan-${index + 1}`,
          name,
          status: plan?.status || '启用',
          tasks: mappedTasks
        }
      }).filter((plan) => plan)
    },
    isActiveOnceOverride(override) {
      if (!override || override.mode !== 'once') return false
      if (String(override.execution_state || '') !== 'scheduled') return false
      if (override.active !== true) return false
      if (override.remote_synced === false) return false
      if (String(override.cleanup_state || '') === 'cleaned') return false
      return true
    },
    planBaseTaskCount(plan) {
      const tasks = Array.isArray(plan?.tasks) ? plan.tasks : []
      return tasks.length
    },
    planOnceTaskCount(plan) {
      return this.planOnceSummary(plan).count
    },
    planTaskCountLabel(plan) {
      return String(this.planBaseTaskCount(plan))
    },
    planOnceSummary(plan) {
      return summarizeOnceSpecs(this.taskOverrides, { planName: plan?.name || '' })
    },
    openPlanOncePanel(plan) {
      const planName = String(plan?.name || '').trim()
      if (!planName || !this.$router) return
      this.$router.push({
        name: 'TaskScheduler',
        query: { oncePanel: '1', planName }
      })
    },
    mapTask(task, idx) {
      const time = this.toTime(task?.starttime) || '00:00:00'
      const durationMode = task?.timelengthtype === 2 ? 'loop' : 'duration'
      const loop = durationMode === 'loop' ? (task?.timelength || 1) : 1
      const duration = durationMode === 'loop' ? '' : this.toDurationSeconds(task?.timelength, task?.timelengthtype)
      const customName = task?.customName || task?.taskname || ''
      const audio = task?.audio || task?.taskname || ''
      return {
        id: task?.taskid || `task-${Date.now()}-${idx}`,
        customName,
        audio,
        time,
        duration,
        loop,
        weekdays: this.normalizeWeekdays(task?.weekdays),
        dateRange: this.normalizeDateRange(task?.startdate, task?.enddate),
        location: this.formatLocation(task?.location),
        volume: typeof task?.volume === 'number' ? task.volume : 50
      }
    },
    mapDraftTask(task, idx) {
      const durationMode = task?.durationMode === 'loop' ? 'loop' : 'duration'
      return {
        id: task?.id || task?.taskid || `draft-task-${Date.now()}-${idx}`,
        customName: task?.customName || '',
        audio: task?.audio || '',
        time: this.toTime(task?.time || task?.starttime) || '00:00:00',
        duration: durationMode === 'loop'
          ? ''
          : this.toDurationSeconds(task?.duration || task?.timelength, task?.timelengthtype),
        loop: durationMode === 'loop' ? (task?.loop || task?.timelength || 1) : 1,
        weekdays: this.normalizeWeekdays(task?.weekdays),
        dateRange: Array.isArray(task?.dateRange)
          ? task.dateRange
          : this.normalizeDateRange(task?.startdate, task?.enddate),
        location: this.formatLocation(task?.location),
        volume: typeof task?.volume === 'number' ? task.volume : 50
      }
    },
    async discardPlanDraft() {
      if (!this.hasPlanDraft) return
      try {
        await this.$confirm(
          `确定放弃当前 ${this.planDraftCount} 个未上传的作息方案草稿吗？此操作不可撤销。`,
          '放弃本地草稿',
          {
            confirmButtonText: '放弃草稿',
            cancelButtonText: '取消',
            type: 'warning'
          }
        )
      } catch (err) {
        return
      }
      this.draftState = clearPlanDraft()
      await this.loadData(true)
      this.$message.success('已放弃作息方案草稿')
    },
    formatLocation(location) {
      if (!location) return '—'
      if (Array.isArray(location)) {
        if (location.length && Array.isArray(location[0])) {
          return location.map((path) => path.join(' / ')).join('，')
        }
        return location.join(' / ')
      }
      if (typeof location === 'string') return location
      return '—'
    },
    normalizeDateRange(start, end) {
      const startDate = this.normalizeDate(start)
      const endDate = this.normalizeDate(end)
      if (!startDate && !endDate) return []
      if (!startDate) return [endDate, endDate]
      if (!endDate) return [startDate, startDate]
      return [startDate, endDate]
    },
    normalizeDate(value) {
      if (!value || value === '0-00-00') return ''
      const text = String(value)
      return /^\d{4}-\d{2}-\d{2}$/.test(text) ? text : ''
    },
    toTime(value) {
      if (!value) return ''
      const text = String(value)
      if (text.length >= 8) return text.slice(0, 8)
      if (text.length >= 5) return `${text.slice(0, 5)}:00`
      return text
    },
    toDurationSeconds(length, type) {
      if (!length) return ''
      const val = Number(length)
      if (!val) return ''
      if (type === 1) return Math.max(1, Math.round(val))
      return Math.max(1, Math.round(val))
    },
    normalizeWeekdays(value) {
      if (!Array.isArray(value)) return []
      const normalized = value
        .map((day) => (day !== undefined && day !== null ? String(day) : ''))
        .filter((day) => day)
      if (!normalized.length) return []
      const inOrder = []
      WEEKDAY_ORDER.forEach((day) => {
        if (normalized.includes(day)) inOrder.push(day)
      })
      normalized.forEach((day) => {
        if (!inOrder.includes(day)) inOrder.push(day)
      })
      return inOrder
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

.header-actions {
  display: flex;
  align-items: center;
  gap: 8px;
}

.muted-text {
  color: #909399;
}

::v-deep .el-table__expand-icon .el-icon {
  color: #ffffff;
  font-weight: 700;
  -webkit-text-stroke: 1px #2d7cf6;
  text-stroke: 1px #2d7cf6;
  font-size: 16px;
}
</style>
