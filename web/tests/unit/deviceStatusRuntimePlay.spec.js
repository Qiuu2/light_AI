jest.mock('@/api/dataService', () => ({
  fetchTerminalZones: jest.fn(),
  fetchAllTerminalData: jest.fn(),
  fetchRuntimePlayTasks: jest.fn(),
  setTerminalVolume: jest.fn(),
  moveTerminalZone: jest.fn()
}))

jest.mock('@/utils/assistantRefreshBus', () => ({
  onAssistantRefresh: jest.fn(),
  offAssistantRefresh: jest.fn()
}))

import DeviceStatus from '@/views/device-status/index.vue'
import { fetchAllTerminalData, fetchRuntimePlayTasks } from '@/api/dataService'

describe('DeviceStatus runtime play overlay', () => {
  afterEach(() => {
    jest.useRealTimers()
    fetchAllTerminalData.mockReset()
    fetchRuntimePlayTasks.mockReset()
  })

  it('marks runtime-play terminals as playing while the task is active', () => {
    const { methods } = DeviceStatus
    const ctx = {
      runtimePlayRowState: methods.runtimePlayRowState,
      extractRuntimePlayTerminalIds: methods.extractRuntimePlayTerminalIds,
      terminalKey: (device) => String(device?.terminalid || device?.id || '')
    }

    const rows = methods.applyRuntimePlayOverlay.call(ctx, [
      { terminalid: '101', status: 'online', taskstate: 0 }
    ], [
      { terminal_ids: ['101'], remote_state: 0, status: '执行中' }
    ])

    expect(rows[0]).toEqual(expect.objectContaining({
      terminalid: '101',
      status: 'playing',
      taskstate: 3,
      runtimePlayState: 0
    }))
  })

  it('keeps offline terminals offline even when a runtime-play task is active', () => {
    const { methods } = DeviceStatus
    const ctx = {
      runtimePlayRowState: methods.runtimePlayRowState,
      extractRuntimePlayTerminalIds: methods.extractRuntimePlayTerminalIds,
      terminalKey: (device) => String(device?.terminalid || device?.id || '')
    }

    const rows = methods.applyRuntimePlayOverlay.call(ctx, [
      { terminalid: '101', status: 'offline', taskstate: 0, netstate: 0 }
    ], [
      { terminal_ids: ['101'], remote_state: 0, status: '执行中' }
    ])

    expect(rows[0]).toEqual(expect.objectContaining({
      terminalid: '101',
      status: 'offline',
      taskstate: 0,
      runtimePlayState: 0
    }))
  })

  it('keeps fault terminals faulted even when a runtime-play task is active', () => {
    const { methods } = DeviceStatus
    const ctx = {
      runtimePlayRowState: methods.runtimePlayRowState,
      extractRuntimePlayTerminalIds: methods.extractRuntimePlayTerminalIds,
      terminalKey: (device) => String(device?.terminalid || device?.id || '')
    }

    const rows = methods.applyRuntimePlayOverlay.call(ctx, [
      { terminalid: '101', status: 'fault', taskstate: 0, devicestate: 0 }
    ], [
      { terminal_ids: ['101'], remote_state: 0, status: '执行中' }
    ])

    expect(rows[0]).toEqual(expect.objectContaining({
      terminalid: '101',
      status: 'fault',
      taskstate: 0,
      runtimePlayState: 0
    }))
  })

  it('clears runtime-play state after the temp task stops', () => {
    const { methods } = DeviceStatus
    const ctx = {
      runtimePlayRowState: methods.runtimePlayRowState,
      extractRuntimePlayTerminalIds: methods.extractRuntimePlayTerminalIds,
      terminalKey: (device) => String(device?.terminalid || device?.id || '')
    }

    const rows = methods.applyRuntimePlayOverlay.call(ctx, [
      { terminalid: '101', status: 'playing', taskstate: 3 }
    ], [
      { terminal_ids: ['101'], remote_state: -1, status: '停止' }
    ])

    expect(rows[0]).toEqual(expect.objectContaining({
      terminalid: '101',
      status: 'online',
      taskstate: 0,
      runtimePlayState: -1
    }))
  })

  it('does not restore a real offline terminal to online when the temp task stops', () => {
    const { methods } = DeviceStatus
    const ctx = {
      runtimePlayRowState: methods.runtimePlayRowState,
      extractRuntimePlayTerminalIds: methods.extractRuntimePlayTerminalIds,
      terminalKey: (device) => String(device?.terminalid || device?.id || '')
    }

    const rows = methods.applyRuntimePlayOverlay.call(ctx, [
      { terminalid: '101', status: 'offline', taskstate: 3, netstate: 0 }
    ], [
      { terminal_ids: ['101'], remote_state: -1, status: '停止' }
    ])

    expect(rows[0]).toEqual(expect.objectContaining({
      terminalid: '101',
      status: 'offline',
      taskstate: 3,
      runtimePlayState: -1
    }))
  })

  it('syncRuntimePlayPolling only keeps polling while active runtime tasks exist', () => {
    const { methods } = DeviceStatus
    const ctx = {
      runtimePlayRows: [{ terminal_ids: ['101'], remote_state: 0, status: '执行中' }],
      runtimePlayRowState: methods.runtimePlayRowState,
      hasActiveRuntimePlayRows: methods.hasActiveRuntimePlayRows,
      startRuntimePlayPolling: jest.fn(),
      stopRuntimePlayPolling: jest.fn()
    }

    methods.syncRuntimePlayPolling.call(ctx, ctx.runtimePlayRows)
    expect(ctx.startRuntimePlayPolling).toHaveBeenCalledTimes(1)
    expect(ctx.stopRuntimePlayPolling).not.toHaveBeenCalled()

    methods.syncRuntimePlayPolling.call(ctx, [{ terminal_ids: ['101'], remote_state: -1, status: '停止' }])
    expect(ctx.stopRuntimePlayPolling).toHaveBeenCalledTimes(1)
  })

  it('status text without remote_state does not count as an active runtime play', () => {
    const { methods } = DeviceStatus
    const ctx = {
      runtimePlayRows: [{ terminal_ids: ['101'], status: '执行中' }],
      runtimePlayRowState: methods.runtimePlayRowState,
      hasActiveRuntimePlayRows: methods.hasActiveRuntimePlayRows,
      startRuntimePlayPolling: jest.fn(),
      stopRuntimePlayPolling: jest.fn()
    }

    expect(methods.runtimePlayRowState.call(ctx, { terminal_ids: ['101'], status: '执行中' })).toBeNull()
    methods.syncRuntimePlayPolling.call(ctx, ctx.runtimePlayRows)
    expect(ctx.startRuntimePlayPolling).not.toHaveBeenCalled()
    expect(ctx.stopRuntimePlayPolling).toHaveBeenCalledTimes(1)
  })

  it('blank remote_state does not count as an active runtime play', () => {
    const { methods } = DeviceStatus
    const ctx = {
      runtimePlayRows: [{ terminal_ids: ['101'], remote_state: '', status: '待确认' }],
      runtimePlayRowState: methods.runtimePlayRowState,
      hasActiveRuntimePlayRows: methods.hasActiveRuntimePlayRows,
      startRuntimePlayPolling: jest.fn(),
      stopRuntimePlayPolling: jest.fn()
    }

    expect(methods.runtimePlayRowState.call(ctx, { terminal_ids: ['101'], remote_state: '', status: '待确认' })).toBeNull()
    methods.syncRuntimePlayPolling.call(ctx, ctx.runtimePlayRows)
    expect(ctx.startRuntimePlayPolling).not.toHaveBeenCalled()
    expect(ctx.stopRuntimePlayPolling).toHaveBeenCalledTimes(1)
  })

  it('deviceTaskState returns idle for offline and fault devices', () => {
    const { methods } = DeviceStatus

    expect(methods.deviceTaskState.call({}, { status: 'offline', taskstate: 3, runtimePlayState: 0 })).toBe(0)
    expect(methods.deviceTaskState.call({}, { status: 'fault', taskstate: 12, runtimePlayState: 0 })).toBe(0)
    expect(methods.deviceTaskState.call({}, { status: 'online', taskstate: 3, runtimePlayState: 0 })).toBe(3)
    expect(methods.deviceTaskState.call({}, { status: 'online', taskstate: 3, runtimePlayState: -1 })).toBe(0)
  })

  it('marks the snapshot stale and removes runtime overlay when refresh falls back to the last good snapshot', () => {
    const { methods } = DeviceStatus
    const ctx = {
      baseTerminals: [{ terminalid: '101', status: 'online', taskstate: 0 }],
      runtimePlayRows: [{ terminal_ids: ['101'], remote_state: 0, status: 'active' }],
      terminals: [{ terminalid: '101', status: 'playing', taskstate: 3, runtimePlayState: 0 }],
      snapshotStale: false,
      treeData: [],
      renderedTerminals: [],
      runtimePlayRowState: methods.runtimePlayRowState,
      extractRuntimePlayTerminalIds: methods.extractRuntimePlayTerminalIds,
      terminalKey: (device) => String(device?.terminalid || device?.id || ''),
      hasActiveRuntimePlayRows: methods.hasActiveRuntimePlayRows,
      syncRuntimePlayPolling: methods.syncRuntimePlayPolling,
      applyRuntimePlayOverlay: methods.applyRuntimePlayOverlay,
      filterTerminals: (list) => list,
      startRenderCards: jest.fn(),
      mapTreeData: jest.fn(() => ['tree']),
      startRuntimePlayPolling: jest.fn(),
      stopRuntimePlayPolling: jest.fn(),
      renderTerminalSnapshot: methods.renderTerminalSnapshot
    }

    methods.markTerminalSnapshotStale.call(ctx)

    expect(ctx.snapshotStale).toBe(true)
    expect(ctx.runtimePlayRows).toEqual([])
    expect(ctx.stopRuntimePlayPolling).toHaveBeenCalledTimes(1)
    expect(ctx.terminals[0]).toEqual(expect.objectContaining({
      terminalid: '101',
      status: 'online',
      taskstate: 0
    }))
    expect(ctx.startRenderCards).toHaveBeenCalledWith(ctx.terminals)
    expect(ctx.treeData).toEqual(['tree'])
  })

  it('sorts zones alphabetically and keeps unassigned last in the tree', () => {
    const { methods } = DeviceStatus
    const ctx = {
      zones: [
        { id: '3', name: 'D区' },
        { id: '1', name: 'A区' },
        { id: '2', name: 'C区' }
      ],
      terminals: [
        { id: 't3', terminalid: 't3', name: '后排POE3', zoneIds: ['3'] },
        { id: 't1', terminalid: 't1', name: '讲台终端', zoneIds: ['1'] },
        { id: 't2', terminalid: 't2', name: '报警主机-0', zoneIds: ['unassigned'] }
      ],
      zoneLabel: methods.zoneLabel,
      zoneNameFromItem: methods.zoneNameFromItem,
      zoneSortLabel: methods.zoneSortLabel,
      compareZoneEntries: methods.compareZoneEntries,
      sortZonesForDisplay: methods.sortZonesForDisplay,
      zoneLabelById: methods.zoneLabelById,
      terminalKey: (device) => String(device?.terminalid || device?.id || ''),
      deviceZoneIds: (device) => Array.isArray(device?.zoneIds) ? device.zoneIds : [device?.zone]
    }

    const tree = methods.mapTreeData.call(ctx)

    expect(tree.map((node) => node.label)).toEqual(['A区', 'C区', 'D区', '无分区终端'])
  })
  it('refreshData forwards force to loadTerminalSnapshot', async() => {
    const { methods } = DeviceStatus
    const ctx = {
      loadTerminalSnapshot: jest.fn(() => Promise.resolve())
    }

    await methods.refreshData.call(ctx, true, true)

    expect(ctx.loadTerminalSnapshot).toHaveBeenCalledWith(true, true)
  })

  it('loadTerminalSnapshot passes force=true to fetchAllTerminalData', async() => {
    const { methods } = DeviceStatus
    fetchAllTerminalData.mockResolvedValue({
      zones: [],
      zone_terminals: {},
      terminal_info: []
    })
    fetchRuntimePlayTasks.mockResolvedValue({ runtime_play_tasks: [] })

    const ctx = {
      loading: false,
      zones: [],
      selectedZone: '',
      baseTerminals: [],
      snapshotStale: false,
      lastUpdatedAt: '',
      $message: { success: jest.fn(), error: jest.fn() },
      sortZonesForDisplay: jest.fn((list) => list),
      zoneNameFromItem: jest.fn(() => ''),
      mapDevices: jest.fn(() => []),
      terminalKey: jest.fn(() => ''),
      mergeDevicesByTerminal: jest.fn((list) => list),
      renderTerminalSnapshot: jest.fn(),
      formatNow: jest.fn(() => 'now'),
      markTerminalSnapshotStale: jest.fn(),
      buildLocationPath: jest.fn(() => '')
    }

    await methods.loadTerminalSnapshot.call(ctx, true, true)

    expect(fetchAllTerminalData).toHaveBeenCalledWith(true)
  })

  it('applyAssistantTerminalStateOptimistic re-enables matching terminals when remote_state is 0', () => {
    const { methods } = DeviceStatus
    const ctx = {
      baseTerminals: [{ terminalid: '11', devicestate: 0, netstate: 1, taskstate: 0, status: 'fault' }],
      terminals: [{ terminalid: '11', devicestate: 0, netstate: 1, taskstate: 0, status: 'fault' }],
      terminalKey: (device) => String(device?.terminalid || device?.id || ''),
      collectAssistantTerminalStateTargets: methods.collectAssistantTerminalStateTargets,
      deriveStatus: methods.deriveStatus,
      startRenderCards: jest.fn(),
      filterTerminals: jest.fn((list) => list)
    }

    const changed = methods.applyAssistantTerminalStateOptimistic.call(ctx, {
      intent: 'enable_terminal',
      action_log: [
        {
          action: 'enable_terminal',
          details: {
            remote_state: 0,
            terminal_ids: ['11']
          }
        }
      ]
    })

    expect(changed).toBe(true)
    expect(ctx.baseTerminals[0]).toEqual(expect.objectContaining({
      terminalid: '11',
      devicestate: 1,
      status: 'online'
    }))
    expect(ctx.terminals[0]).toEqual(expect.objectContaining({
      terminalid: '11',
      devicestate: 1,
      status: 'online'
    }))
    expect(ctx.startRenderCards).toHaveBeenCalledWith(ctx.terminals)
  })

  it('handleAssistantRefresh keeps optimistic enable and schedules a forced refresh', () => {
    jest.useFakeTimers()
    const { methods } = DeviceStatus
    const ctx = {
      assistantTerminalRefreshTimer: null,
      refreshData: jest.fn(() => Promise.resolve()),
      hasAssistantRefreshAction: methods.hasAssistantRefreshAction,
      collectAssistantRefreshActions: methods.collectAssistantRefreshActions,
      applyAssistantTerminalStateOptimistic: jest.fn(() => true),
      queueAssistantTerminalForceRefresh: methods.queueAssistantTerminalForceRefresh,
      clearAssistantTerminalRefreshTimer: methods.clearAssistantTerminalRefreshTimer
    }

    methods.handleAssistantRefresh.call(ctx, {
      intent: 'enable_terminal',
      action_log: [{ action: 'enable_terminal', details: { remote_state: 0, terminal_ids: ['11'] } }]
    })

    expect(ctx.applyAssistantTerminalStateOptimistic).toHaveBeenCalled()
    expect(ctx.refreshData).not.toHaveBeenCalled()

    jest.runAllTimers()

    expect(ctx.refreshData).toHaveBeenCalledTimes(1)
    expect(ctx.refreshData).toHaveBeenCalledWith(true, true)
  })

  it('handleAssistantRefresh falls back to normal refresh when optimistic enable cannot be applied', () => {
    jest.useFakeTimers()
    const { methods } = DeviceStatus
    const ctx = {
      assistantTerminalRefreshTimer: null,
      refreshData: jest.fn(() => Promise.resolve()),
      hasAssistantRefreshAction: methods.hasAssistantRefreshAction,
      collectAssistantRefreshActions: methods.collectAssistantRefreshActions,
      applyAssistantTerminalStateOptimistic: jest.fn(() => false),
      queueAssistantTerminalForceRefresh: methods.queueAssistantTerminalForceRefresh,
      clearAssistantTerminalRefreshTimer: methods.clearAssistantTerminalRefreshTimer
    }

    methods.handleAssistantRefresh.call(ctx, {
      intent: 'enable_terminal',
      action_log: [{ action: 'enable_terminal', details: { remote_state: 0, terminal_ids: ['11'] } }]
    })

    expect(ctx.refreshData).toHaveBeenNthCalledWith(1, true)
    jest.runAllTimers()
    expect(ctx.refreshData).toHaveBeenNthCalledWith(2, true, true)
  })

  it('consecutive terminal refreshes keep only the last forced refresh timer', () => {
    jest.useFakeTimers()
    const { methods } = DeviceStatus
    const ctx = {
      assistantTerminalRefreshTimer: null,
      refreshData: jest.fn(() => Promise.resolve()),
      hasAssistantRefreshAction: methods.hasAssistantRefreshAction,
      collectAssistantRefreshActions: methods.collectAssistantRefreshActions,
      applyAssistantTerminalStateOptimistic: jest.fn(() => false),
      queueAssistantTerminalForceRefresh: methods.queueAssistantTerminalForceRefresh,
      clearAssistantTerminalRefreshTimer: methods.clearAssistantTerminalRefreshTimer
    }

    methods.handleAssistantRefresh.call(ctx, {
      intent: 'disable_terminal',
      action_log: [{ action: 'disable_terminal', details: { remote_state: 0, terminal_ids: ['11'] } }]
    })
    methods.handleAssistantRefresh.call(ctx, {
      intent: 'enable_terminal',
      action_log: [{ action: 'enable_terminal', details: { remote_state: 0, terminal_ids: ['11'] } }]
    })

    jest.runAllTimers()

    expect(ctx.refreshData.mock.calls).toEqual([
      [true],
      [true],
      [true, true]
    ])
  })

  it('beforeDestroy clears the pending terminal force refresh timer', () => {
    jest.useFakeTimers()
    const { methods, beforeDestroy } = DeviceStatus
    const ctx = {
      assistantTerminalRefreshTimer: null,
      refreshData: jest.fn(() => Promise.resolve()),
      handleAssistantRefresh: jest.fn(),
      clearRenderTimer: jest.fn(),
      stopRuntimePlayPolling: jest.fn(),
      clearDragExpandTimer: jest.fn(),
      clearAssistantTerminalRefreshTimer: methods.clearAssistantTerminalRefreshTimer,
      dragGhostEl: null
    }

    methods.queueAssistantTerminalForceRefresh.call(ctx)
    beforeDestroy.call(ctx)
    jest.runAllTimers()

    expect(ctx.assistantTerminalRefreshTimer).toBeNull()
    expect(ctx.refreshData).not.toHaveBeenCalled()
  })
})
