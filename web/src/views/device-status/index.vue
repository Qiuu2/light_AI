<template>
  <div
    v-loading="loading"
    element-loading-text="正在刷新音响状态..."
    element-loading-spinner="el-icon-loading"
    element-loading-background="rgba(255, 255, 255, 0.65)"
    class="device-status-page"
    :class="{ 'is-dragging': Boolean(draggingDevice), 'is-drop-forbidden': dragForbidden }"
  >
    <div class="page-header">
      <div>
        <h2>音响状态概览</h2>
        <p>实时监控终端状态，支持分区筛选与系统全局音量调节。</p>
      </div>
      <div class="header-actions">
        <el-select
          v-model="selectedZone"
          placeholder="全部分区"
          clearable
          size="small"
          class="zone-select"
          @change="handleZoneChange"
        >
          <el-option label="全部分区" value="" />
          <el-option
            v-for="zone in zones"
            :key="String(zone.id)"
            :label="zoneLabelById(zone.id)"
            :value="String(zone.id)"
          />
        </el-select>
        <el-input
          v-model="keyword"
          placeholder="搜索终端或 IP"
          prefix-icon="el-icon-search"
          clearable
          size="small"
          class="search-input"
        />
        <div class="system-volume-control">
          <span>系统音量</span>
          <el-input-number
            v-model="systemVolume"
            :min="0"
            :max="100"
            size="small"
            controls-position="right"
          />
          <el-button
            size="small"
            type="primary"
            :loading="settingSystemVolume"
            @click="applySystemVolume"
          >
            应用
          </el-button>
        </div>
        <el-button type="primary" icon="el-icon-refresh" size="small" :loading="loading" @click="refreshData">
          刷新状态
        </el-button>
        <span class="update-time" :class="{ 'is-stale': snapshotStale }">
          更新时间：{{ lastUpdatedAt || '—' }}
          <template v-if="snapshotStale">（当前展示的是上次成功刷新结果）</template>
        </span>
      </div>
    </div>

    <div class="content">
      <div class="tree-panel card" :class="{ 'is-collapsed': isMobileLayout && !mobileTreeVisible }">
        <div class="panel-title-row">
          <div class="panel-title">分区 / 终端</div>
          <el-button
            v-if="isMobileLayout"
            size="mini"
            type="primary"
            plain
            @click="mobileTreeVisible = !mobileTreeVisible"
          >
            {{ mobileTreeVisible ? '收起分区' : '展开分区' }}
          </el-button>
        </div>
        <div v-show="!isMobileLayout || mobileTreeVisible" class="tree-panel-body">
          <div class="tree-scroll">
            <el-tree
              ref="zoneTree"
              :data="treeData"
              node-key="id"
              highlight-current
              default-expand-all
              :props="treeProps"
              @node-click="handleNodeSelect"
            >
              <span
                slot-scope="{ data }"
                class="tree-node-content"
                :class="[
                  data.type === 'zone' ? 'is-zone' : (data.type === 'empty' ? 'is-empty' : 'is-device'),
                  { 'is-zone-has-device': Boolean(draggingDevice) && data.type === 'zone' && zoneHasTerminal(data, draggingDevice.terminalId || draggingDevice.id) },
                  { 'is-zone-available': Boolean(draggingDevice) && data.type === 'zone' && !zoneHasTerminal(data, draggingDevice.terminalId || draggingDevice.id) },
                  { 'is-drop-target': data.type === 'zone' && dragTargetZoneId === data.zoneId },
                  { 'is-drop-forbidden': Boolean(draggingDevice) && !isDropAllowed(data, draggingDevice) }
                ]"
                @dragenter="handleTreeDragEnter(data)"
                @dragover="handleTreeDragOver(data, $event)"
                @dragleave="handleTreeDragLeave(data)"
                @drop="handleTreeDrop(data, $event)"
              >
                <template v-if="data.type === 'device'">
                  <div
                    class="tree-device-drag-target"
                    :draggable="!isMobileLayout"
                    @dragstart.stop="handleTreeDeviceDragStart(data, $event)"
                    @dragend.stop="handleTreeDeviceDragEnd"
                  >
                    <i class="el-icon-microphone tree-node-icon" />
                    <span class="tree-device-label">{{ data.label }}</span>
                    <span v-if="!isMobileLayout" class="tree-device-drag-hint">拖动移出/分配</span>
                  </div>
                </template>
                <template v-else>
                  <i
                    v-if="data.type === 'zone'"
                    class="el-icon-folder tree-node-icon"
                  />
                  <i
                    v-else-if="data.type === 'empty'"
                    class="el-icon-more-outline tree-node-icon"
                  />
                  <span>{{ data.label }}</span>
                </template>
              </span>
            </el-tree>
          </div>
          <div
            v-if="showRemoveDrop"
            class="remove-drop-zone"
            :class="[
              `is-${removeDrop.state}`,
              { 'is-hover': removeDrop.state === 'hover' },
              { 'is-loading': removeDrop.state === 'loading' }
            ]"
            @dragenter.prevent="handleRemoveDropDragEnter"
            @dragover.prevent="handleRemoveDropDragOver($event)"
            @dragleave="handleRemoveDropDragLeave"
            @drop.prevent="handleRemoveDropDrop($event)"
          >
            <div class="remove-drop-icon">
              <i class="el-icon-remove-outline" />
            </div>
            <div class="remove-drop-copy">
              <div class="remove-drop-title">{{ removeDropTitle }}</div>
              <div class="remove-drop-desc">{{ removeDropDescription }}</div>
            </div>
          </div>
          <div class="legend">
            <div v-for="item in statusLegend" :key="item.key" class="legend-item">
              <span :class="['dot', item.key]" />
              <span>{{ item.label }}</span>
            </div>
          </div>
        </div>
      </div>

      <div class="cards-panel card">
        <div class="panel-title">终端状态卡片</div>
        <div v-if="filteredDevices.length" class="card-grid">
          <div
            v-for="device in filteredDevices"
            :key="device.id"
            class="device-card"
            :class="[statusClass(device.status), { 'is-drag-source': draggingDevice && draggingDevice.id === device.id }]"
            :draggable="!isMobileLayout"
            @dragstart="handleCardDragStart(device, $event)"
            @dragend="handleCardDragEnd"
          >
            <div class="device-header">
              <div>
                <div class="device-name">{{ device.name }}</div>
                <div class="device-location">{{ device.locationPath }}</div>
              </div>
              <el-tag :type="statusTagType(device.status)" size="mini">
                {{ statusLabel(device.status) }}
              </el-tag>
            </div>

            <div class="device-tags">
              <el-tag size="mini" :type="netStateTag(device.netstate).type">
                网络: {{ netStateTag(device.netstate).label }}
              </el-tag>
              <el-tag size="mini" :type="deviceStateTag(device.devicestate).type">
                设备: {{ deviceStateTag(device.devicestate).label }}
              </el-tag>
              <el-tag size="mini" :type="taskStateTag(deviceTaskState(device)).type">
                任务: {{ taskStateTag(deviceTaskState(device)).label }}
              </el-tag>
            </div>

            <div class="device-stats">
              <div class="stat-item">
                <span>当前音量</span>
                <strong>{{ device.volume }}%</strong>
              </div>
              <div class="stat-item network-stat-item">
                <span class="terminal-id-label">终端id</span>
                <strong>{{ device.terminalid || device.id || '—' }}</strong>
                <span class="terminal-ip-label">终端 IP</span>
                <strong>{{ device.ip || '—' }}</strong>
              </div>
            </div>

            <div class="device-actions">
              <div class="volume-control-hint">终端卡片只展示状态；音量统一使用页面顶部“系统音量”。</div>
              <div v-if="isMobileLayout" class="mobile-device-actions">
                <el-button size="mini" plain @click="openMoveDialogForDevice(device)">
                  移动分区
                </el-button>
                <el-button
                  size="mini"
                  type="text"
                  :disabled="!canRemoveDeviceZone(device)"
                  @click="removeDeviceFromCurrentZone(device)"
                >
                  移出分区
                </el-button>
              </div>
            </div>
          </div>
        </div>
        <div v-else-if="isRendering" class="card-loading">正在加载终端...</div>
        <el-empty v-else description="当前筛选下没有终端" />
      </div>
    </div>

    <el-dialog
      title="确认终端移动"
      :visible.sync="moveDialog.visible"
      :width="isMobileLayout ? '92%' : '420px'"
      :close-on-click-modal="false"
      :close-on-press-escape="!moveDialog.loading"
      :show-close="!moveDialog.loading"
    >
      <div v-if="moveDialog.pending" class="move-confirm-text">
        <template v-if="moveDialog.pending.mode === 'manual'">
          <div class="move-confirm-title">选择“{{ moveDialog.pending.deviceName }}”的新分区</div>
          <div class="move-confirm-subtitle">当前分区：{{ zoneLabelById(moveDialog.pending.sourceZoneId) }}</div>
          <el-form label-position="top" size="small" class="move-form">
            <el-form-item label="目标分区">
              <el-select
                v-model="moveDialog.pending.targetZoneId"
                filterable
                placeholder="请选择目标分区"
                class="move-select"
                @change="onMoveTargetChange"
              >
                <el-option
                  v-for="zone in moveTargetOptions(moveDialog.pending.sourceZoneId)"
                  :key="String(zone.id)"
                  :label="zoneLabelById(zone.id)"
                  :value="String(zone.id)"
                />
              </el-select>
            </el-form-item>
          </el-form>
        </template>
        <template v-else>
          确定要将设备 [{{ moveDialog.pending.deviceName }}] 移动到 [{{ moveDialog.pending.targetZoneName }}] 吗？
        </template>
      </div>
      <span slot="footer" class="dialog-footer">
        <el-button :disabled="moveDialog.loading" @click="cancelMoveDialog">取消</el-button>
        <el-button
          type="primary"
          :loading="moveDialog.loading"
          :disabled="moveDialog.pending && moveDialog.pending.mode === 'manual' && !moveDialog.pending.targetZoneId"
          @click="confirmMoveDialog"
        >
          确认
        </el-button>
      </span>
    </el-dialog>
  </div>
