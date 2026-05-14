<template>
  <div class="light-page">
    <div class="page-head">
      <div>
        <h2>作息管理</h2>
        <p>顶部展示当前启用作息的真实任务；下方可查看任意方案，并将其切换为当前作息。</p>
      </div>
      <div class="head-actions">
        <el-button size="small" icon="el-icon-refresh" :loading="loading" @click="loadAll">刷新</el-button>
        <el-button size="small" type="primary" icon="el-icon-plus" :disabled="!selectedScheme" @click="openCreate">新增任务</el-button>
      </div>
    </div>

    <el-alert
      v-if="lastMessage"
      class="result-alert"
      :title="lastMessage"
      :type="lastSuccess ? 'success' : 'warning'"
      show-icon
      :closable="false"
    />

    <div class="schedule-layout">
      <el-card shadow="never" class="current-schedule-card">
        <div slot="header" class="section-title">
          <span>当前启用作息任务</span>
          <el-tag size="mini" type="success">远端当前状态</el-tag>
        </div>
        <div class="current-schedule-meta">
          <span>当前启用方案：{{ currentSchemeLabel }}</span>
          <span>任务数：{{ currentTaskRows.length }}</span>
        </div>
        <el-alert
          v-if="currentSchemeError"
          class="inline-alert"
          :title="currentSchemeError"
          type="warning"
          show-icon
          :closable="false"
        />
        <el-alert
          v-if="currentTasksError"
          class="inline-alert"
          :title="currentTasksError"
          type="warning"
          show-icon
          :closable="false"
        />
        <el-alert
          v-if="scheduleSyncMessage"
          class="inline-alert"
          :title="scheduleSyncMessage"
          type="info"
          show-icon
          :closable="false"
        />
        <el-table v-if="!currentTasksError" v-loading="currentTasksLoading" :data="currentTaskRows" border size="mini" empty-text="当前启用作息暂无任务">
          <el-table-column label="任务ID" width="90">
            <template slot-scope="{ row }">{{ taskId(row) || '-' }}</template>
          </el-table-column>
          <el-table-column label="任务名称" min-width="150">
            <template slot-scope="{ row }">{{ taskName(row) }}</template>
          </el-table-column>
          <el-table-column label="播放时间" width="110">
            <template slot-scope="{ row }">{{ timeText(row) }}</template>
          </el-table-column>
          <el-table-column label="时长" width="100">
            <template slot-scope="{ row }">{{ row.playlength || row.duration || dataAt(row, 2) || '-' }}</template>
          </el-table-column>
          <el-table-column label="音量" width="80">
            <template slot-scope="{ row }">{{ row.volume || dataAt(row, 4) || '-' }}</template>
          </el-table-column>
        </el-table>
      </el-card>

      <el-card shadow="never" class="other-schedules-card">
        <div slot="header" class="section-title">
          <span>作息目录</span>
          <span class="muted-text">当前方案已高亮，其他方案可查看或切换</span>
        </div>
        <div v-if="otherSchemes.length" class="other-schedule-list">
          <div
            v-for="scheme in otherSchemes"
            :key="scheme.id"
            class="other-schedule-item"
            :class="{ selected: String(selectedSchemeId) === String(scheme.id), current: isCurrentScheme(scheme) }"
          >
            <div>
              <div class="other-schedule-name">
                {{ scheme.name || ('方案' + scheme.id) }}
                <el-tag v-if="isCurrentScheme(scheme)" size="mini" type="success">当前方案</el-tag>
              </div>
              <div class="muted-text">方案ID：{{ scheme.id }} · {{ schemeTaskSummary(scheme) }}</div>
            </div>
            <div class="other-schedule-actions">
              <el-button size="mini" @click="selectScheme(scheme)">查看作息</el-button>
              <el-button
                size="mini"
                type="primary"
                :disabled="isCurrentScheme(scheme)"
                :loading="activatingProgramId === String(scheme.id)"
                @click="activateScheme(scheme)"
              >
                {{ isCurrentScheme(scheme) ? '当前方案' : '设为当前作息' }}
              </el-button>
            </div>
          </div>
        </div>
        <el-empty v-else description="暂无作息目录" :image-size="72" />
      </el-card>
    </div>

    <el-card shadow="never" class="table-card">
      <div slot="header" class="section-title">
        <span>{{ selectedScheme ? `${selectedScheme.name || ('方案' + selectedScheme.id)} · 任务列表` : '任务列表' }}</span>
        <el-button size="mini" type="primary" icon="el-icon-plus" :disabled="!selectedScheme" @click="openCreate">新增任务</el-button>
      </div>
      <el-alert
        v-if="schedulesError"
        class="inline-alert"
        :title="schedulesError"
        type="warning"
        show-icon
        :closable="false"
      />
      <el-alert
        v-if="selectedSchemeTaskError"
        class="inline-alert"
        :title="selectedSchemeTaskError"
        type="warning"
        show-icon
        :closable="false"
      />
      <el-table v-if="!schedulesError && !selectedSchemeTaskError" v-loading="schedulesLoading" :data="selectedTaskRows" border size="small" empty-text="该作息暂无任务">
        <el-table-column label="任务ID" width="90">
          <template slot-scope="{ row }">{{ taskId(row) || '-' }}</template>
        </el-table-column>
        <el-table-column label="任务名称" min-width="160">
          <template slot-scope="{ row }">{{ taskName(row) }}</template>
        </el-table-column>
        <el-table-column label="播放时间" width="110">
          <template slot-scope="{ row }">{{ timeText(row) }}</template>
        </el-table-column>
        <el-table-column label="时长" width="100">
          <template slot-scope="{ row }">{{ row.duration || dataAt(row, 2) || '-' }}</template>
        </el-table-column>
        <el-table-column label="音量" width="80">
          <template slot-scope="{ row }">{{ row.volume || dataAt(row, 4) || '-' }}</template>
        </el-table-column>
        <el-table-column label="原始字段" min-width="220">
          <template slot-scope="{ row }">
            <span class="raw-preview">{{ compactRow(row.raw || row) }}</span>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="150" fixed="right">
          <template slot-scope="{ row }">
            <el-button type="text" size="mini" @click="openEdit(row)">编辑</el-button>
            <el-button type="text" size="mini" class="danger-link" @click="confirmDelete(row)">删除</el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-card>

    <el-dialog :title="dialog.mode === 'create' ? '新增任务' : '编辑任务'" :visible.sync="dialog.visible" width="720px">
      <el-alert
        v-if="detailWarning"
        class="detail-alert"
        :title="detailWarning"
        type="warning"
        show-icon
        :closable="false"
      />
      <el-form label-width="96px" size="small">
        <el-row :gutter="12">
          <el-col :span="12">
            <el-form-item label="方案ID">
              <el-input v-model="form.programId" :disabled="dialog.mode === 'edit'" placeholder="addtask query id" />
            </el-form-item>
          </el-col>
          <el-col :span="12">
            <el-form-item label="任务ID">
              <el-input v-model="form.taskId" :disabled="dialog.mode === 'create'" placeholder="modify/delete taskid" />
            </el-form-item>
          </el-col>
          <el-col :span="12">
            <el-form-item label="任务名称">
              <el-input v-model="form.taskname" />
            </el-form-item>
          </el-col>
          <el-col :span="12">
            <el-form-item label="播放时间">
              <el-time-picker v-model="form.time" value-format="HH:mm:ss" format="HH:mm:ss" placeholder="播放时间" class="full" />
            </el-form-item>
          </el-col>
          <el-col :span="12">
            <el-form-item label="媒体ID">
              <el-select v-model="selectedMedia" multiple filterable allow-create default-first-option class="full" placeholder="可手输或选择">
                <el-option v-for="item in mediaOptions" :key="item.value" :label="item.label" :value="item.value" />
              </el-select>
            </el-form-item>
          </el-col>
          <el-col :span="12">
            <el-form-item label="终端/分组">
              <el-select v-model="selectedTerminal" multiple filterable allow-create default-first-option class="full" placeholder="如 2_446 或 1_70">
                <el-option v-for="item in terminalOptions" :key="item.value" :label="item.label" :value="item.value" />
              </el-select>
            </el-form-item>
          </el-col>
          <el-col :span="8">
            <el-form-item label="播放模式">
              <el-select v-model="form.playmode" class="full">
                <el-option label="按时长" value="0" />
                <el-option label="按次数" value="1" />
              </el-select>
            </el-form-item>
          </el-col>
          <el-col :span="8">
            <el-form-item label="时长">
              <div class="triple">
                <el-input v-model="form.timehour" placeholder="时" />
                <el-input v-model="form.timeminute" placeholder="分" />
                <el-input v-model="form.timesecond" placeholder="秒" />
              </div>
            </el-form-item>
          </el-col>
          <el-col :span="8">
            <el-form-item label="次数/音量">
              <div class="double">
                <el-input v-model="form.times" placeholder="次数" />
                <el-input v-model="form.volume" placeholder="音量" />
              </div>
            </el-form-item>
          </el-col>
          <el-col :span="24">
            <el-form-item label="星期">
              <el-checkbox-group v-model="checkedDays">
                <el-checkbox v-for="item in dayOptions" :key="item.key" :label="item.key">{{ item.label }}</el-checkbox>
              </el-checkbox-group>
            </el-form-item>
          </el-col>
        </el-row>
      </el-form>
      <span slot="footer">
        <el-button size="small" @click="dialog.visible = false">取消</el-button>
        <el-button size="small" type="primary" :loading="saving || detailLoading" @click="submitTask">提交</el-button>
      </span>
    </el-dialog>
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

