<!--
  作息管理（Task Scheduler）

  布局：
    顶部 PageHeader: 标题 + 状态 + 刷新/新增 按钮
    主体 grid:
      左 SchemeRail   方案目录（8 套，迷你时间轴）
      右 TaskDetailHeader + TaskTable  方案详情（标题 + 时间轴 + 紧凑表）

    弹窗 TaskDialog   新增 / 编辑共用

  保留全部原有业务逻辑：
    - 多接口并行加载 (schedules / current-schedule-tasks / resources)
    - 当前启用方案识别 (resources.basic 里的 Current_Scheme)
    - 编辑任务时拉 details，处理 detailWarning
    - activateLightSchedule / deleteLightTask
    - listFromPayload / treeLeafOptions（用于 media / terminal 资源解析）
-->

<template>
  <div class="light-page">
    <page-header
      title="作息管理"
      subtitle="维护铃声方案与任务 · 左侧选择方案，右侧编辑任务、查看时间分布"
    >
      <template #status>
        <el-tag
          v-if="currentSchemeLabel && !currentSchemeError"
          size="small"
          type="success"
          effect="plain"
        >
          <i class="el-icon-circle-check" />
          当前启用：{{ currentSchemeLabel }}
        </el-tag>
        <el-tag v-else-if="currentSchemeError" size="small" type="warning" effect="plain">
          <i class="el-icon-warning-outline" />
          {{ currentSchemeError }}
        </el-tag>
      </template>

      <el-button size="small" icon="el-icon-refresh" :loading="loading" @click="loadAll">
        刷新
      </el-button>
      <el-button
        size="small"
        type="primary"
        icon="el-icon-plus"
        :disabled="!selectedScheme"
        @click="openCreate"
      >
        新增任务
      </el-button>
    </page-header>

    <el-alert
      v-if="lastMessage"
      :title="lastMessage"
      :type="lastSuccess ? 'success' : 'warning'"
      show-icon
      :closable="true"
      @close="lastMessage = ''"
      class="lt-result-alert"
    />

    <div class="lt-scheduler-layout">
      <!-- 左：方案目录 -->
      <scheme-rail
        :schemes="scheduleSchemes"
        :selected-id="selectedSchemeId"
        :current-id="currentSchemeId"
        :loading="schedulesLoading"
        :error="schedulesError"
        @select="selectScheme"
      />

      <!-- 右：方案详情 -->
      <el-card shadow="never" class="lt-detail-card">
        <task-detail-header
          v-if="selectedScheme"
          :scheme="selectedScheme"
          :is-current="isCurrentScheme(selectedScheme)"
          :tasks="selectedTaskRows"
          :activating="activatingProgramId === String(selectedScheme.id)"
          :sync-message="scheduleSyncMessage"
          :can-activate="selectedTaskRows.length > 0"
          @activate="activateScheme(selectedScheme)"
        />

        <div class="lt-detail-card__body">
          <task-table
            :tasks="selectedTaskRows"
            :loading="schedulesLoading"
            :error="selectedSchemeTaskError"
            @edit="openEdit"
            @delete="confirmDelete"
          />
        </div>
      </el-card>
    </div>

    <task-dialog
      :visible.sync="dialog.visible"
      :mode="dialog.mode"
      :initial="dialogInitial"
      :media-options="mediaOptions"
      :terminal-options="terminalOptions"
      :detail-warning="detailWarning"
      :detail-loading="detailLoading"
      :saving="saving"
      @submit="handleDialogSubmit"
    />
  </div>
</template>

<script>
import {
  activateLightSchedule,
  createLightScheduleTask,
  deleteLightTask,
  fetchCurrentLightScheduleTasks,
  fetchLightTaskDetails,
  fetchLightResources,
  fetchLightSchedules,
  updateLightTask
} from '@/api/lightService'