</template>

<script>
import {
  fetchTerminalZones,
  fetchAllTerminalData,
  fetchRuntimePlayTasks,
  setSystemVolume
} from '@/api/dataService'
import { offAssistantRefresh, onAssistantRefresh } from '@/utils/assistantRefreshBus'

const extractList = (payload) => {
  if (Array.isArray(payload)) return payload
  if (payload && Array.isArray(payload.data)) return payload.data
  if (payload && payload.data && Array.isArray(payload.data.rows)) return payload.data.rows
  if (payload && Array.isArray(payload.rows)) return payload.rows
  return []
}

const resolveDeviceName = (item, fallbackId = '') => {
  const name = String(item?.name || item?.terminalname || '').trim()
  if (name) return name
  const terminalId = String(item?.terminalid ?? item?.terminal_id ?? item?.id ?? fallbackId ?? '').trim()
  if (terminalId && !terminalId.startsWith('device-')) return terminalId
  const ip = String(item?.ip || '').trim()
  if (ip) return ip
  return '未命名终端'
}

const isValidDeviceItem = (item) => {
  if (!item || typeof item !== 'object') return false
  const terminalId = String(item?.terminalid ?? item?.terminal_id ?? item?.id ?? '').trim()
  const name = String(item?.name || item?.terminalname || '').trim()
  const ip = String(item?.ip || '').trim()
  return Boolean(terminalId || name || ip)
}

const TERMINAL_STATE_REFRESH_ACTIONS = ['enable_terminal', 'disable_terminal']
const TERMINAL_STATE_FORCE_REFRESH_DELAY = 1200