function treeLeafOptions(payload, valuePrefix = '') {
  const options = []
  const walk = (node) => {
    if (Array.isArray(node)) {
      node.forEach(walk)
      return
    }
    if (!node || typeof node !== 'object') return
    if (Array.isArray(node.item) && node.item.length) {
      node.item.forEach(walk)
      return
    }
    const rawId = node.id || node.value || node.code
    if (rawId === undefined || rawId === null || rawId === '') return
    const id = String(rawId).trim()
    if (!id || id.indexOf('dir_') === 0) return
    const value = valuePrefix && !id.startsWith('1_') && !id.startsWith('2_') ? `${valuePrefix}${id}` : id
    options.push({
      value,
      label: String(node.text || node.name || node.label || optionLabel(node) || id),
      raw: node
    })
  }
  walk(payload)
  return options
}

function optionLabel(item) {
  return item.label || item.text || item.name || item.medianame || item.terminalname || item.ip || item.id || item.mediaid || item.terminalid || ''
}

export default {
  name: 'TaskScheduler',
  data() {
    return {
      loading: false,
      saving: false,
      detailLoading: false,
      detailWarning: '',
      schedulesLoading: false,
      currentTasksLoading: false,
      resourcesLoading: false,
      schedulesPayload: null,
      currentTasksPayload: null,
      schedulesError: '',
      currentTasksError: '',
      currentSchemeError: '',
      scheduleSyncMessage: '',
      selectedSchemeId: '',
      activatingProgramId: '',
      resources: {},
      lastMessage: '',
      lastSuccess: true,
      dialog: {
        visible: false,
        mode: 'create'
      },
      selectedMedia: [],
      selectedTerminal: [],
      checkedDays: DAY_OPTIONS.map((item) => item.key),
      dayOptions: DAY_OPTIONS,
      form: this.defaultForm()
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
      return this.scheduleSchemes.find((scheme) => String(scheme.id) === String(this.selectedSchemeId)) || this.scheduleSchemes[0] || null
    },
    selectedTaskRows() {
      return this.taskRowsForScheme(this.selectedScheme)
    },
    currentTaskRows() {
      const payload = this.currentTasksPayload || {}
      if (payload.data && Array.isArray(payload.data.tasks)) return payload.data.tasks
      if (Array.isArray(payload.tasks)) return payload.tasks
      return listFromPayload(payload)
    },
    currentSchemeId() {
      const basicRows = listFromPayload(this.resources.basic)
      const basic = basicRows[0] || {}
      const value = basic.Current_Scheme ?? basic.current_scheme ?? basic.currentScheme
      return value === undefined || value === null || value === '' ? '' : String(value)
    },
    currentScheme() {
      if (!this.currentSchemeId) return null
      return this.scheduleSchemes.find((scheme) => String(scheme.id) === this.currentSchemeId) || null
    },
    currentSchemeLabel() {
      if (this.currentSchemeError) return '当前方案状态暂不可用'
      if (this.currentScheme) return this.currentScheme.name || `方案${this.currentScheme.id}`
      return this.currentSchemeId ? `ID ${this.currentSchemeId}` : '未获取到当前方案'
    },
    selectedSchemeTaskError() {
      return this.selectedScheme && this.selectedScheme.task_error ? `该方案详情加载失败：${this.selectedScheme.task_error}` : ''
    },
    otherSchemes() {
      return this.scheduleSchemes
    },
    mediaOptions() {
      const normalized = listFromPayload(this.resources.media_options)
      if (normalized.length) return normalized
      const treeOptions = treeLeafOptions(this.resources.media)
      if (treeOptions.length) return treeOptions
      return listFromPayload(this.resources.media).map((item) => ({
        value: String(item.mediaid || item.id || item.media_id || optionLabel(item)),
        label: String(optionLabel(item))
      })).filter((item) => item.value)
    },
    terminalOptions() {
      const normalized = listFromPayload(this.resources.terminal_options)
      if (normalized.length) return normalized
      const treeOptions = treeLeafOptions(this.resources.terminal, '2_')
      if (treeOptions.length) return treeOptions
      return listFromPayload(this.resources.terminal).map((item) => {
        const id = item.terminalid || item.id || item.terminal_id || optionLabel(item)
        return {
          value: String(item.value || item.code || id),
          label: String(optionLabel(item))
        }
      }).filter((item) => item.value)
    }
  },
  created() {
    this.loadAll()
  },
  methods: {
    defaultForm() {
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
    },
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
        const schedules = await fetchLightSchedules()
        if (!schedules || schedules.success === false) {
          this.schedulesPayload = null
          this.schedulesError = (schedules && schedules.message) || '作息目录加载失败'
          return
        }
        this.schedulesPayload = schedules
        const selectedExists = this.scheduleSchemes.some((scheme) => String(scheme.id) === String(this.selectedSchemeId))
        if (!selectedExists) {
          this.selectedSchemeId = (this.scheduleSchemes[0] && String(this.scheduleSchemes[0].id)) || ''
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
        const currentTasks = await fetchCurrentLightScheduleTasks()
        if (!currentTasks || currentTasks.success === false) {
          this.currentTasksPayload = null
          this.currentTasksError = (currentTasks && currentTasks.message) || '当前任务加载失败'
          return
        }
        this.currentTasksPayload = currentTasks
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
        const resources = await fetchLightResources()
        this.resources = (resources && resources.data) || {}
        const basicPart = resources && resources.parts && resources.parts.basic
        if ((basicPart && basicPart.success === false) || (!this.resources.basic && resources && resources.success === false)) {
          this.currentSchemeError = (basicPart && basicPart.message) || (resources && resources.message) || '当前方案状态暂不可用'
        }
      } catch (err) {
        this.resources = {}
        this.currentSchemeError = this.errorText(err, '当前方案状态暂不可用')
      } finally {
        this.resourcesLoading = false
      }
    },
    openCreate() {
      this.openCreateForScheme(this.selectedScheme || { id: '1' })
    },
    openCreateForScheme(scheme) {
      this.dialog = { visible: true, mode: 'create' }
      this.detailWarning = ''
      this.form = {
        ...this.defaultForm(),
        programId: String(scheme && scheme.id ? scheme.id : '1')
      }
      this.selectedMedia = []
      this.selectedTerminal = []
      this.checkedDays = DAY_OPTIONS.map((item) => item.key)
    },
    selectScheme(scheme) {
      this.selectedSchemeId = String((scheme && scheme.id) || '')
    },
    isCurrentScheme(scheme) {
      return Boolean(this.currentSchemeId && scheme && String(scheme.id) === this.currentSchemeId)
    },
    schemeTaskSummary(scheme) {
      if (scheme && scheme.task_error) return '任务详情加载失败'
      return `${this.taskRowsForScheme(scheme).length} 个任务`
    },
    async activateScheme(scheme) {
      const programId = String((scheme && scheme.id) || '').trim()
      if (!programId) return this.$message.warning('未找到可启用的作息ID')
      if (this.isCurrentScheme(scheme)) return
      this.activatingProgramId = programId
      this.scheduleSyncMessage = '当前作息切换请求已提交，正在同步远端状态'
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
        this.scheduleSyncMessage = this.currentSchemeId === programId
          ? ''
          : '切换请求已提交，远端状态同步中'
      } catch (err) {
        this.scheduleSyncMessage = ''
        this.$message.error(this.errorText(err, '切换当前作息失败'))
      } finally {
        this.activatingProgramId = ''
      }
    },
    async openEdit(row) {
      this.dialog = { visible: true, mode: 'edit' }
      this.detailWarning = ''
      const time = this.timeText(row)
      this.form = {
        ...this.defaultForm(),
        programId: String(row.programid || row.program_id || row.secheid || '1'),
        taskId: String(this.taskId(row) || ''),
        taskname: this.taskName(row) === '-' ? '' : this.taskName(row),
        time: time === '-' ? '08:00:00' : time,
        volume: String(row.volume || this.dataAt(row, 4) || '80'),
        pretime: String(row.pretime || this.dataAt(row, 13) || '10'),
        delaytime: String(row.delaytime || this.dataAt(row, 14) || '10')
      }
      this.selectedMedia = String(row.media || row.mediaid || '').split(',').filter(Boolean)
      this.selectedTerminal = String(row.terminal || row.terminalid || '').split(',').filter(Boolean)
      this.checkedDays = DAY_OPTIONS.filter((item) => String(row[item.key]) !== '0').map((item) => item.key)
      if (this.form.taskId) {
        await this.loadTaskDetails(this.form.taskId)
      }
    },
    async loadTaskDetails(taskId) {
      this.detailLoading = true
      try {
        const resp = await fetchLightTaskDetails(taskId)
        if (!resp || resp.success === false) {
          this.detailWarning = (resp && resp.message) || '任务详情未完整加载，请核对媒体、终端和分区后再提交'
          return
        }
        this.applyTaskDetails(resp.data || {})
      } catch (err) {
        this.detailWarning = this.errorText(err, '任务详情未完整加载，请核对媒体、终端和分区后再提交')
      } finally {
        this.detailLoading = false
      }
    },
    applyTaskDetails(details) {
      const media = this.extractIds(details.media, ['mediaid', 'media_id', 'id', 'value'])
      const terminal = this.extractIds(details.terminal, ['terminalid', 'terminal_id', 'id', 'value'])
      if (media.length) this.selectedMedia = media
      if (terminal.length) this.selectedTerminal = terminal
      this.applyDetailFields(details.area)
      this.applyDetailFields(details.taskinfo && details.taskinfo.detail ? [details.taskinfo.detail] : details.taskinfo)
    },
    extractIds(payload, keys) {
      const rows = listFromPayload(payload)
      const values = []
      rows.forEach((row) => {
        if (row && typeof row === 'object') {
          const data = Array.isArray(row.data) ? row.data : []
          const value = keys.map((key) => row[key]).find((item) => item !== undefined && item !== null && item !== '') || data[0]
          if (value !== undefined && value !== null && value !== '') values.push(String(value))
        } else if (row !== undefined && row !== null && row !== '') {
          values.push(String(row))
        }
      })
      return Array.from(new Set(values.map((item) => item.trim()).filter(Boolean)))
    },
    applyDetailFields(payload) {
      const rows = listFromPayload(payload)
      rows.forEach((row) => {
        if (!row || typeof row !== 'object') return
        Object.keys(this.defaultForm()).forEach((key) => {
          if (Object.prototype.hasOwnProperty.call(row, key)) this.$set(this.form, key, String(row[key]))
        })
      })
    },
    buildPayload() {
      const parts = String(this.form.time || '00:00:00').split(':')
      const allowedKeys = [
        'media',
        'terminal',
        'taskname',
        'playhour',
        'playminute',
        'playsecond',
        'playmode',
        'timehour',
        'timeminute',
        'timesecond',
        'times',
        'volume',
        'enableordis',
        'area0',
        'area1',
        'area2',
        'area3',
        'area4',
        'area5',
        'area6',
        'area7',
        'workmode',
        'day0',
        'day1',
        'day2',
        'day3',
        'day4',
        'day5',
        'day6',
        'pretime',
        'delaytime',
        'random'
      ]
      const payload = {}
      allowedKeys.forEach((key) => {
        if (Object.prototype.hasOwnProperty.call(this.form, key)) payload[key] = this.form[key]
      })
      payload.media = this.selectedMedia.join(',')
      payload.terminal = this.selectedTerminal.join(',')
      payload.playhour = parts[0] || '0'
      payload.playminute = parts[1] || '0'
      payload.playsecond = parts[2] || '0'
      DAY_OPTIONS.forEach((item) => {
        payload[item.key] = this.checkedDays.includes(item.key) ? '1' : '0'
      })
      Object.keys(payload).forEach((key) => {
        if (payload[key] === '' || payload[key] === undefined || payload[key] === null) delete payload[key]
      })
      return payload
    },
    async submitTask() {
      if (this.dialog.mode === 'create' && !String(this.form.programId || '').trim()) {
        return this.$message.warning('请填写方案ID')
      }
      if (this.dialog.mode === 'edit' && !String(this.form.taskId || '').trim()) {
        return this.$message.warning('请填写任务ID')
      }
      if (this.dialog.mode === 'edit' && this.detailWarning) {
        try {
          await this.$confirm(`${this.detailWarning}。仍要提交当前表单吗？`, '详情未完整加载', { type: 'warning' })
        } catch (err) {
          return
        }
      }
      this.saving = true
      try {
        const payload = this.buildPayload()
        const resp = this.dialog.mode === 'create'
          ? await createLightScheduleTask(this.form.programId || '1', payload)
          : await updateLightTask(this.form.taskId, payload)
        this.handleResult(resp, this.dialog.mode === 'create' ? '新增任务已提交' : '编辑任务已提交')
        this.dialog.visible = false
        await this.loadAll()
      } catch (err) {
        this.$message.error(this.errorText(err, '提交失败'))
      } finally {
        this.saving = false
      }
    },
    async confirmDelete(row) {
      const taskId = String(this.taskId(row) || '')
      if (!taskId) return this.$message.warning('未找到任务ID')
      try {
        await this.$confirm(`确定删除任务 ${this.taskName(row) || taskId} 吗？`, '删除确认', { type: 'warning' })
      } catch (err) {
        return
      }
      const resp = await deleteLightTask(taskId)
      this.handleResult(resp, '删除任务已提交')
      await this.loadAll()
    },
    taskRowsForScheme(scheme) {
      return Array.isArray(scheme && scheme.tasks) ? scheme.tasks : []
    },
    taskId(row) {
      return row && (row.taskid || row.task_id || row.id)
    },
    taskName(row) {
      return (row && (row.taskname || row.name || row.title || this.dataAt(row, 0))) || '-'
    },
    dataAt(row, index) {
      return row && Array.isArray(row.data) ? row.data[index] : ''
    },
    handleResult(resp, fallback) {
      this.lastSuccess = resp && resp.success !== false
      this.lastMessage = (resp && resp.message) || fallback
      this.$message[this.lastSuccess ? 'success' : 'warning'](fallback)
    },
    timeText(row) {
      if (row.playtime) return row.playtime
      if (row.time) return row.time
      const dataTime = this.dataAt(row, 1)
      if (dataTime) return dataTime
      const h = row.playhour
      const m = row.playminute
      const s = row.playsecond
      if (h === undefined && m === undefined && s === undefined) return '-'
      return `${String(h || 0).padStart(2, '0')}:${String(m || 0).padStart(2, '0')}:${String(s || 0).padStart(2, '0')}`
    },
    compactRow(row) {
      return JSON.stringify(row).slice(0, 180)
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
.head-actions {
  display: flex;
  align-items: center;
  gap: 8px;
}
.result-alert {
  margin-bottom: 12px;
}
.inline-alert {
  margin-bottom: 12px;
}
.schedule-layout {
  display: grid;
  grid-template-columns: minmax(280px, 0.9fr) minmax(360px, 1.35fr);
  gap: 14px;
  margin-bottom: 14px;
}
.section-title {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}
.current-schedule-name {
  margin-bottom: 10px;
  color: #1f2d3d;
  font-size: 24px;
  font-weight: 700;
}
.current-schedule-meta {
  display: flex;
  flex-wrap: wrap;
  gap: 14px;
  margin-bottom: 16px;
  color: #606266;
  font-size: 13px;
}
.other-schedule-list {
  display: grid;
  gap: 10px;
}
.other-schedule-item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 12px;
  border: 1px solid #e4e7ed;
  border-radius: 8px;
  background: #fff;
}
.other-schedule-item.selected {
  border-color: #409eff;
  background: #f5faff;
}
.other-schedule-item.current {
  border-color: #67c23a;
  background: #f4fbef;
}
.other-schedule-name {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 4px;
  color: #303133;
  font-weight: 600;
}
.other-schedule-actions {
  display: flex;
  gap: 8px;
  flex-shrink: 0;
}
.muted-text {
  color: #909399;
  font-size: 12px;
}
.detail-alert {
  margin-bottom: 12px;
}
.table-card {
  border-radius: 8px;
}
.scheme-detail {
  padding: 10px 12px 14px;
  background: #fafafa;
}
.scheme-toolbar {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 10px;
  color: #303133;
  font-size: 13px;
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
.full {
  width: 100%;
}
.triple,
.double {
  display: grid;
  gap: 6px;
}
.triple {
  grid-template-columns: repeat(3, 1fr);
}
.double {
  grid-template-columns: repeat(2, 1fr);
}
@media (max-width: 760px) {
  .page-head {
    flex-direction: column;
  }
  .head-actions {
    justify-content: flex-start;
  }
  .scheme-toolbar {
    align-items: flex-start;
    flex-direction: column;
    gap: 8px;
  }
  .schedule-layout {
    grid-template-columns: 1fr;
  }
  .other-schedule-item,
  .other-schedule-actions {
    align-items: flex-start;
    flex-direction: column;
  }
}
</style>
