<!--
  浣滄伅绠＄悊锛圱ask Scheduler锛?
  甯冨眬锛?    椤堕儴 PageHeader: 鏍囬 + 鐘舵€?+ 鍒锋柊/鏂板 鎸夐挳
    涓讳綋 grid:
      宸?SchemeRail   鏂规鐩綍锛? 濂楋紝杩蜂綘鏃堕棿杞达級
      鍙?TaskDetailHeader + TaskTable  鏂规璇︽儏锛堟爣棰?+ 鏃堕棿杞?+ 绱у噾琛級

    寮圭獥 TaskDialog   鏂板 / 缂栬緫鍏辩敤

  淇濈暀鍏ㄩ儴鍘熸湁涓氬姟閫昏緫锛?    - 澶氭帴鍙ｅ苟琛屽姞杞?(schedules / current-schedule-tasks / resources)
    - 褰撳墠鍚敤鏂规璇嗗埆 (resources.basic 閲岀殑 Current_Scheme)
    - 缂栬緫浠诲姟鏃舵媺 details锛屽鐞?detailWarning
    - activateLightSchedule / deleteLightTask
    - listFromPayload / treeLeafOptions锛堢敤浜?media / terminal 璧勬簮瑙ｆ瀽锛?-->

<template>
  <div class="light-page">
    <page-header
      title="作息管理"
      subtitle="维护铃声方案与任务，左侧选择方案，右侧编辑任务并查看时间分布"
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
      class="lt-result-alert"
      @close="lastMessage = ''"
    />

    <div class="lt-scheduler-layout">
      <!-- 宸︼細鏂规鐩綍 -->
      <scheme-rail
        :schemes="scheduleSchemes"
        :selected-id="selectedSchemeId"
        :current-id="currentSchemeId"
        :loading="schedulesLoading"
        :error="schedulesError"
        @select="selectScheme"
      />

      <!-- 鍙筹細鏂规璇︽儏 -->
      <el-card shadow="never" class="lt-detail-card">
        <task-detail-header
          v-if="selectedScheme"
          :scheme="selectedScheme"
          :is-current="isCurrentScheme(selectedScheme)"
          :tasks="selectedTaskRows"
          :activating="activatingProgramId === String(selectedScheme.id)"
          :sync-message="scheduleSyncMessage"
          :can-activate="selectedTaskRows.length > 0"
          :renaming="renamingProgramId === String(selectedScheme.id)"
          @activate="activateScheme(selectedScheme)"
          @rename="renameScheme(selectedScheme)"
        />

        <div class="lt-detail-card__body">
          <task-table
            :tasks="selectedTaskRows"
            :loading="schedulesLoading"
            :error="selectedSchemeTaskError"
            :busy-id="busyId"
            @execute="executeTask"
            @stop="stopTask"
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
  executeLightTask,
  fetchCurrentLightScheduleTasks,
  fetchLightTaskDetails,
  fetchLightResources,
  fetchLightSchedules,
  stopLightTask,
  renameLightSchedule,
  updateLightTask
} from '@/api/lightService'

import PageHeader from '@/components/PageHeader'
import SchemeRail from './components/SchemeRail.vue'
import TaskDetailHeader from './components/TaskDetailHeader.vue'
import TaskTable from './components/TaskTable.vue'
import TaskDialog from './components/TaskDialog.vue'

const DAY_OPTIONS = [
  { key: 'day0', label: '鍛ㄤ竴' },
  { key: 'day1', label: '鍛ㄤ簩' },
  { key: 'day2', label: '鍛ㄤ笁' },
  { key: 'day3', label: '鍛ㄥ洓' },
  { key: 'day4', label: '鍛ㄤ簲' },
  { key: 'day5', label: '鍛ㄥ叚' },
  { key: 'day6', label: '鍛ㄦ棩' }
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

// Local cache: 远端 modifytask 当前固件不接受 1_ 前缀的分组写入，导致下次打开看不到。
// 用 localStorage 在客户端"记住"每个任务的分组选择，仅 1_ 前缀的项参与缓存合并。
const TASK_GROUP_CACHE_KEY = 'lt:task_group_selections'

function loadTaskGroupCache() {
  try {
    const raw = window.localStorage.getItem(TASK_GROUP_CACHE_KEY)
    const obj = raw ? JSON.parse(raw) : {}
    return obj && typeof obj === 'object' ? obj : {}
  } catch (err) {
    return {}
  }
}

function saveTaskGroupCacheEntry(taskId, selections) {
  if (!taskId) return
  try {
    const cache = loadTaskGroupCache()
    const groups = (selections || []).filter((v) => String(v).startsWith('1_'))
    if (groups.length) {
      cache[String(taskId)] = groups
    } else {
      delete cache[String(taskId)]
    }
    window.localStorage.setItem(TASK_GROUP_CACHE_KEY, JSON.stringify(cache))
  } catch (err) { /* storage unavailable */ }
}

function readTaskGroupCacheEntry(taskId) {
  if (!taskId) return []
  const cache = loadTaskGroupCache()
  const list = cache[String(taskId)]
  return Array.isArray(list) ? list.filter((v) => String(v).startsWith('1_')) : []
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
    area7: '0',
    // day0-6 必须显式定义，否则 applyTaskDetails 的 merge 会跳过这些 key，
    // 导致编辑窗口的星期永远 fallback 到"全选"。
    day0: '1',
    day1: '1',
    day2: '1',
    day3: '1',
    day4: '1',
    day5: '1',
    day6: '1'
  }
}