export default {
  name: 'DeviceStatus',
  data() {
    return {
      keyword: '',
      selectedZone: '',
      activeTreeZoneId: '',
      selectedDeviceId: '',
      treeProps: { children: 'children', label: 'label' },
      treeData: [],
      terminals: [],
      baseTerminals: [],
      runtimePlayRows: [],
      renderedTerminals: [],
      zones: [],
      loading: false,
      settingVolume: {},
      settingSystemVolume: false,
      systemVolume: 50,
      renderTimer: null,
      runtimePlayPollTimer: null,
      renderToken: 0,
      renderBatchSize: 8,
      isRendering: false,
      lastUpdatedAt: '',
      snapshotStale: false,
      draggingDevice: null,
      dragTargetZoneId: '',
      dragForbidden: false,
      moveDialog: {
        visible: false,
        loading: false,
        pending: null
      },
      removeDrop: {
        state: 'hidden',
        sourceZoneId: '',
        sourceZoneName: '',
        deviceId: '',
        deviceName: ''
      },
      dragGhostEl: null,
      dragExpandTimer: null,
      dragExpandZoneId: '',
      assistantTerminalRefreshTimer: null,
      mobileTreeVisible: false,
      statusLegend: [
        { key: 'online', label: '在线' },
        { key: 'offline', label: '离线' },
        { key: 'playing', label: '播放中' },
        { key: 'idle', label: '空闲' }
      ]
    }
  },
  computed: {
    isMobileLayout() {
      return this.$store?.state?.app?.device === 'mobile'
    },
    filteredDevices() {
      return this.renderedTerminals
    },
    showRemoveDrop() {
      return !this.isMobileLayout && this.canUseRemoveDrop(this.draggingDevice)
    },
    removeDropTitle() {
      const zoneName = this.removeDrop.sourceZoneName || '当前分区'
      if (this.removeDrop.state === 'hover') {
        return `松手即可移出 ${zoneName}`
      }
      if (this.removeDrop.state === 'loading') {
        return '正在移出...'
      }
      return `移出 ${zoneName}`
    },
    removeDropDescription() {
      if (this.removeDrop.state === 'loading') {
        return '正在移除分区关联，请稍候'
      }
      return this.removeDrop.state === 'hover'
        ? '仅移除分区关联，不删除终端'
        : '仅移除分区关联，不删除终端'
    }
  },
  watch: {
    keyword() {
      if (!this.terminals.length) return
      this.startRenderCards(this.filterTerminals(this.terminals))
    },
    selectedDeviceId() {
      if (!this.terminals.length) return
      this.startRenderCards(this.filterTerminals(this.terminals))
    },
    selectedZone() {
      if (!this.terminals.length) return
      this.startRenderCards(this.filterTerminals(this.terminals))
    }
  },
  created() {
    this.refreshData()
    onAssistantRefresh(this.handleAssistantRefresh)
  },
  beforeDestroy() {
    offAssistantRefresh(this.handleAssistantRefresh)
    this.clearRenderTimer()
    this.stopRuntimePlayPolling()
    this.clearDragExpandTimer()
    this.clearAssistantTerminalRefreshTimer()
    if (this.dragGhostEl && this.dragGhostEl.parentNode) {
      this.dragGhostEl.parentNode.removeChild(this.dragGhostEl)
    }
    this.dragGhostEl = null
  },
  methods: {
    terminalMutationUnsupported(kind) {
      const messages = {
        move: '当前 light 终端分组移动未开放：远端 action 映射尚未确认。'
      }
      this.$message.warning(messages[kind] || '当前终端写操作未开放。')
    },
    hasActiveRuntimePlayRows(rows = this.runtimePlayRows) {
      return (Array.isArray(rows) ? rows : []).some((row) => this.runtimePlayRowState(row) === 0)
    },
    syncRuntimePlayPolling(rows = this.runtimePlayRows) {
      if (!this.hasActiveRuntimePlayRows(rows)) {
        this.stopRuntimePlayPolling()
        return
      }
      this.startRuntimePlayPolling()
    },
    startRuntimePlayPolling() {
      if (this.runtimePlayPollTimer) return
      this.runtimePlayPollTimer = setInterval(() => {
        if (!this.hasActiveRuntimePlayRows()) {
          this.stopRuntimePlayPolling()
          return
        }
        this.refreshData(true)
      }, 60000)
    },
    stopRuntimePlayPolling() {
      if (!this.runtimePlayPollTimer) return
      clearInterval(this.runtimePlayPollTimer)
      this.runtimePlayPollTimer = null
    },
    collectAssistantRefreshActions(payload = {}) {
      const actions = []
      const actionLog = Array.isArray(payload?.action_log) ? payload.action_log : []
      actionLog.forEach((item) => {
        const action = String(item?.action || '').trim()
        if (action) actions.push(action)
      })
      const intent = String(payload?.intent || '').trim()
      if (intent) actions.push(intent)
      return actions
    },
    hasAssistantRefreshAction(payload = {}, candidates = []) {
      const candidateSet = new Set(
        (Array.isArray(candidates) ? candidates : [])
          .map((item) => String(item || '').trim())
          .filter(Boolean)
      )
      if (!candidateSet.size) return false
      return this.collectAssistantRefreshActions(payload).some((action) => candidateSet.has(action))
    },
    collectAssistantTerminalStateTargets(payload = {}, actionName = 'enable_terminal') {
      const actionLog = Array.isArray(payload?.action_log) ? payload.action_log : []
      return actionLog
        .filter((item) => String(item?.action || '').trim() === actionName)
        .filter((item) => Number(item?.details?.remote_state) === 0)
        .flatMap((item) => {
          const terminalIds = Array.isArray(item?.details?.terminal_ids) ? item.details.terminal_ids : []
          return terminalIds.map((value) => String(value || '').trim()).filter(Boolean)
        })
    },
    applyAssistantTerminalStateOptimistic(payload = {}) {
      const targetIds = new Set(this.collectAssistantTerminalStateTargets(payload, 'enable_terminal'))
      if (!targetIds.size) return false
      let updated = false
      const patchDeviceList = (list) => {
        if (!Array.isArray(list)) return list
        return list.map((device) => {
          const terminalId = String(this.terminalKey(device) || '')
          if (!targetIds.has(terminalId)) return device
          updated = true
          const next = {
            ...(device || {}),
            devicestate: 1
          }
          next.status = this.deriveStatus(next)
          return next
        })
      }
      this.baseTerminals = patchDeviceList(this.baseTerminals)
      this.terminals = patchDeviceList(this.terminals)
      this.startRenderCards(this.filterTerminals(this.terminals))
      return updated
    },
    clearAssistantTerminalRefreshTimer() {
      if (!this.assistantTerminalRefreshTimer) return
      clearTimeout(this.assistantTerminalRefreshTimer)
      this.assistantTerminalRefreshTimer = null
    },
    queueAssistantTerminalForceRefresh() {
      this.clearAssistantTerminalRefreshTimer()
      this.assistantTerminalRefreshTimer = setTimeout(() => {
        this.assistantTerminalRefreshTimer = null
        this.refreshData(true, true)
      }, TERMINAL_STATE_FORCE_REFRESH_DELAY)
    },
    renderTerminalSnapshot(baseTerminals, runtimeRows = []) {
      const normalizedBase = Array.isArray(baseTerminals) ? baseTerminals.map((device) => ({ ...(device || {}) })) : []
      const normalizedRuntimeRows = Array.isArray(runtimeRows) ? runtimeRows : []
      this.runtimePlayRows = normalizedRuntimeRows
      this.syncRuntimePlayPolling(normalizedRuntimeRows)
      this.terminals = this.applyRuntimePlayOverlay(normalizedBase, normalizedRuntimeRows)
      this.startRenderCards(this.filterTerminals(this.terminals))
      this.treeData = this.mapTreeData()
    },
    markTerminalSnapshotStale() {
      this.snapshotStale = true
      this.renderTerminalSnapshot(this.baseTerminals, [])
    },
    canUseRemoveDrop(dragging) {
      if (!dragging || dragging.sourceType !== 'device-tree-node') return false
      const sourceZoneId = String(dragging.zoneId || '')
      return Boolean(sourceZoneId) && sourceZoneId !== 'unassigned' && sourceZoneId !== '0'
    },
    syncRemoveDropFromDragging(dragging, state = 'idle') {
      if (!this.canUseRemoveDrop(dragging)) {
        this.resetRemoveDrop()
        return
      }
      this.removeDrop = {
        state,
        sourceZoneId: String(dragging.zoneId || ''),
        sourceZoneName: String(dragging.zoneName || this.zoneLabelById(dragging.zoneId) || '当前分区'),
        deviceId: String(dragging.terminalId || dragging.id || ''),
        deviceName: String(dragging.name || '终端')
      }
    },
    resetRemoveDrop() {
      this.removeDrop = {
        state: 'hidden',
        sourceZoneId: '',
        sourceZoneName: '',
        deviceId: '',
        deviceName: ''
      }
    },
    beginDeviceDrag(dragging, event) {
      if (!dragging || !event || !event.dataTransfer) return
      this.draggingDevice = dragging
      this.dragTargetZoneId = ''
      this.dragForbidden = false
      this.syncRemoveDropFromDragging(dragging, 'idle')
      event.dataTransfer.effectAllowed = 'move'
      event.dataTransfer.setData('application/json', JSON.stringify(this.draggingDevice))
      event.dataTransfer.setData('text/plain', this.draggingDevice.id)

      if (this.dragGhostEl && this.dragGhostEl.parentNode) {
        this.dragGhostEl.parentNode.removeChild(this.dragGhostEl)
      }

      const ghost = document.createElement('div')
      ghost.className = 'drag-ghost'
      Object.assign(ghost.style, {
        position: 'fixed',
        top: '0',
        left: '0',
        transform: 'translate(-9999px, -9999px)',
        display: 'inline-flex',
        flexDirection: 'column',
        alignItems: 'center',
        gap: '8px',
        padding: '10px 12px',
        borderRadius: '14px',
        background: 'rgba(31, 45, 61, 0.92)',
        color: '#fff',
        fontSize: '12px',
        fontWeight: '600',
        boxShadow: '0 10px 24px rgba(31, 45, 61, 0.28)',
        pointerEvents: 'none',
        zIndex: '2147483647'
      })

      const nameEl = document.createElement('div')
      nameEl.className = 'drag-ghost-name'
      nameEl.textContent = this.draggingDevice.name
      Object.assign(nameEl.style, {
        maxWidth: '180px',
        whiteSpace: 'nowrap',
        overflow: 'hidden',
        textOverflow: 'ellipsis'
      })

      const iconWrap = document.createElement('div')
      Object.assign(iconWrap.style, {
        width: '38px',
        height: '38px',
        borderRadius: '50%',
        display: 'inline-flex',
        alignItems: 'center',
        justifyContent: 'center',
        background: 'rgba(64, 158, 255, 0.18)',
        border: '1px solid rgba(64, 158, 255, 0.55)'
      })
      const iconEl = document.createElement('span')
      iconEl.className = 'drag-ghost-icon'
      iconEl.textContent = '🔊'
      Object.assign(iconEl.style, {
        fontSize: '18px',
        lineHeight: '1'
      })
      iconWrap.appendChild(iconEl)
      ghost.appendChild(nameEl)
      ghost.appendChild(iconWrap)

      document.body.appendChild(ghost)
      this.dragGhostEl = ghost
      event.dataTransfer.setDragImage(ghost, 24, 28)
    },
    endDeviceDrag() {
      if (this.dragGhostEl && this.dragGhostEl.parentNode) {
        this.dragGhostEl.parentNode.removeChild(this.dragGhostEl)
      }
      this.dragGhostEl = null
      this.clearDragExpandTimer()
      this.draggingDevice = null
      this.dragTargetZoneId = ''
      this.dragForbidden = false
      this.resetRemoveDrop()
    },
    terminalKey(device) {
      const value = device?.terminalid ?? device?.terminal_id ?? device?.id
      return value === undefined || value === null ? '' : String(value)
    },
    normalizeZoneIds(values) {
      const source = Array.isArray(values) ? values : [values]
      const result = []
      source.forEach((value) => {
        let key = value !== undefined && value !== null ? String(value) : ''
        if (!key || key === '0') key = 'unassigned'
        if (!result.includes(key)) {
          result.push(key)
        }
      })
      const filtered = result.length > 1 ? result.filter((item) => item !== 'unassigned') : result
      return filtered.length ? filtered : ['unassigned']
    },
    deviceZoneIds(device) {
      const zones = Array.isArray(device?.zoneIds) && device.zoneIds.length
        ? device.zoneIds
        : [device?.zone]
      return this.normalizeZoneIds(zones)
    },
    buildLocationPath(zoneIds, deviceName) {
      const labels = this.normalizeZoneIds(zoneIds).map((zoneId) => this.zoneLabelById(zoneId))
      const zoneText = labels.length ? labels.join('、') : '无分区终端'
      return `${zoneText} / ${deviceName || '终端'}`
    },
    mergeDevicesByTerminal(list) {
      const merged = new Map()
      const source = Array.isArray(list) ? list : []
      source.forEach((item, index) => {
        if (!isValidDeviceItem(item)) return
        const key = this.terminalKey(item) || `device-${index + 1}`
        const incomingZoneIds = this.deviceZoneIds(item)
        const incomingName = resolveDeviceName(item, key)

        if (!merged.has(key)) {
          const volume = this.toNumber(item?.volume, 0)
          merged.set(key, {
            ...item,
            id: key,
            terminalid: String(item?.terminalid || key),
            name: incomingName,
            zoneIds: incomingZoneIds,
            zone: incomingZoneIds[0],
            locationPath: this.buildLocationPath(incomingZoneIds, incomingName),
            volume,
            muted: volume <= 0,
            prevVolume: volume > 0 ? volume : (item?.prevVolume || 30)
          })
          return
        }

        const existing = merged.get(key)
        const zoneIds = this.normalizeZoneIds([
          ...(Array.isArray(existing?.zoneIds) ? existing.zoneIds : [existing?.zone]),
          ...incomingZoneIds
        ])
        const name = resolveDeviceName(item, existing?.terminalid || key) || String(existing?.name || '未命名终端')
        const volume = this.toNumber(item?.volume, this.toNumber(existing?.volume, 0))
        merged.set(key, {
          ...existing,
          ...item,
          id: key,
          terminalid: String(existing?.terminalid || item?.terminalid || key),
          name,
          ip: item?.ip || existing?.ip || '',
          zoneIds,
          zone: zoneIds[0],
          locationPath: this.buildLocationPath(zoneIds, name),
          volume,
          muted: volume <= 0,
          prevVolume: volume > 0 ? volume : (existing?.prevVolume || item?.prevVolume || 30)
        })
      })
      return Array.from(merged.values())
    },
    filterTerminals(list) {
      const keyword = String(this.keyword || '').trim().toLowerCase()
      return list.filter((device) => {
        if (this.selectedZone) {
          const selected = String(this.selectedZone)
          const zones = this.deviceZoneIds(device)
          if (!zones.includes(selected)) {
            return false
          }
        }
        if (this.selectedDeviceId && this.terminalKey(device) !== String(this.selectedDeviceId)) {
          return false
        }
        if (!keyword) return true
        const name = String(device.name || '').toLowerCase()
        const ip = String(device.ip || '').toLowerCase()
        return name.includes(keyword) || ip.includes(keyword)
      })
    },
    clearRenderTimer() {
      if (this.renderTimer) {
        clearTimeout(this.renderTimer)
        this.renderTimer = null
      }
    },
    startRenderCards(list) {
      this.clearRenderTimer()
      this.renderToken += 1
      const token = this.renderToken
      this.renderedTerminals = []
      if (!Array.isArray(list) || list.length === 0) {
        this.isRendering = false
        return
      }
      this.isRendering = true
      const batchSize = Math.max(1, this.renderBatchSize)
      let index = 0
      const step = () => {
        if (token !== this.renderToken) return
        const next = list.slice(index, index + batchSize)
        if (!next.length) {
          this.isRendering = false
          return
        }
        this.renderedTerminals = this.renderedTerminals.concat(next)
        index += batchSize
        if (index < list.length) {
          this.renderTimer = setTimeout(step, 16)
        } else {
          this.isRendering = false
        }
      }
      step()
    },
    handleAssistantRefresh(payload = {}) {
      const hasTerminalStateAction = this.hasAssistantRefreshAction(payload, TERMINAL_STATE_REFRESH_ACTIONS)
      if (!hasTerminalStateAction) {
        this.refreshData(true)
        return
      }
      const appliedOptimistic = this.applyAssistantTerminalStateOptimistic(payload)
      if (!appliedOptimistic) {
        this.refreshData(true)
      }
      this.queueAssistantTerminalForceRefresh()
    },
    handleZoneChange() {
      this.selectedDeviceId = ''
    },
    handleNodeSelect(node) {
      if (!node || typeof node !== 'object') return
      if (node.type === 'zone') {
        this.activeTreeZoneId = node.zoneId || ''
        this.selectedDeviceId = ''
        return
      }
      if (node.type === 'device') {
        this.activeTreeZoneId = node.zoneId || ''
        this.selectedDeviceId = node.deviceId || ''
      }
    },
    handleCardDragStart(device, event) {
      if (this.isMobileLayout) return
      if (!device || !event || !event.dataTransfer) return
      const deviceZones = this.deviceZoneIds(device)
      const selected = String(this.selectedZone || '')
      const sourceZone = selected && deviceZones.includes(selected) ? selected : (deviceZones[0] || 'unassigned')
      const terminalId = this.terminalKey(device)
      this.beginDeviceDrag({
        id: String(terminalId || device.id || ''),
        terminalId: String(terminalId || device.id || ''),
        name: String(device.name || terminalId || '终端'),
        zoneId: String(sourceZone),
        zoneName: this.zoneLabelById(sourceZone),
        sourceType: 'device-card'
      }, event)
    },
    handleTreeDeviceDragStart(data, event) {
      if (this.isMobileLayout) return
      if (!data || data.type !== 'device' || !event || !event.dataTransfer) return
      const dragging = {
        id: String(data.deviceId || data.terminalId || ''),
        terminalId: String(data.terminalId || data.deviceId || ''),
        name: String(data.label || data.deviceId || '终端'),
        zoneId: String(data.zoneId || 'unassigned'),
        zoneName: this.zoneLabelById(data.zoneId),
        sourceType: 'device-tree-node'
      }
      if (typeof window !== 'undefined') {
        window.__DEVICE_STATUS_TREE_DRAG__ = {
          id: dragging.id,
          sourceType: dragging.sourceType,
          zoneId: dragging.zoneId,
          zoneName: dragging.zoneName
        }
      }
      this.beginDeviceDrag(dragging, event)
    },
    handleCardDragEnd() {
      this.endDeviceDrag()
    },
    handleTreeDeviceDragEnd() {
      this.endDeviceDrag()
    },
    clearDragExpandTimer() {
      if (this.dragExpandTimer) {
        clearTimeout(this.dragExpandTimer)
        this.dragExpandTimer = null
      }
      this.dragExpandZoneId = ''
    },
    queueAutoExpandZone(data) {
      if (!data || data.type !== 'zone') return
      const zoneId = String(data.zoneId || '')
      if (!zoneId) return
      if (this.dragExpandZoneId === zoneId && this.dragExpandTimer) return
      this.clearDragExpandTimer()
      this.dragExpandZoneId = zoneId
      this.dragExpandTimer = setTimeout(() => {
        const tree = this.$refs.zoneTree
        if (!tree || typeof tree.getNode !== 'function') return
        const node = tree.getNode(data.id)
        if (node && !node.expanded) {
          node.expanded = true
        }
      }, 1000)
    },
    zoneHasTerminal(zoneNode, terminalId) {
      if (!zoneNode || zoneNode.type !== 'zone' || !terminalId) return false
      const targetId = String(terminalId)
      const children = Array.isArray(zoneNode.children) ? zoneNode.children : []
      return children.some((child) => {
        const childDeviceId = String(child?.deviceId || '')
        const childTerminalId = String(child?.terminalId || '')
        return childDeviceId === targetId || childTerminalId === targetId
      })
    },
    resolveDropZoneNode(data) {
      if (!data || typeof data !== 'object') return null
      if (data.type === 'zone') return data
      if (data.type !== 'empty') return null
      const zoneId = String(data.zoneId || '')
      if (!zoneId) return null
      return this.treeData.find((item) => item && item.type === 'zone' && String(item.zoneId) === zoneId) || null
    },
    isDropAllowed(data, dragging) {
      const zoneNode = this.resolveDropZoneNode(data)
      if (!zoneNode || !dragging) return false
      const targetZoneId = String(zoneNode.zoneId || 'unassigned')
      const sourceZoneId = String(dragging.zoneId || 'unassigned')
      if (targetZoneId === sourceZoneId) return false
      const dragId = String(dragging.terminalId || dragging.id || '')
      if (!dragId) return false
      if (this.zoneHasTerminal(zoneNode, dragId)) return false
      return true
    },
    parseDraggingFromEvent(event) {
      if (!event || !event.dataTransfer) return this.draggingDevice
      const raw = event.dataTransfer.getData('application/json')
      if (!raw) return this.draggingDevice
      try {
        const parsed = JSON.parse(raw)
        if (parsed && parsed.id) {
          return {
            id: String(parsed.id),
            terminalId: String(parsed.terminalId || parsed.id || ''),
            name: String(parsed.name || parsed.id || '终端'),
            zoneId: String(parsed.zoneId || 'unassigned'),
            zoneName: String(parsed.zoneName || ''),
            sourceType: String(parsed.sourceType || '')
          }
        }
      } catch (err) {
        return this.draggingDevice
      }
      return this.draggingDevice
    },
    handleTreeDragEnter(data) {
      if (!this.draggingDevice) return
      if (this.isDropAllowed(data, this.draggingDevice)) {
        this.dragTargetZoneId = String(data.zoneId || 'unassigned')
        this.dragForbidden = false
        this.queueAutoExpandZone(data)
      } else {
        this.dragTargetZoneId = ''
        this.dragForbidden = true
        this.clearDragExpandTimer()
      }
    },
    handleTreeDragOver(data, event) {
      const dragging = this.parseDraggingFromEvent(event)
      if (!dragging) return
      const allowed = this.isDropAllowed(data, dragging)
      if (allowed) {
        event.preventDefault()
        event.dataTransfer.dropEffect = 'move'
        this.dragForbidden = false
        this.dragTargetZoneId = String(data.zoneId || 'unassigned')
        this.queueAutoExpandZone(data)
      } else {
        event.dataTransfer.dropEffect = 'none'
        this.dragTargetZoneId = ''
        this.dragForbidden = true
        this.clearDragExpandTimer()
      }
    },
    handleTreeDragLeave(data) {
      if (!this.draggingDevice) return
      const zoneNode = this.resolveDropZoneNode(data)
      if (!zoneNode) return
      const zoneId = String(zoneNode.zoneId || 'unassigned')
      if (this.dragTargetZoneId === zoneId) {
        this.dragTargetZoneId = ''
      }
      this.clearDragExpandTimer()
    },
    handleTreeDrop(data, event) {
      if (this.isMobileLayout) return
      const dragging = this.parseDraggingFromEvent(event)
      const zoneNode = this.resolveDropZoneNode(data)
      if (!dragging || !zoneNode) return
      if (!this.isDropAllowed(zoneNode, dragging)) {
        this.dragForbidden = true
        const dragId = String(dragging.terminalId || dragging.id || '')
        if (dragId && this.zoneHasTerminal(zoneNode, dragId)) {
          this.$message.warning('该分区已包含该终端，不能重复加入')
        }
        return
      }
      event.preventDefault()
      this.dragForbidden = false
      this.dragTargetZoneId = ''
      this.clearDragExpandTimer()
      this.terminalMutationUnsupported('move')
      this.endDeviceDrag()
    },
    handleRemoveDropDragEnter() {
      if (this.removeDrop.state === 'loading') return
      if (!this.canUseRemoveDrop(this.draggingDevice)) return
      this.syncRemoveDropFromDragging(this.draggingDevice, 'hover')
    },
    handleRemoveDropDragOver(event) {
      if (this.removeDrop.state === 'loading') {
        if (event?.dataTransfer) event.dataTransfer.dropEffect = 'none'
        return
      }
      const dragging = this.parseDraggingFromEvent(event)
      if (!this.canUseRemoveDrop(dragging)) {
        if (event?.dataTransfer) event.dataTransfer.dropEffect = 'none'
        return
      }
      if (event?.dataTransfer) event.dataTransfer.dropEffect = 'move'
      this.syncRemoveDropFromDragging(dragging, 'hover')
    },
    handleRemoveDropDragLeave() {
      if (this.removeDrop.state === 'loading') return
      if (!this.canUseRemoveDrop(this.draggingDevice)) {
        this.resetRemoveDrop()
        return
      }
      this.syncRemoveDropFromDragging(this.draggingDevice, 'idle')
    },
    async handleRemoveDropDrop(event) {
      if (this.removeDrop.state === 'loading') return
      const dragging = this.parseDraggingFromEvent(event)
      if (!this.canUseRemoveDrop(dragging)) return
      this.terminalMutationUnsupported('move')
      this.endDeviceDrag()
    },
    cancelMoveDialog() {
      if (this.moveDialog.loading) return
      this.moveDialog.visible = false
      this.moveDialog.pending = null
      this.dragTargetZoneId = ''
      this.dragForbidden = false
      this.clearDragExpandTimer()
      this.syncRemoveDropFromDragging(this.draggingDevice, 'idle')
    },
    async confirmMoveDialog() {
      const pending = this.moveDialog.pending
      if (!pending || this.moveDialog.loading) return
      if (pending.mode === 'manual' && !pending.targetZoneId) {
        this.$message.warning('请先选择目标分区')
        return
      }
      this.terminalMutationUnsupported('move')
      this.moveDialog.visible = false
      this.moveDialog.pending = null
      this.dragTargetZoneId = ''
      this.dragForbidden = false
      this.endDeviceDrag()
    },
    moveTargetOptions(sourceZoneId) {
      const sourceKey = String(sourceZoneId || '')
      return (Array.isArray(this.zones) ? this.zones : []).filter((zone) => {
        const zoneId = String(zone?.id ?? '')
        return zoneId && zoneId !== sourceKey
      })
    },
    onMoveTargetChange(value) {
      if (!this.moveDialog.pending) return
      this.moveDialog.pending.targetZoneName = this.zoneLabelById(value)
    },
    preferredDeviceZoneId(device) {
      const zones = this.deviceZoneIds(device)
      const selected = String(this.selectedZone || '')
      if (selected && zones.includes(selected) && selected !== '0' && selected !== 'unassigned') {
        return selected
      }
      return zones.find((zoneId) => zoneId && zoneId !== '0' && zoneId !== 'unassigned') || ''
    },
    canRemoveDeviceZone(device) {
      return Boolean(this.preferredDeviceZoneId(device))
    },
    openMoveDialogForDevice(device) {
      const deviceId = this.terminalKey(device) || String(device?.id || '')
      if (!deviceId) {
        this.$message.warning('缺少终端 ID，无法移动')
        return
      }
      this.terminalMutationUnsupported('move')
    },
    async removeDeviceFromCurrentZone(device) {
      const deviceId = this.terminalKey(device) || String(device?.id || '')
      const sourceZoneId = this.preferredDeviceZoneId(device)
      if (!deviceId || !sourceZoneId) {
        this.$message.warning('当前终端不在可移除的分区内')
        return
      }
      this.terminalMutationUnsupported('move')
    },
    zoneLabel(zone) {
      const value = zone !== undefined && zone !== null ? String(zone) : '0'
      const mapping = {
        '0': '区域零',
        '1': '区域一',
        '2': '区域二',
        '3': '区域三',
        '4': '区域四',
        '5': '区域五',
        '6': '区域六',
        '7': '区域七',
        '8': '区域八',
        '9': '区域九'
      }
      return mapping[value] || `区域${value}`
    },
    zoneNameFromItem(item) {
      if (!item || typeof item !== 'object') return ''
      return String(item.name || item.zonename || item.zone_name || item.description || '').trim()
    },
    zoneSortLabel(zone) {
      if (!zone || typeof zone !== 'object') return ''
      const zoneId = zone.zoneId !== undefined && zone.zoneId !== null
        ? String(zone.zoneId)
        : (zone.id !== undefined && zone.id !== null ? String(zone.id) : '')
      const label = String(
        zone.label || zone.name || zone.zonename || zone.zone_name || zone.description || ''
      ).trim()
      return label || this.zoneLabelById(zoneId)
    },
    compareZoneEntries(left, right) {
      const leftId = left?.zoneId !== undefined && left?.zoneId !== null
        ? String(left.zoneId)
        : (left?.id !== undefined && left?.id !== null ? String(left.id) : '')
      const rightId = right?.zoneId !== undefined && right?.zoneId !== null
        ? String(right.zoneId)
        : (right?.id !== undefined && right?.id !== null ? String(right.id) : '')
      const leftLabel = this.zoneSortLabel(left)
      const rightLabel = this.zoneSortLabel(right)
      const isLeftUnassigned = !leftId || leftId === '0' || leftId === 'unassigned' || leftLabel === '无分区终端'
      const isRightUnassigned = !rightId || rightId === '0' || rightId === 'unassigned' || rightLabel === '无分区终端'
      if (isLeftUnassigned !== isRightUnassigned) {
        return isLeftUnassigned ? 1 : -1
      }
      const leftStartsWithLetter = /^[A-Za-z]/.test(leftLabel)
      const rightStartsWithLetter = /^[A-Za-z]/.test(rightLabel)
      if (leftStartsWithLetter !== rightStartsWithLetter) {
        return leftStartsWithLetter ? -1 : 1
      }
      const byLabel = leftLabel.localeCompare(rightLabel, 'zh-Hans-CN-u-co-pinyin', {
        numeric: true,
        sensitivity: 'base'
      })
      if (byLabel !== 0) return byLabel
      return leftId.localeCompare(rightId, 'en', { numeric: true, sensitivity: 'base' })
    },
    sortZonesForDisplay(zones) {
      if (!Array.isArray(zones)) return []
      return [...zones].sort((left, right) => this.compareZoneEntries(left, right))
    },
    zoneLabelById(zoneId) {
      const key = zoneId !== undefined && zoneId !== null ? String(zoneId) : ''
      if (!key || key === '0' || key === 'unassigned') {
        return '无分区终端'
      }
      const match = this.zones.find((item) => String(item.id) === key)
      const label = this.zoneNameFromItem(match)
      if (label) {
        return label
      }
      if (match) {
        return this.zoneLabel(key)
      }
      if (this.zones.length) {
        return this.zoneLabel(key)
      }
      return key ? this.zoneLabel(key) : '无分区终端'
    },
    mapTreeData() {
      const zones = {}
      const zoneIds = new Set(this.zones.map((zone) => String(zone.id)))
      const hasZones = zoneIds.size > 0
      const normalizeZoneId = (value) => {
        const key = value !== undefined && value !== null ? String(value) : ''
        if (!key || key === '0') return 'unassigned'
        if (hasZones && !zoneIds.has(key)) return 'unassigned'
        return key
      }
      this.zones.forEach((zone) => {
        const id = String(zone.id)
        zones[id] = {
          id: `zone-${id}`,
          label: this.zoneLabelById(id),
          zoneId: id,
          type: 'zone',
          children: []
        }
      })
      zones.unassigned = {
        id: 'zone-unassigned',
        label: this.zoneLabelById('unassigned'),
        zoneId: 'unassigned',
        type: 'zone',
        children: []
      }
      this.terminals.forEach((item) => {
        const label = item.name || item.ip || item.id
        if (!label) return
        const deviceId = this.terminalKey(item) || String(item.id || '')
        const terminalId = String(item.terminalid || deviceId || '')
        const deviceZones = this.deviceZoneIds(item).map((zoneId) => normalizeZoneId(zoneId))
        deviceZones.forEach((zoneId) => {
          if (!zones[zoneId]) {
            zones[zoneId] = {
              id: `zone-${zoneId}`,
              label: this.zoneLabelById(zoneId),
              zoneId,
              type: 'zone',
              children: []
            }
          }
          zones[zoneId].children.push({
            id: `device-${zoneId}-${deviceId}`,
            label: String(label),
            type: 'device',
            zoneId,
            deviceId: String(deviceId),
            terminalId
          })
        })
      })
      return this.sortZonesForDisplay(Object.values(zones))
    },
    mapDevices(payload, fallbackZone = '', markUnassigned = false) {
      const list = extractList(payload)
      return list.map((item, index) => {
        if (!isValidDeviceItem(item)) return null
        const terminalId = String(item?.terminalid || item?.terminal_id || item?.id || `device-${index + 1}`)
        const name = resolveDeviceName(item, terminalId)
        const rawZone = item?.zone !== undefined && item?.zone !== null ? String(item.zone) : ''
        let zoneValue = fallbackZone && (rawZone === '' || rawZone === '0')
          ? String(fallbackZone)
          : (rawZone || '0')
        if (markUnassigned && (!zoneValue || zoneValue === '0')) {
          zoneValue = 'unassigned'
        }
        const zoneIds = this.normalizeZoneIds([zoneValue])
        const volume = this.toNumber(item?.volume, 0)
        return {
          id: terminalId,
          terminalid: terminalId,
          name: String(name),
          ip: item?.ip || '',
          zone: zoneIds[0],
          zoneIds,
          locationPath: this.buildLocationPath(zoneIds, String(name)),
          status: this.deriveStatus(item),
          volume,
          devicestate: item?.devicestate,
          netstate: item?.netstate,
          speechstate: item?.speechstate,
          taskstate: item?.taskstate,
          muted: volume <= 0,
          prevVolume: volume > 0 ? volume : 30
        }
      }).filter(Boolean)
    },
    deriveStatus(item) {
      const netstate = Number(item?.netstate)
      const devicestate = Number(item?.devicestate)
      const taskstate = Number(item?.taskstate)
      if (netstate === 0) return 'offline'
      if (devicestate === 0) return 'fault'
      const playingStates = [1, 3, 4, 8, 12, 25, 28]
      const talkingStates = [2, 5, 6, 9, 10, 11]
      if (playingStates.includes(taskstate)) return 'playing'
      if (talkingStates.includes(taskstate)) return 'talking'
      if ([7, 13, 15, 19].includes(taskstate)) return 'special'
      if (taskstate === 0) return 'online'
      return 'online'
    },
    runtimePlayRowState(row) {
      if (!row || typeof row !== 'object') return null
      const rawValue = row.remote_state
      if (rawValue === null || rawValue === undefined) return null
      if (typeof rawValue === 'string' && !rawValue.trim()) return null
      const numeric = Number(rawValue)
      if (Number.isFinite(numeric)) return numeric
      return null
    },
    deviceTaskState(device) {
      if (!device || typeof device !== 'object') return 0
      const status = String(device.status || '').trim()
      if (status === 'offline' || status === 'fault') {
        return 0
      }
      const runtimePlayState = device.runtimePlayState
      if (runtimePlayState === -1 && status !== 'playing') {
        return 0
      }
      return Number(device.taskstate || 0)
    },
    extractRuntimePlayTerminalIds(row) {
      const ids = Array.isArray(row?.terminal_ids)
        ? row.terminal_ids
        : Array.isArray(row?.terminalids)
          ? row.terminalids
          : []
      return ids.map((item) => String(item || '').trim()).filter(Boolean)
    },
    applyRuntimePlayOverlay(devices, runtimeRows) {
      const activeTerminalIds = new Set()
      const stoppedTerminalIds = new Set()
      const protectedStatuses = new Set(['offline', 'fault'])
      ;(Array.isArray(runtimeRows) ? runtimeRows : []).forEach((row) => {
        const state = this.runtimePlayRowState(row)
        const terminalIds = this.extractRuntimePlayTerminalIds(row)
        if (!terminalIds.length) return
        if (state === 0) {
          terminalIds.forEach((id) => {
            activeTerminalIds.add(id)
            stoppedTerminalIds.delete(id)
          })
          return
        }
        if (state === -1) {
          terminalIds.forEach((id) => {
            if (!activeTerminalIds.has(id)) {
              stoppedTerminalIds.add(id)
            }
          })
        }
      })
      return (Array.isArray(devices) ? devices : []).map((device) => {
        const next = { ...(device || {}) }
        const terminalId = this.terminalKey(next)
        if (!terminalId) return next
        if (activeTerminalIds.has(terminalId)) {
          if (protectedStatuses.has(next.status)) {
            next.runtimePlayState = 0
            return next
          }
          next.status = 'playing'
          next.taskstate = 3
          next.runtimePlayState = 0
          return next
        }
        if (stoppedTerminalIds.has(terminalId) && Number(next.taskstate) === 3) {
          if (protectedStatuses.has(next.status)) {
            next.runtimePlayState = -1
            return next
          }
          next.status = 'online'
          next.taskstate = 0
          next.runtimePlayState = -1
        }
        return next
      })
    },
    statusClass(status) {
      return `status-${status}`
    },
    statusLabel(status) {
      const labels = {
        online: '在线', offline: '离线', playing: '播放中',
        talking: '通话中', special: '工作中', fault: '停用'
      }
      return labels[status] || '未知'
    },
    statusTagType(status) {
      const types = {
        online: 'success', offline: 'info', playing: 'primary',
        talking: 'warning', special: '', fault: 'danger'
      }
      return types[status] ?? 'info'
    },
    netStateTag(value) {
      const text = String(value)
      if (text === '1') return { label: '在线', type: 'success' }
      if (text === '0') return { label: '离线', type: 'info' }
      return { label: '未知', type: 'warning' }
    },
    deviceStateTag(value) {
      const text = String(value)
      if (text === '1') return { label: '正常', type: 'success' }
      if (text === '0') return { label: '停用', type: 'danger' }
      return { label: '未知', type: 'warning' }
    },
    taskStateTag(value) {
      const state = Number(value)
      const map = {
        0: { label: '空闲', type: 'info' },
        1: { label: '定时播放', type: 'primary' },
        2: { label: '对讲', type: 'warning' },
        3: { label: '点播', type: 'primary' },
        4: { label: '选播', type: 'primary' },
        5: { label: '正在寻呼', type: 'warning' },
        6: { label: '正在被寻呼', type: 'warning' },
        7: { label: '本地扩音', type: '' },
        8: { label: 'U盘播放', type: 'primary' },
        9: { label: '接收对讲', type: 'warning' },
        10: { label: '拒绝对讲', type: 'warning' },
        11: { label: '寻呼播放', type: 'warning' },
        12: { label: '播放', type: 'primary' },
        13: { label: '采播', type: '' },
        15: { label: '手动采播', type: '' },
        19: { label: '监听', type: '' },
        25: { label: '文字语音播放', type: 'primary' },
        28: { label: '快捷播放', type: 'primary' }
      }
      return map[state] || { label: '未知', type: 'warning' }
    },
    toNumber(value, fallback) {
      const parsed = parseInt(value, 10)
      if (Number.isFinite(parsed)) return parsed
      return fallback
    },
    formatNow() {
      const now = new Date()
      const pad = (num) => String(num).padStart(2, '0')
      return `${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(now.getDate())} ${pad(now.getHours())}:${pad(now.getMinutes())}:${pad(now.getSeconds())}`
    },
    async loadTerminalSnapshot(silent = false, force = false) {
      this.loading = true
      try {
        const [allData, runtimePayload] = await Promise.all([
          fetchAllTerminalData(force),
          fetchRuntimePlayTasks(true).catch(() => ({ runtime_play_tasks: [] }))
        ])
        // 1) 解析分区列表
        const zoneList = extractList(allData.zones || allData)
        this.zones = this.sortZonesForDisplay(zoneList.map((item) => ({
          id: item.id ?? item.zone ?? item.zoneid,
          name: this.zoneNameFromItem(item)
        })).filter((zone) => zone.id !== undefined && zone.id !== null))
        // 2) 解析各分区终端
        const zoneTerminals = allData.zone_terminals || {}
        const zoneTerminalIds = new Set()
        const zoneDevices = []
        this.zones.forEach((zone) => {
          const payload = zoneTerminals[String(zone.id)]
          if (!payload) return
          const mapped = this.mapDevices(payload, String(zone.id))
          mapped.forEach((device) => {
            const key = this.terminalKey(device)
            if (key) zoneTerminalIds.add(key)
          })
          zoneDevices.push(...mapped)
        })
        // 3) 解析全终端状态，找出未分配终端
        let unassignedDevices = []
        const infoPayload = allData.terminal_info
        if (infoPayload) {
          const allDevices = this.mapDevices(infoPayload, '', true)
          unassignedDevices = allDevices
            .filter((device) => {
              const key = this.terminalKey(device)
              if (!key) return true
              return !zoneTerminalIds.has(key)
            })
            .map((device) => ({
              ...device,
              zone: 'unassigned',
              zoneIds: ['unassigned'],
              locationPath: this.buildLocationPath(['unassigned'], device.name)
            }))
        }
        const unassignedOnly = this.selectedZone === 'unassigned'
        const rawList = unassignedOnly ? unassignedDevices : [...zoneDevices, ...unassignedDevices]
        const runtimeRows = Array.isArray(runtimePayload?.runtime_play_tasks) ? runtimePayload.runtime_play_tasks : []
        this.baseTerminals = this.mergeDevicesByTerminal(rawList).map((device) => ({ ...(device || {}) }))
        this.snapshotStale = false
        this.renderTerminalSnapshot(this.baseTerminals, runtimeRows)
        this.lastUpdatedAt = this.formatNow()
        if (!silent) {
          this.$message.success('终端状态已刷新')
        }
      } catch (err) {
        this.markTerminalSnapshotStale()
        if (!silent) {
          const detail = err?.response?.data?.detail
          this.$message.error(detail || '加载终端状态失败，当前展示的是上次成功刷新结果')
        }
      } finally {
        this.loading = false
      }
    },
    async refreshData(silent = false, force = false) {
      await this.loadTerminalSnapshot(silent, force)
    },
    async fetchZones(silent = false) {
      try {
        const payload = await fetchTerminalZones()
        const list = extractList(payload)
        this.zones = this.sortZonesForDisplay(list.map((item) => ({
          id: item.id ?? item.zone ?? item.zoneid,
          name: this.zoneNameFromItem(item)
        })).filter((zone) => zone.id !== undefined && zone.id !== null))
      } catch (err) {
        if (!silent) {
          const detail = err?.response?.data?.detail
          this.$message.error(detail || '分区列表获取失败')
        }
      }
    },
    async refreshTerminals(silent = false, force = false) {
      await this.loadTerminalSnapshot(silent, force)
    },
    getTerminalId(device) {
      return this.terminalKey(device)
    },
    async applySystemVolume() {
      this.settingSystemVolume = true
      try {
        const response = await setSystemVolume(this.systemVolume)
        if (response?.success === false) {
          throw new Error(response?.message || '系统音量调整失败')
        }
        this.$message.success('系统全局音量已更新')
      } catch (error) {
        this.$message.error(error?.response?.data?.detail || error?.message || '系统音量调整失败')
      } finally {
        this.settingSystemVolume = false
      }
    },
    syncDeviceVolumeMeta(deviceId, safeVolume) {
      const targetId = String(deviceId || '')
      if (!targetId) return
      const applyMeta = (item) => {
        if (!item) return
        item.muted = safeVolume <= 0
        if (safeVolume > 0) {
          item.prevVolume = safeVolume
        }
      }
      const seen = new Set()
      ;[this.terminals, this.renderedTerminals].forEach((list) => {
        if (!Array.isArray(list)) return
        list.forEach((item) => {
          if (!item || seen.has(item)) return
          if (this.terminalKey(item) !== targetId) return
          seen.add(item)
          applyMeta(item)
        })
      })
    }
  }
}
</script>