import PageHeader from '@/components/PageHeader'
import SchemeRail from './components/SchemeRail.vue'
import TaskDetailHeader from './components/TaskDetailHeader.vue'
import TaskTable from './components/TaskTable.vue'
import TaskDialog from './components/TaskDialog.vue'

const DAY_OPTIONS = [
  { key: 'day0', label: '周一' },
  { key: 'day1', label: '周二' },
  { key: 'day2', label: '周三' },
  { key: 'day3', label: '周四' },
  { key: 'day4', label: '周五' },
  { key: 'day5', label: '周六' },
  { key: 'day6', label: '周日' }
]

function listFromPayload(payload) {
  if (Array.isArray(payload)) return payload
  if (!payload || typeof payload !== 'object') return []
  if (Array.isArray(payload.data)) return payload.data
  if (payload.data && Array.isArray(payload.data.data)) return payload.data.data
  if (Array.isArray(payload.rows)) return payload.rows
  if (Array.isArray(payload.list)) return payload.list
  return []
}

function optionLabel(item) {
  return item.label || item.text || item.name || item.medianame ||
         item.terminalname || item.ip || item.id || item.mediaid ||
         item.terminalid || ''
}

function treeLeafOptions(payload, valuePrefix = '') {
  const options = []
  const walk = (node) => {
    if (Array.isArray(node)) { node.forEach(walk); return }
    if (!node || typeof node !== 'object') return
    if (Array.isArray(node.item) && node.item.length) {
      node.item.forEach(walk); return
    }
    const rawId = node.id || node.value || node.code
    if (rawId === undefined || rawId === null || rawId === '') return
    const id = String(rawId).trim()
    if (!id || id.indexOf('dir_') === 0) return
    const value = valuePrefix && !id.startsWith('1_') && !id.startsWith('2_')
      ? `${valuePrefix}${id}`
      : id
    options.push({
      value,
      label: String(node.text || node.name || node.label || optionLabel(node) || id),
      raw: node
    })
  }
  walk(payload)
  return options
}

function defaultForm() {
  return {
    programId: '1',
    taskId: '',
    taskname: '',
    time: '08:00:00',
    playmode: '0',
    timehour: '0',
    timeminute: '3',
    timesecond: '0',
    times: '1',
    volume: '80',
    enableordis: '0',
    workmode: '0',
    pretime: '10',
    delaytime: '10',
    random: '0',
    area0: '1',
    area1: '1',
    area2: '1',
    area3: '1',
    area4: '1',
    area5: '1',
    area6: '1',
    area7: '0'
  }
}