// schedules / opensech 返回的星期字段是 mon/tue/.../sun；前端 form 用 day0-6。
const DAY_REMOTE_TO_LOCAL = [
  ['mon', 'day0'],
  ['tue', 'day1'],
  ['wed', 'day2'],
  ['thu', 'day3'],
  ['fri', 'day4'],
  ['sat', 'day5'],
  ['sun', 'day6']
]

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
      renamingProgramId: '',
      scheduleSyncMessage: '',
      busyId: '',

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
        ? `璇ユ柟妗堣鎯呭姞杞藉け璐ワ細${this.selectedScheme.task_error}`
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
      if (this.currentScheme) return this.currentScheme.name || `鏂规${this.currentScheme.id}`
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
          this.schedulesError = (r && r.message) || '浣滄伅鐩綍鍔犺浇澶辫触'
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
        this.schedulesError = this.errorText(err, '浣滄伅鐩綍鍔犺浇澶辫触')
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
          this.currentTasksError = (r && r.message) || '褰撳墠浠诲姟鍔犺浇澶辫触'
          return
        }
        this.currentTasksPayload = r
      } catch (err) {
        this.currentTasksPayload = null
        this.currentTasksError = this.errorText(err, '褰撳墠浠诲姟鍔犺浇澶辫触')
      } finally {
        this.currentTasksLoading = false
      }
    },
    async loadResourcesData({ silent = false } = {}) {
      this.resourcesLoading = true
      if (!silent) this.currentSchemeError = ''
      try {
        const r = await fetchLightResources()
        this.resources = (r && r.data) || {}
        const basicPart = r && r.parts && r.parts.basic
        if (
          !silent && (
            (basicPart && basicPart.success === false) ||
            (!this.resources.basic && r && r.success === false)
          )
        ) {
          this.currentSchemeError =
            (basicPart && basicPart.message) ||
            (r && r.message) ||
            '当前方案状态暂不可用'
        }
      } catch (err) {
        this.resources = {}
        if (!silent) this.currentSchemeError = this.errorText(err, '当前方案状态暂不可用')
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
    async waitForSchemeActivation(programId, { totalMs = 30000 } = {}) {
      const start = Date.now()
      let attempt = 0
      while (Date.now() - start < totalMs) {
        attempt += 1
        await this.loadResourcesData({ silent: true })
        if (this.currentSchemeId === programId) {
          await this.loadCurrentTasksData()
          return true
        }
        const elapsed = Date.now() - start
        const interval = elapsed < 3000 ? 500 : (elapsed < 10000 ? 1500 : 2500)
        const remaining = Math.max(60, totalMs - (Date.now() - start))
        this.scheduleSyncMessage = elapsed < 2500
          ? '正在向设备发送切换指令…'
          : `设备正在重启以应用新方案，预计还需 ${Math.ceil(remaining / 1000)} 秒…`
        await new Promise((resolve) => setTimeout(resolve, Math.min(interval, remaining)))
      }
      return false
    },
    async activateScheme(scheme) {
      const programId = String((scheme && scheme.id) || '').trim()
      if (!programId) return this.$message.warning('鏈壘鍒板彲鍚敤鐨勪綔鎭?ID')
      if (this.isCurrentScheme(scheme)) return
      this.activatingProgramId = programId
      this.currentSchemeError = ''
      this.scheduleSyncMessage = '正在向设备发送切换指令…'
      try {
        const resp = await activateLightSchedule(programId)
        if (resp && resp.success === false) {
          this.scheduleSyncMessage = ''
          this.handleResult(resp, '当前作息切换失败')
          return
        }
        this.selectedSchemeId = programId
        this.scheduleSyncMessage = '设备已收到指令，正在重启以应用新方案（约 15-20 秒）…'
        const activated = await this.waitForSchemeActivation(programId)
        this.currentSchemeError = ''
        if (activated) {
          this.scheduleSyncMessage = ''
          this.$message.success('方案切换完成，设备已应用新作息')
        } else {
          this.scheduleSyncMessage = '设备重启耗时超出预期，请稍后手动刷新确认状态'
        }
      } catch (err) {
        this.scheduleSyncMessage = ''
        this.$message.error(this.errorText(err, '切换当前作息失败'))
      } finally {
        this.activatingProgramId = ''
      }
    },
    async renameScheme(scheme) {
      const programId = String((scheme && scheme.id) || '').trim()
      if (!programId) return this.$message.warning('未找到方案 ID')
      const currentName = (scheme && scheme.name) ? String(scheme.name) : ''
      let nextName
      try {
        const result = await this.$prompt('请输入新的方案名称', '重命名方案', {
          confirmButtonText: '确定',
          cancelButtonText: '取消',
          inputValue: currentName,
          inputValidator: (val) => (val && String(val).trim() ? true : '名称不能为空')
        })
        nextName = String(result.value || '').trim()
      } catch (err) {
        return
      }
      if (!nextName || nextName === currentName) return
      this.renamingProgramId = programId
      try {
        const resp = await renameLightSchedule(programId, nextName)
        this.handleResult(resp, '方案重命名已提交')
        if (!resp || resp.success !== false) {
          await this.loadSchedulesData()
        }
      } catch (err) {
        this.$message.error(this.errorText(err, '方案重命名失败'))
      } finally {
        this.renamingProgramId = ''
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
      // area / day 瀛楁灏介噺浠?row 澶嶅埗
      // 把 row 里所有 defaultForm 涉及的字段尽可能拷过来（覆盖默认值）。
      // 之前只拷了 area* / day*，导致 timehour/timeminute/timesecond/times/playmode
      // 等字段每次打开都是默认值，看不到上一次保存的真实值。
      Object.keys(form).forEach((k) => {
        if (k === 'programId' || k === 'taskId' || k === 'time') return
        const v = row[k]
        if (v !== undefined && v !== null && v !== '') {
          form[k] = String(v)
        }
      })
      // schedules / opensech 返回的星期字段名是 mon/tue/.../sun，而 form 用 day0-6。
      // 上面的通用拷贝看不到这种字段名差异，单独做一次映射。
      DAY_REMOTE_TO_LOCAL.forEach(([remoteKey, localKey]) => {
        const v = row[remoteKey]
        if (v !== undefined && v !== null && v !== '') {
          form[localKey] = String(v)
        }
      })
      const selectedMedia = String(row.media || row.mediaid || '').split(',').filter(Boolean)
      const remoteTerminal = String(row.terminal || row.terminalid || '').split(',').filter(Boolean)
      const cachedGroups = readTaskGroupCacheEntry(form.taskId)
      const selectedTerminal = Array.from(new Set([...remoteTerminal, ...cachedGroups]))
      const checkedDays = DAY_OPTIONS
        .filter((d) => String(form[d.key] !== undefined ? form[d.key] : (row[d.key] || '1')) !== '0')
        .map((d) => d.key)

      this.detailWarning = ''
      this.dialogInitial = { form, selectedMedia, selectedTerminal, checkedDays }
      this.dialog = { visible: true, mode: 'edit' }

      // 鍚庣鎷夎鎯咃紝鐢ㄤ簬琛ュ叏瀛楁
      if (form.taskId) {
        await this.loadTaskDetails(form.taskId)
      }
    },
    async loadTaskDetails(taskId) {
      this.detailLoading = true
      try {
        const resp = await fetchLightTaskDetails(taskId)
        if (resp && resp.data) {
          this.applyTaskDetails(resp.data)
        }
        if (!resp || resp.success === false) {
          this.detailWarning =
            (resp && resp.message) || '浠诲姟璇︽儏鏈畬鏁村姞杞斤紝璇锋牳瀵瑰獟浣撱€佺粓绔拰鍒嗗尯鍚庡啀鎻愪氦'
          return
        }
        this.applyTaskDetails(resp.data || {})
      } catch (err) {
        this.detailWarning = this.errorText(
          err,
          '浠诲姟璇︽儏鏈畬鏁村姞杞斤紝璇锋牳瀵瑰獟浣撱€佺粓绔拰鍒嗗尯鍚庡啀鎻愪氦'
        )
      } finally {
        this.detailLoading = false
      }
    },
    applyTaskDetails(details) {
      // 鎶婂悗绔ˉ鍥炴潵鐨勮鎯?merge 杩?dialogInitial锛岀劧鍚庤 dialog 閲嶆柊搴旂敤
      const next = JSON.parse(JSON.stringify(this.dialogInitial || {}))
      next.form = next.form || defaultForm()

      const media = this.extractIds(details.media, ['mediaid', 'media_id', 'id', 'value'])
      const terminal = this.extractIds(details.terminal, ['terminalid', 'terminal_id', 'id', 'value'])
      if (media.length) next.selectedMedia = media
      // 远端 terminal 是权威的 2_ 前缀终端；分组（1_）固件丢字段，只能从本地缓存恢复
      const cachedGroups = readTaskGroupCacheEntry(next.form && next.form.taskId)
      next.selectedTerminal = Array.from(new Set([...terminal, ...cachedGroups]))

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

      // 把 /action/gettaskinfo 规范化后的 taskinfo.detail 字段合并进 form。
      // 包含 taskname / volume / pretime / delaytime / time / playhour / playminute /
      // playsecond / timehour / timeminute / timesecond / day0..day6 / random / enableordis
      // 之前漏了这一段，导致编辑成功后再打开看到的还是 row 里的旧字段或者默认值。
      const taskinfoDetail = details.taskinfo && details.taskinfo.detail
      if (taskinfoDetail && typeof taskinfoDetail === 'object') {
        const formKeys = defaultForm()
        Object.keys(taskinfoDetail).forEach((k) => {
          const v = taskinfoDetail[k]
          if (v === undefined || v === null || v === '') return
          if (k === 'time' || Object.prototype.hasOwnProperty.call(formKeys, k)) {
            next.form[k] = String(v)
          }
        })
      }

      // 閲嶇畻 checkedDays
      next.checkedDays = DAY_OPTIONS
        .filter((d) => String(next.form[d.key]) !== '0')
        .map((d) => d.key)

      this.dialogInitial = next
      // 寮哄埗 dialog re-apply: 閫氳繃鍏堝叧鍚庡紑浼氶棯鐑侊紝鎵€浠ョ敤 watch + key
      // 杩欓噷鍏跺疄鏈€绠€鍗曞仛娉曪細鎵嬪姩閫氱煡 dialog 閲嶆柊 apply
      // 浣?dialog 鐜板湪鍙湪 visible 鍙?true 鏃?apply銆傛墍浠ヨ繖閲岃皟涓€涓嬶細
      this.$nextTick(() => {
        // 璁?dialog 閲嶆柊 apply: 涓存椂 toggle visible 涓嶄紭闆?        // 鏃㈢劧 dialog 搴旂敤 initial 鏄?watch(visible)锛屾垜浠洿鎺ュ箍鎾簨浠惰瀹冮噸 apply
        // 绠€鍖栵細鎶?visible 鍏?false 鍐?true
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
        // Persist user's group selections client-side (固件不接受 1_ 写入，靠本地缓存记忆)
        const taskIdForCache = form.taskId
          || (resp && resp.data && (resp.data.taskid || resp.data.task_id || resp.data.id))
          || ''
        if (taskIdForCache) {
          saveTaskGroupCacheEntry(taskIdForCache, selectedTerminal)
        }
        this.dialog.visible = false
        await this.loadAll()
      } catch (err) {
        this.$message.error(this.errorText(err, '鎻愪氦澶辫触'))
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
      if (!id) return this.$message.warning('鏈壘鍒颁换鍔?ID')
      try {
        await this.$confirm(
          `纭畾鍒犻櫎浠诲姟 ${this.taskName(row) || id} 鍚楋紵`,
          '鍒犻櫎纭',
          { type: 'warning' }
        )
      } catch (err) {
        return
      }
      const resp = await deleteLightTask(id)
      this.handleResult(resp, '删除任务已提交')
      // Drop the cached group selection so it doesn't leak to a future task with the same id
      saveTaskGroupCacheEntry(id, [])
      await this.loadAll()
    },

    async executeTask(row) {
      const id = String(this.taskId(row) || '')
      if (!id) return this.$message.warning('鏈壘鍒颁换鍔?ID')
      this.busyId = `run-${id}`
      try {
        const resp = await executeLightTask(id)
        this.handleResult(resp, '鎵ц璇锋眰宸叉彁浜?')
      } catch (err) {
        this.$message.error(this.errorText(err, '鎵ц澶辫触'))
      } finally {
        this.busyId = ''
      }
    },
    async stopTask(row) {
      const id = String(this.taskId(row) || '')
      if (!id) return this.$message.warning('鏈壘鍒颁换鍔?ID')
      this.busyId = `stop-${id}`
      try {
        const resp = await stopLightTask(id)
        this.handleResult(resp, '鍋滄璇锋眰宸叉彁浜?')
      } catch (err) {
        this.$message.error(this.errorText(err, '鍋滄澶辫触'))
      } finally {
        this.busyId = ''
      }
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
      const h = row.playhour
      const m = row.playminute
      const s = row.playsecond
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