<style lang="scss" scoped>
.device-status-page {
  padding: 24px;
  background: #f6f8fb;
  min-height: 100%;
  box-sizing: border-box;
}

.device-status-page.is-dragging {
  cursor: grabbing;
}

.device-status-page.is-drop-forbidden {
  cursor: not-allowed;
}

.page-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 16px;

  h2 {
    margin: 0;
    color: #1f2d3d;
    font-size: 22px;
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
  flex-wrap: wrap;
  justify-content: flex-end;
}

.zone-select {
  width: 140px;
}

.search-input {
  width: 220px;
}

.system-volume-control {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  color: #334155;
  white-space: nowrap;
}

.volume-control-hint {
  color: #94a3b8;
  font-size: 12px;
  line-height: 18px;
}

.update-time {
  color: #909399;
  font-size: 12px;
}

.update-time.is-stale {
  color: #e6a23c;
}

.content {
  display: grid;
  grid-template-columns: 260px 1fr;
  gap: 16px;
}

.card {
  background: #fff;
  border-radius: 10px;
  padding: 16px;
  box-shadow: 0 8px 20px rgba(31, 45, 61, 0.08);
}

.tree-panel {
  display: flex;
  flex-direction: column;
  min-height: 480px;
  max-height: calc(100vh - 180px);
  overflow: hidden;
}