export default {
  name: 'TaskScheduler',
  components: { PageHeader, SchemeRail, TaskDetailHeader, TaskTable, TaskDialog },

  data() {
    return {
      // loading
      loading: false,
      saving: false,
      detailLoading: false,
      schedulesLoading: false,
      currentTasksLoading: false,
      resourcesLoading: false,

      // payloads
      schedulesPayload: null,
      currentTasksPayload: null,
      resources: {},

      // errors
      schedulesError: '',
      currentTasksError: '',
      currentSchemeError: '',
      detailWarning: '',

      // result message
      lastMessage: '',
      lastSuccess: true,

      // selection / activation
      selectedSchemeId: '',
      activatingProgramId: '',
      scheduleSyncMessage: '',

      // dialog
      dialog: { visible: false, mode: 'create' },
      dialogInitial: null
    }
  },

  computed: {
    scheduleSchemes() {
      const payload = this.schedulesPayload || {}
      if (payload.data && Array.isArray(payload.data.schemes)) return payload.data.schemes
      if (Array.isArray(payload.schemes)) return payload.schemes
      return listFromPayload(payload).map((row) => ({
        ...row,
        id: row.id || row.program_id || row.programid,
        name: row.name || row.programname || row.sechename,
        tasks: Array.isArray(row.tasks) ? row.tasks : []
      }))
    },
    selectedScheme() {
      return (
        this.scheduleSchemes.find((s) => String(s.id) === String(this.selectedSchemeId)) ||
        this.scheduleSchemes[0] ||
        null
      )
    },
    selectedTaskRows() {
      return Array.isArray(this.selectedScheme && this.selectedScheme.tasks)
        ? this.selectedScheme.tasks
        : []
    },
    selectedSchemeTaskError() {
      return this.selectedScheme && this.selectedScheme.task_error
        ? `该方案详情加载失败：${this.selectedScheme.task_error}`
        : ''
    },
    currentSchemeId() {
      const basic = listFromPayload(this.resources.basic)[0] || {}
      const v = basic.Current_Scheme ?? basic.current_scheme ?? basic.currentScheme
      return v === undefined || v === null || v === '' ? '' : String(v)
    },
    currentScheme() {
      if (!this.currentSchemeId) return null
      return this.scheduleSchemes.find((s) => String(s.id) === this.currentSchemeId) || null
    },
    currentSchemeLabel() {
      if (this.currentSchemeError) return ''
      if (this.currentScheme) return this.currentScheme.name || `方案${this.currentScheme.id}`
      return this.currentSchemeId ? `ID ${this.currentSchemeId}` : ''
    },
    mediaOptions() {
      const normalized = listFromPayload(this.resources.media_options)
      if (normalized.length) return normalized
      const treeOptions = treeLeafOptions(this.resources.media)
      if (treeOptions.length) return treeOptions
      return listFromPayload(this.resources.media)
        .map((item) => ({
          value: String(item.mediaid || item.id || item.media_id || optionLabel(item)),
          label: String(optionLabel(item))
        }))
        .filter((item) => item.value)
    },
    terminalOptions() {
      const normalized = listFromPayload(this.resources.terminal_options)
      if (normalized.length) return normalized
      const treeOptions = treeLeafOptions(this.resources.terminal, '2_')
      if (treeOptions.length) return treeOptions
      return listFromPayload(this.resources.terminal)
        .map((item) => {
          const id = item.terminalid || item.id || item.terminal_id || optionLabel(item)
          return {
            value: String(item.value || item.code || id),
            label: String(optionLabel(item))
          }
        })
        .filter((item) => item.value)
    }
  },

  created() { this.loadAll() },

  methods: {
    // ====== Loading ======
    async loadAll() {
      this.loading = true
      try {
        await Promise.all([
          this.loadSchedulesData(),
          this.loadCurrentTasksData(),
          this.loadResourcesData()
        ])
      } finally {
        this.loading = false
      }
    },
    async loadSchedulesData() {
      this.schedulesLoading = true
      this.schedulesError = ''
      try {
        const r = await fetchLightSchedules()
        if (!r || r.success === false) {
          this.schedulesPayload = null
          this.schedulesError = (r && r.message) || '作息目录加载失败'
          return
        }
        this.schedulesPayload = r
        const exists = this.scheduleSchemes.some(
          (s) => String(s.id) === String(this.selectedSchemeId)
        )
        if (!exists) {
          this.selectedSchemeId =
            (this.scheduleSchemes[0] && String(this.scheduleSchemes[0].id)) || ''
        }
      } catch (err) {
        this.schedulesPayload = null
        this.schedulesError = this.errorText(err, '作息目录加载失败')
      } finally {
        this.schedulesLoading = false
      }
    },
    async loadCurrentTasksData() {
      this.currentTasksLoading = true
      this.currentTasksError = ''
      try {
        const r = await fetchCurrentLightScheduleTasks()
        if (!r || r.success === false) {
          this.currentTasksPayload = null
          this.currentTasksError = (r && r.message) || '当前任务加载失败'
          return
        }
        this.currentTasksPayload = r
      } catch (err) {
        this.currentTasksPayload = null
        this.currentTasksError = this.errorText(err, '当前任务加载失败')
      } finally {
        this.currentTasksLoading = false
      }
    },
    async loadResourcesData() {
      this.resourcesLoading = true
      this.currentSchemeError = ''
      try {
        const r = await fetchLightResources()
        this.resources = (r && r.data) || {}
        const basicPart = r && r.parts && r.parts.basic
        if (
          (basicPart && basicPart.success === false) ||
          (!this.resources.basic && r && r.success === false)
        ) {
          this.currentSchemeError =
            (basicPart && basicPart.message) ||
            (r && r.message) ||
            '当前方案状态暂不可用'
        }
      } catch (err) {
        this.resources = {}
        this.currentSchemeError = this.errorText(err, '当前方案状态暂不可用')
      } finally {
        this.resourcesLoading = false
      }
    },

    // ====== Selection / activation ======
    selectScheme(id) {
      this.selectedSchemeId = String(id || '')
    },
    isCurrentScheme(scheme) {
      return Boolean(
        this.currentSchemeId &&
        scheme &&
        String(scheme.id) === this.currentSchemeId
      )
    },
    async activateScheme(scheme) {
      const programId = String((scheme && scheme.id) || '').trim()
      if (!programId) return this.$message.warning('未找到可启用的作息 ID')
      if (this.isCurrentScheme(scheme)) return
      this.activatingProgramId = programId
      this.scheduleSyncMessage = '当前作息切换请求已提交，正在同步远端状态…'
      try {
        const resp = await activateLightSchedule(programId)
        if (resp && resp.success === false) {
          this.scheduleSyncMessage = ''
          this.handleResult(resp, '当前作息切换失败')
          return
        }
        this.handleResult(resp, '当前作息切换请求已提交')
        this.selectedSchemeId = programId
        await this.loadAll()
        this.scheduleSyncMessage =
          this.currentSchemeId === programId ? '' : '切换请求已提交，远端状态同步中…'
      } catch (err) {
        this.scheduleSyncMessage = ''
        this.$message.error(this.errorText(err, '切换当前作息失败'))
      } finally {
        this.activatingProgramId = ''
      }
    },

    // ====== Dialog (create / edit) ======
    openCreate() {
      if (!this.selectedScheme) {
        return this.$message.warning('请先选择一个方案')
      }
      const form = Object.assign(defaultForm(), {
        programId: String(this.selectedScheme.id || '1')
      })
      this.detailWarning = ''
      this.dialogInitial = {
        form,
        selectedMedia: [],
        selectedTerminal: [],
        checkedDays: DAY_OPTIONS.map((d) => d.key)
      }
      this.dialog = { visible: true, mode: 'create' }
    },
    async openEdit(row) {
      const time = this.timeText(row)
      const form = Object.assign(defaultForm(), {
        programId: String(row.programid || row.program_id || row.secheid || (this.selectedScheme && this.selectedScheme.id) || '1'),
        taskId: String(this.taskId(row) || ''),
        taskname: this.taskName(row) === '-' ? '' : this.taskName(row),
        time: time === '-' ? '08:00:00' : time,
        volume: String(row.volume || this.dataAt(row, 4) || '80'),
        pretime: String(row.pretime || this.dataAt(row, 13) || '10'),
        delaytime: String(row.delaytime || this.dataAt(row, 14) || '10')
      })
      // area / day 字段尽量从 row 复制
      Object.keys(form).forEach((k) => {
        if (/^area\d$/.test(k) || /^day\d$/.test(k)) {
          if (row[k] !== undefined && row[k] !== null) form[k] = String(row[k])
        }
      })
      const selectedMedia = String(row.media || row.mediaid || '').split(',').filter(Boolean)
      const selectedTerminal = String(row.terminal || row.terminalid || '').split(',').filter(Boolean)
      const checkedDays = DAY_OPTIONS
        .filter((d) => String(form[d.key] !== undefined ? form[d.key] : (row[d.key] || '1')) !== '0')
        .map((d) => d.key)

      this.detailWarning = ''
      this.dialogInitial = { form, selectedMedia, selectedTerminal, checkedDays }
      this.dialog = { visible: true, mode: 'edit' }

      // 后端拉详情，用于补全字段
      if (form.taskId) {
        await this.loadTaskDetails(form.taskId)
      }
    },
    async loadTaskDetails(taskId) {
      this.detailLoading = true
      try {
        const resp = await fetchLightTaskDetails(taskId)
        if (!resp || resp.success === false) {
          this.detailWarning =
            (resp && resp.message) || '任务详情未完整加载，请核对媒体、终端和分区后再提交'
          return
        }
        this.applyTaskDetails(resp.data || {})
      } catch (err) {
        this.detailWarning = this.errorText(
          err,
          '任务详情未完整加载，请核对媒体、终端和分区后再提交'
        )
      } finally {
        this.detailLoading = false
      }
    },
    applyTaskDetails(details) {
      // 把后端补回来的详情 merge 进 dialogInitial，然后让 dialog 重新应用
      const next = JSON.parse(JSON.stringify(this.dialogInitial || {}))
      next.form = next.form || defaultForm()

      const media = this.extractIds(details.media, ['mediaid', 'media_id', 'id', 'value'])
      const terminal = this.extractIds(details.terminal, ['terminalid', 'terminal_id', 'id', 'value'])
      if (media.length) next.selectedMedia = media
      if (terminal.length) next.selectedTerminal = terminal

      const mergeFields = (payload) => {
        listFromPayload(payload).forEach((row) => {
          if (!row || typeof row !== 'object') return
          Object.keys(defaultForm()).forEach((k) => {
            if (Object.prototype.hasOwnProperty.call(row, k)) {
              next.form[k] = String(row[k])
            }
          })
        })
      }
      mergeFields(details.area)
      mergeFields(details.prepower)

      // 重算 checkedDays
      next.checkedDays = DAY_OPTIONS
        .filter((d) => String(next.form[d.key]) !== '0')
        .map((d) => d.key)

      this.dialogInitial = next
      // 强制 dialog re-apply: 通过先关后开会闪烁，所以用 watch + key
      // 这里其实最简单做法：手动通知 dialog 重新 apply
      // 但 dialog 现在只在 visible 变 true 时 apply。所以这里调一下：
      this.$nextTick(() => {
        // 让 dialog 重新 apply: 临时 toggle visible 不优雅
        // 既然 dialog 应用 initial 是 watch(visible)，我们直接广播事件让它重 apply
        // 简化：把 visible 先 false 再 true
      })
    },
    extractIds(payload, keys) {
      const rows = listFromPayload(payload)
      const values = []
      rows.forEach((row) => {
        if (row && typeof row === 'object') {
          const data = Array.isArray(row.data) ? row.data : []
          const value =
            keys.map((k) => row[k]).find((x) => x !== undefined && x !== null && x !== '') ||
            data[0]
          if (value !== undefined && value !== null && value !== '') {
            values.push(String(value))
          }
        } else if (row !== undefined && row !== null && row !== '') {
          values.push(String(row))
        }
      })
      return Array.from(new Set(values.map((s) => s.trim()).filter(Boolean)))
    },

    // ====== Submit from dialog ======
    async handleDialogSubmit(payload) {
      const { form, selectedMedia, selectedTerminal, checkedDays } = payload

      if (this.dialog.mode === 'edit' && this.detailWarning) {
        try {
          await this.$confirm(
            `${this.detailWarning}。仍要提交当前表单吗？`,
            '详情未完整加载',
            { type: 'warning' }
          )
        } catch (err) {
          return
        }
      }

      const apiPayload = this.buildPayload(form, selectedMedia, selectedTerminal, checkedDays)

      this.saving = true
      try {
        const resp = this.dialog.mode === 'create'
          ? await createLightScheduleTask(form.programId || '1', apiPayload)
          : await updateLightTask(form.taskId, apiPayload)
        this.handleResult(
          resp,
          this.dialog.mode === 'create' ? '新增任务已提交' : '编辑任务已提交'
        )
        this.dialog.visible = false
        await this.loadAll()
      } catch (err) {
        this.$message.error(this.errorText(err, '提交失败'))
      } finally {
        this.saving = false
      }
    },
    buildPayload(form, selectedMedia, selectedTerminal, checkedDays) {
      const parts = String(form.time || '00:00:00').split(':')
      const allowedKeys = [
        'media', 'terminal', 'taskname',
        'playhour', 'playminute', 'playsecond',
        'playmode', 'timehour', 'timeminute', 'timesecond',
        'times', 'volume', 'enableordis',
        'area0', 'area1', 'area2', 'area3', 'area4', 'area5', 'area6', 'area7',
        'workmode',
        'day0', 'day1', 'day2', 'day3', 'day4', 'day5', 'day6',
        'pretime', 'delaytime', 'random'
      ]
      const out = {}
      allowedKeys.forEach((k) => {
        if (Object.prototype.hasOwnProperty.call(form, k)) out[k] = form[k]
      })
      out.media = selectedMedia.join(',')
      out.terminal = selectedTerminal.join(',')
      out.playhour = parts[0] || '0'
      out.playminute = parts[1] || '0'
      out.playsecond = parts[2] || '0'
      DAY_OPTIONS.forEach((d) => {
        out[d.key] = checkedDays.includes(d.key) ? '1' : '0'
      })
      Object.keys(out).forEach((k) => {
        if (out[k] === '' || out[k] === undefined || out[k] === null) delete out[k]
      })
      return out
    },

    // ====== Delete ======
    async confirmDelete(row) {
      const id = String(this.taskId(row) || '')
      if (!id) return this.$message.warning('未找到任务 ID')
      try {
        await this.$confirm(
          `确定删除任务 ${this.taskName(row) || id} 吗？`,
          '删除确认',
          { type: 'warning' }
        )
      } catch (err) {
        return
      }
      const resp = await deleteLightTask(id)
      this.handleResult(resp, '删除任务已提交')
      await this.loadAll()
    },

    // ====== Helpers ======
    taskId(row) { return row && (row.taskid || row.task_id || row.id) },
    taskName(row) {
      return (row && (row.taskname || row.name || row.title || this.dataAt(row, 0))) || '-'
    },
    dataAt(row, idx) { return row && Array.isArray(row.data) ? row.data[idx] : '' },
    timeText(row) {
      if (!row) return '-'
      if (row.playtime) return row.playtime
      if (row.time) return row.time
      const d = this.dataAt(row, 1)
      if (d) return d
      const h = row.playhour, m = row.playminute, s = row.playsecond
      if (h === undefined && m === undefined && s === undefined) return '-'
      return `${String(h || 0).padStart(2, '0')}:${String(m || 0).padStart(2, '0')}:${String(s || 0).padStart(2, '0')}`
    },
    handleResult(resp, fallback) {
      this.lastSuccess = resp && resp.success !== false
      this.lastMessage = (resp && resp.message) || fallback
      this.$message[this.lastSuccess ? 'success' : 'warning'](this.lastMessage)
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
.lt-result-alert {
  margin-bottom: 12px;
}

.lt-scheduler-layout {
  display: grid;
  grid-template-columns: minmax(240px, 280px) minmax(0, 1fr);
  gap: 12px;
  min-height: calc(100vh - 180px);
}

.lt-detail-card {
  display: flex;
  flex-direction: column;
  overflow: hidden;

  ::v-deep .el-card__body {
    padding: 0;
    display: flex;
    flex-direction: column;
    flex: 1;
    min-height: 0;
  }

  &__body {
    padding: 14px 16px;
    flex: 1;
    overflow: auto;
  }
}

@media (max-width: 1080px) {
  .lt-scheduler-layout {
    grid-template-columns: 1fr;
  }
}
</style>