.tree-scroll {
  flex: 1 1 auto;
  min-height: 0;
  overflow-y: auto;
  overflow-x: hidden;
  margin-right: -4px;
  padding-right: 4px;
}

.tree-panel ::v-deep .el-tree {
  min-width: 0;
}

.panel-title {
  font-weight: 600;
  color: #1f2d3d;
  margin-bottom: 12px;
}

.panel-title-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
}

.tree-panel-body {
  display: flex;
  flex-direction: column;
  min-height: 0;
  flex: 1 1 auto;
}

.tree-node-content {
  width: 100%;
  display: inline-flex;
  align-items: center;
  gap: 6px;
  min-height: 26px;
  padding: 2px 6px;
  border-radius: 6px;
  transition: background-color 0.16s ease, color 0.16s ease, border-color 0.16s ease;
  border: 1px solid transparent;
}

.tree-node-content.is-zone {
  font-weight: 500;
}

.tree-node-content.is-device {
  cursor: default;
}

.tree-node-content.is-empty {
  color: #a0a7b4;
  font-size: 12px;
  cursor: default;
}

.tree-device-drag-target {
  width: 100%;
  display: inline-flex;
  align-items: center;
  gap: 6px;
  min-height: 26px;
  cursor: grab;
}

.tree-device-drag-target:active {
  cursor: grabbing;
}

.tree-device-label {
  min-width: 0;
  flex: 0 1 auto;
}

.tree-device-drag-hint {
  margin-left: auto;
  color: #a0a7b4;
  font-size: 11px;
  white-space: nowrap;
  opacity: 0;
  transition: opacity 0.16s ease;
}

.tree-device-drag-target:hover .tree-device-drag-hint {
  opacity: 1;
}

.tree-node-content.is-zone-available {
  background: rgba(64, 158, 255, 0.1);
  border-color: rgba(64, 158, 255, 0.45);
  color: #2f6fbf;
}

.tree-node-content.is-zone-has-device {
  background: rgba(230, 162, 60, 0.14);
  border-color: rgba(230, 162, 60, 0.56);
  color: #8a5a00;
}

.tree-node-content.is-drop-target {
  background: rgba(64, 158, 255, 0.2);
  border-color: #2f86ff;
  color: #1f2d3d;
  box-shadow: inset 0 0 0 1px rgba(47, 134, 255, 0.36);
}

.tree-node-content.is-drop-forbidden {
  cursor: not-allowed;
}

.tree-node-icon {
  color: #7a869a;
  font-size: 14px;
}

.remove-drop-zone {
  margin-top: 12px;
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 12px 14px;
  border-radius: 12px;
  border: 1px dashed #c0c4cc;
  background: #f7f8fa;
  transition: all 0.18s ease;
  flex: 0 0 auto;
  position: sticky;
  bottom: 0;
  z-index: 2;
}

.remove-drop-zone.is-hover {
  border-color: #e06c75;
  background: #fff3f1;
  box-shadow: 0 0 0 1px rgba(224, 108, 117, 0.12);
}

.remove-drop-zone.is-loading {
  border-style: solid;
  border-color: #e6a23c;
  background: #fff8eb;
}

.remove-drop-icon {
  width: 34px;
  height: 34px;
  border-radius: 50%;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  background: rgba(144, 147, 153, 0.14);
  color: #606266;
  flex: 0 0 auto;
  transition: all 0.18s ease;
}

.remove-drop-zone.is-hover .remove-drop-icon {
  background: rgba(224, 108, 117, 0.16);
  color: #d34a5a;
  transform: scale(1.06);
}

.remove-drop-zone.is-loading .remove-drop-icon {
  background: rgba(230, 162, 60, 0.16);
  color: #c97b00;
}

.remove-drop-copy {
  min-width: 0;
}

.remove-drop-title {
  color: #1f2d3d;
  font-weight: 600;
  line-height: 1.4;
}

.remove-drop-desc {
  margin-top: 2px;
  color: #7a869a;
  font-size: 12px;
  line-height: 1.4;
}

.legend {
  margin-top: 16px;
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 8px;
  color: #5e6d82;
  font-size: 13px;
  flex: 0 0 auto;
}

.legend-item {
  display: flex;
  align-items: center;
  gap: 6px;
}

.dot {
  width: 10px;
  height: 10px;
  border-radius: 50%;
  display: inline-block;

  &.online {
    background: #4caf50;
  }
  &.offline {
    background: #c0c4cc;
  }
  &.playing {
    background: #409eff;
    box-shadow: 0 0 0 6px rgba(64, 158, 255, 0.16);
  }
  &.fault {
    background: #f56c6c;
  }
}

.cards-panel {
  min-height: 480px;
}

.card-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
  gap: 12px;
}

.card-loading {
  padding: 18px;
  color: #7a869a;
  font-size: 13px;
}

.device-card {
  border-radius: 12px;
  padding: 14px;
  background: #f7f9fc;
  border: 1px solid #e4e7ed;
  transition: all 0.2s ease;
  animation: card-enter 0.35s ease both;
  cursor: grab;

  &:hover {
    box-shadow: 0 12px 24px rgba(31, 45, 61, 0.12);
    transform: translateY(-2px);
  }
}

.device-card.is-drag-source {
  opacity: 1;
  border-color: #409eff;
  box-shadow: 0 0 0 2px rgba(64, 158, 255, 0.18);
  cursor: grabbing;
}

@keyframes card-enter {
  from {
    opacity: 0;
    transform: translateY(8px);
  }
  to {
    opacity: 1;
    transform: translateY(0);
  }
}

.device-header {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  margin-bottom: 8px;
}

.device-name {
  font-weight: 600;
  color: #1f2d3d;
}

.device-location {
  color: #7a869a;
  font-size: 12px;
  margin-top: 2px;
}

.device-tags {
  display: flex;
  gap: 6px;
  flex-wrap: wrap;
  margin-bottom: 10px;
}

.device-stats {
  display: flex;
  justify-content: space-between;
  gap: 8px;
  margin-bottom: 10px;
}

.stat-item {
  display: flex;
  flex-direction: column;
  color: #5e6d82;
  font-size: 12px;

  strong {
    color: #1f2d3d;
    font-size: 16px;
    margin-top: 4px;
    word-break: break-all;
  }
}

.network-stat-item {
  .terminal-id-label {
    font-weight: 700;
    color: #1f2d3d;
  }

  .terminal-ip-label {
    margin-top: 8px;
  }
}

.device-actions {
  display: flex;
  align-items: center;
  gap: 6px;
}

.mobile-device-actions {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-left: auto;
}

.volume-control {
  display: flex;
  align-items: center;
  gap: 8px;
}

.status-online {
  background: linear-gradient(135deg, #f0fff4 0%, #f7fbf7 100%);
  border-color: #b7eb8f;
}

.status-offline {
  background: linear-gradient(135deg, #f5f7fa 0%, #f2f3f5 100%);
  border-color: #dcdfe6;
  color: #909399;
}

.status-playing {
  background: linear-gradient(135deg, #f0f7ff 0%, #f4f9ff 100%);
  border-color: #b3d8ff;
  position: relative;
  overflow: hidden;
}

.status-playing::after {
  content: '';
  position: absolute;
  inset: 0;
  background: radial-gradient(circle, rgba(64, 158, 255, 0.08) 0%, rgba(255, 255, 255, 0) 60%);
  animation: pulse 2s infinite;
}

.status-talking {
  background: linear-gradient(135deg, #fff7e6 0%, #fffbe6 100%);
  border-color: #ffe58f;
}

.status-special {
  background: linear-gradient(135deg, #f9f0ff 0%, #faf5ff 100%);
  border-color: #d3adf7;
}

.status-fault {
  background: linear-gradient(135deg, #fff5f5 0%, #fff9f9 100%);
  border-color: #fbc4c4;
}

@keyframes pulse {
  0% {
    opacity: 0.35;
  }
  50% {
    opacity: 0.8;
  }
  100% {
    opacity: 0.35;
  }
}

.drag-ghost {
  position: fixed;
  top: 0;
  left: 0;
  transform: translate(-9999px, -9999px);
  z-index: -1;
  display: inline-flex;
  flex-direction: column;
  align-items: center;
  gap: 6px;
  padding: 8px 12px;
  border-radius: 12px;
  background: rgba(31, 45, 61, 0.9);
  color: #fff;
  font-size: 13px;
  line-height: 1;
  box-shadow: 0 8px 20px rgba(31, 45, 61, 0.25);
}

.drag-ghost-icon {
  font-size: 18px;
}

.drag-ghost-name {
  max-width: 220px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  font-weight: 600;
}

.move-confirm-text {
  color: #303133;
  line-height: 1.6;
}

.move-confirm-title {
  font-weight: 600;
  color: #1f2d3d;
}

.move-confirm-subtitle {
  margin-top: 4px;
  color: #7a869a;
  font-size: 12px;
}

.move-form {
  margin-top: 12px;
}

.move-select {
  width: 100%;
}

@media (max-width: 768px) {
  .device-status-page {
    padding: 14px;
    padding-bottom: calc(18px + var(--safe-bottom));
  }

  .page-header {
    flex-direction: column;
    align-items: flex-start;
    gap: 12px;
  }

  .page-header h2 {
    font-size: 20px;
  }

  .header-actions {
    width: 100%;
    flex-direction: column;
    align-items: stretch;
  }

  .zone-select,
  .search-input {
    width: 100%;
  }

  .update-time {
    width: 100%;
  }

  .content {
    grid-template-columns: 1fr;
  }

  .tree-panel {
    min-height: 0;
    max-height: none;
  }

  .tree-panel.is-collapsed {
    padding-bottom: 12px;
  }

  .legend {
    grid-template-columns: 1fr 1fr;
  }

  .card-grid {
    grid-template-columns: 1fr;
  }

  .device-header,
  .device-stats,
  .device-actions,
  .volume-control {
    flex-direction: column;
    align-items: stretch;
  }

  .mobile-device-actions {
    width: 100%;
    margin-left: 0;
    justify-content: space-between;
  }

  .tree-device-drag-target {
    cursor: default;
  }
}
</style>
