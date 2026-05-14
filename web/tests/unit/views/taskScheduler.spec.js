jest.mock('@/api/dataService', () => ({
  fetchAllAudio: jest.fn(),
  fetchAllLoc: jest.fn(),
  fetchAllTerminalData: jest.fn(),
  fetchAllTask: jest.fn(),
  fetchBroadcasts: jest.fn(),
  fetchLivecasts: jest.fn(),
  fetchBroadcastSchedulesSummary: jest.fn(),
  fetchTaskOverrides: jest.fn(),
  fetchScheduleTasks: jest.fn(),
  setTaskStatus: jest.fn(),
  setScheduleStatus: jest.fn(),
  syncBackendData: jest.fn(),
  createScheduleEntry: jest.fn(),
  updateScheduleEntry: jest.fn(),
  deleteScheduleEntry: jest.fn(),
  updateBroadcastSchedules: jest.fn(),
  updateAllTask: jest.fn(),
  updateOnceOverrideTask: jest.fn(),
  deleteOnceOverrideTask: jest.fn()
}))

jest.mock('@/utils/schedulerStorage', () => ({
  clearBroadcastDraft: jest.fn(() => ({
    plans: [],
    planDirtyIds: [],
    planBaseSnapshot: [],
    broadcasts: [],
    broadcastDirtyIds: [],
    broadcastDeletedIds: [],
    dirtyScopes: [],
    updatedAt: ''
  })),
  clearPlanDraft: jest.fn(() => ({
    plans: [],
    planDirtyIds: [],
    planBaseSnapshot: [],
    broadcasts: [],
    broadcastDirtyIds: [],
    broadcastDeletedIds: [],
    dirtyScopes: [],
    updatedAt: ''
  })),
  getDefaultSchedulerData: jest.fn(() => ({
    plans: [],
    broadcasts: [],
    livecasts: []
  })),
  getDefaultSchedulerDrafts: jest.fn(() => ({
    plans: [],
    planDirtyIds: [],
    planBaseSnapshot: [],
    broadcasts: [],
    broadcastDirtyIds: [],
    broadcastDeletedIds: [],
    dirtyScopes: [],
    updatedAt: ''
  })),
  hasSchedulerDirtyScope: jest.fn((scope, drafts) => Array.isArray(drafts?.dirtyScopes) && drafts.dirtyScopes.includes(scope)),
  loadSchedulerDrafts: jest.fn(() => ({
    plans: [],
    planDirtyIds: [],
    planBaseSnapshot: [],
    broadcasts: [],
    broadcastDirtyIds: [],
    broadcastDeletedIds: [],
    dirtyScopes: [],
    updatedAt: ''
  })),
  saveBroadcastDraft: jest.fn((broadcasts) => ({
    plans: [],
    planDirtyIds: [],
    planBaseSnapshot: [],
    broadcasts: Array.isArray(broadcasts) ? JSON.parse(JSON.stringify(broadcasts)) : [],
    broadcastDirtyIds: Array.isArray(broadcasts)
      ? broadcasts.map((row) => String(row?.id || row?.taskid || '')).filter((item) => item)
      : [],
    broadcastDeletedIds: [],
    dirtyScopes: Array.isArray(broadcasts) && broadcasts.length ? ['broadcasts'] : [],
    updatedAt: '2026-03-20T00:00:00'
  })),
  savePlanDraft: jest.fn(() => ({
    plans: [],
    planDirtyIds: [],
    planBaseSnapshot: [],
    broadcasts: [],
    broadcastDirtyIds: [],
    broadcastDeletedIds: [],
    dirtyScopes: ['plans'],
    updatedAt: '2026-03-20T00:00:00'
  }))
}))

import {
  fetchAllTask,
  fetchBroadcasts,
  updateBroadcastSchedules,
  updateOnceOverrideTask,
  deleteOnceOverrideTask
} from '@/api/dataService'
import TaskSchedulerPage from '@/views/task-scheduler/index.vue'

const flushMicrotasks = async(count = 3) => {
  for (let index = 0; index < count; index += 1) {
    await Promise.resolve()
  }
}

describe('TaskSchedulerPage', () => {
  beforeEach(() => {
    jest.clearAllMocks()
  })

  it('applies the default terminal to fixed plan template tasks', () => {
    const { methods } = TaskSchedulerPage
    const ctx = {
      audioOptions: [{ value: 'audio-1' }],
      locationOptions: [
        {
          value: 'zone-0',
          children: [{ value: 'podium-terminal' }]
        }
      ],
      terminalIdMap: {
        '8': { name: 'podium-terminal' }
      },
      zoneValueMap: {},
      hasReliableLocationOptions: true,
      nextPlanTaskId: () => '9001',
      createDraftTaskId: (seed = '') => `draft-${seed || '0'}`,
      firstLocationPath: methods.firstLocationPath,
      defaultLocation: methods.defaultLocation,
      uniqueStringList: methods.uniqueStringList,
      buildTerminalNameIdMap: methods.buildTerminalNameIdMap,
      normalizeLocationPaths: methods.normalizeLocationPaths,
      extractTerminalIdsFromLocation: methods.extractTerminalIdsFromLocation,
      resolvePlanTaskTerminalFields: methods.resolvePlanTaskTerminalFields,
      newPlanTask: methods.newPlanTask,
      normalizeRealTaskId: methods.normalizeRealTaskId,
      normalizeTempTaskId: (value, idx) => String(value || `900${idx || 0}`),
      normalizeDateRange: (start, end) => [start || '2026-01-14', end || '2039-01-31'],
      normalizeWeekdays: (list) => (Array.isArray(list) ? list : []),
      toTime: (value) => value,
      toDurationSecondsFromApi: (length, type, fallback) => Number(length || fallback || (type === 2 ? 1 : 0)),
      buildPlanTaskFromSchedule: methods.buildPlanTaskFromSchedule,
      buildFixedPlanTasks: methods.buildFixedPlanTasks
    }

    const tasks = methods.buildFixedPlanTasks.call(ctx)

    expect(tasks).toHaveLength(14)
    expect(tasks.every((task) => JSON.stringify(task.weekdays) === JSON.stringify(['周一', '周二', '周三', '周四', '周五']))).toBe(true)
    expect(tasks[0].location).toEqual([['zone-0', 'podium-terminal']])
    expect(tasks[0].terminalids).toEqual(['8'])
    expect(tasks[0].terminalnames).toEqual(['podium-terminal'])
    expect(tasks[0].liveterminalid).toBe('8')
    expect(tasks[0].liveterminalname).toBe('podium-terminal')
  })
  it('expands a zone-only location selection into all terminals under that zone', () => {
    const { methods } = TaskSchedulerPage
    const ctx = {
      zoneValueMap: {},
      locationOptions: [
        {
          value: '教学区',
          label: '教学区',
          children: [
            { value: '终端A', label: '终端A' },
            { value: '终端B', label: '终端B' }
          ]
        }
      ],
      terminalIdMap: {
        '101': { zoneLabel: '教学区', name: '终端A' },
        '102': { zoneLabel: '教学区', name: '终端B' }
      },
      terminalNameZoneMap: {
        '终端A': { zoneId: '1', zoneLabel: '教学区', terminalId: '101', terminalName: '终端A' },
        '终端B': { zoneId: '1', zoneLabel: '教学区', terminalId: '102', terminalName: '终端B' }
      },
      uniqueStringList: methods.uniqueStringList,
      uniqueLocationPaths: methods.uniqueLocationPaths,
      normalizeLocationPaths: methods.normalizeLocationPaths,
      uniqueTerminalZoneCandidates: methods.uniqueTerminalZoneCandidates,
      terminalCandidatesById: methods.terminalCandidatesById,
      terminalCandidatesByName: methods.terminalCandidatesByName,
      matchingTerminalCandidatesForLocationEntry: methods.matchingTerminalCandidatesForLocationEntry,
      locationOptionZoneLabel: methods.locationOptionZoneLabel,
      locationPathsForZoneLabel: methods.locationPathsForZoneLabel,
      normalizeExplicitLocationEntry: methods.normalizeExplicitLocationEntry
    }

    const result = methods.expandLocationSelection.call(ctx, [['教学区']])

    expect(result).toEqual({
      paths: [['教学区', '终端A'], ['教学区', '终端B']],
      emptyZones: []
    })
  })

  it('deduplicates terminals when a zone and one of its children are selected together', () => {
    const { methods } = TaskSchedulerPage
    const ctx = {
      zoneValueMap: {},
      locationOptions: [
        {
          value: '教学区',
          label: '教学区',
          children: [
            { value: '终端A', label: '终端A' },
            { value: '终端B', label: '终端B' }
          ]
        },
        {
          value: '操场区',
          label: '操场区',
          children: [{ value: '终端C', label: '终端C' }]
        }
      ],
      terminalIdMap: {
        '101': { zoneLabel: '教学区', name: '终端A' },
        '102': { zoneLabel: '教学区', name: '终端B' },
        '103': { zoneLabel: '操场区', name: '终端C' }
      },
      terminalNameZoneMap: {
        '终端A': { zoneId: '1', zoneLabel: '教学区', terminalId: '101', terminalName: '终端A' },
        '终端B': { zoneId: '1', zoneLabel: '教学区', terminalId: '102', terminalName: '终端B' },
        '终端C': { zoneId: '2', zoneLabel: '操场区', terminalId: '103', terminalName: '终端C' }
      },
      uniqueStringList: methods.uniqueStringList,
      uniqueLocationPaths: methods.uniqueLocationPaths,
      normalizeLocationPaths: methods.normalizeLocationPaths,
      uniqueTerminalZoneCandidates: methods.uniqueTerminalZoneCandidates,
      terminalCandidatesById: methods.terminalCandidatesById,
      terminalCandidatesByName: methods.terminalCandidatesByName,
      matchingTerminalCandidatesForLocationEntry: methods.matchingTerminalCandidatesForLocationEntry,
      locationOptionZoneLabel: methods.locationOptionZoneLabel,
      locationPathsForZoneLabel: methods.locationPathsForZoneLabel,
      normalizeExplicitLocationEntry: methods.normalizeExplicitLocationEntry
    }

    const result = methods.expandLocationSelection.call(ctx, [['教学区'], ['教学区', '终端A'], ['操场区']])

    expect(result.paths).toEqual([
      ['教学区', '终端A'],
      ['教学区', '终端B'],
      ['操场区', '终端C']
    ])
    expect(result.emptyZones).toEqual([])
  })

  it('reports empty zones instead of persisting a zone-only location without terminals', () => {
    const { methods } = TaskSchedulerPage
    const ctx = {
      zoneValueMap: {},
      locationOptions: [
        { value: '空分区', label: '空分区', children: [] }
      ],
      uniqueStringList: methods.uniqueStringList,
      uniqueLocationPaths: methods.uniqueLocationPaths,
      normalizeLocationPaths: methods.normalizeLocationPaths,
      locationOptionZoneLabel: methods.locationOptionZoneLabel,
      locationPathsForZoneLabel: methods.locationPathsForZoneLabel,
      normalizeExplicitLocationEntry: methods.normalizeExplicitLocationEntry
    }

    const result = methods.expandLocationSelection.call(ctx, [['空分区']])

    expect(result.paths).toEqual([])
    expect(result.emptyZones).toEqual(['空分区'])
    expect(methods.emptyZoneLocationMessage.call({ uniqueStringList: methods.uniqueStringList }, result.emptyZones))
      .toBe('分区“空分区”下暂无可用终端')
  })

  it('normalizes broadcast row location changes into explicit terminals and synced ids', () => {
    const { methods } = TaskSchedulerPage
    const row = {
      location: [],
      terminalids: [],
      terminalnames: [],
      liveterminalid: '',
      liveterminalname: ''
    }
    const ctx = {
      zoneValueMap: {},
      locationOptions: [
        {
          value: '教学区',
          label: '教学区',
          children: [
            { value: '终端A', label: '终端A' },
            { value: '终端B', label: '终端B' }
          ]
        }
      ],
      terminalIdMap: {
        '101': { zoneLabel: '教学区', name: '终端A' },
        '102': { zoneLabel: '教学区', name: '终端B' }
      },
      terminalNameZoneMap: {
        '终端A': { zoneId: '1', zoneLabel: '教学区', terminalId: '101', terminalName: '终端A' },
        '终端B': { zoneId: '1', zoneLabel: '教学区', terminalId: '102', terminalName: '终端B' }
      },
      $message: { warning: jest.fn() },
      uniqueStringList: methods.uniqueStringList,
      uniqueLocationPaths: methods.uniqueLocationPaths,
      normalizeLocationPaths: methods.normalizeLocationPaths,
      uniqueTerminalZoneCandidates: methods.uniqueTerminalZoneCandidates,
      terminalCandidatesById: methods.terminalCandidatesById,
      terminalCandidatesByName: methods.terminalCandidatesByName,
      matchingTerminalCandidatesForLocationEntry: methods.matchingTerminalCandidatesForLocationEntry,
      locationOptionZoneLabel: methods.locationOptionZoneLabel,
      locationPathsForZoneLabel: methods.locationPathsForZoneLabel,
      normalizeExplicitLocationEntry: methods.normalizeExplicitLocationEntry,
      buildTerminalNameIdMap: methods.buildTerminalNameIdMap,
      extractTerminalIdsFromLocation: methods.extractTerminalIdsFromLocation,
      resolvePlanTaskTerminalFields: methods.resolvePlanTaskTerminalFields,
      expandLocationSelection: methods.expandLocationSelection,
      syncTerminalFieldsFromLocation: methods.syncTerminalFieldsFromLocation
    }

    methods.onBroadcastLocationChange.call(ctx, row, [['教学区']])

    expect(row.location).toEqual([['教学区', '终端A'], ['教学区', '终端B']])
    expect(row.terminalids).toEqual(['101', '102'])
    expect(row.terminalnames).toEqual(['终端A', '终端B'])
    expect(row.liveterminalid).toBe('101')
    expect(row.liveterminalname).toBe('终端A')
  })

  it('repairs stored zone-only plan task locations once location options are available', () => {
    const { methods } = TaskSchedulerPage
    const task = {
      location: [['教学区']],
      terminalids: [],
      terminalnames: [],
      liveterminalid: '',
      liveterminalname: ''
    }
    const ctx = {
      zoneValueMap: {},
      locationOptions: [
        {
          value: '教学区',
          label: '教学区',
          children: [
            { value: '终端A', label: '终端A' },
            { value: '终端B', label: '终端B' }
          ]
        }
      ],
      terminalIdMap: {
        '101': { zoneLabel: '教学区', name: '终端A' },
        '102': { zoneLabel: '教学区', name: '终端B' }
      },
      terminalNameZoneMap: {
        '终端A': { zoneId: '1', zoneLabel: '教学区', terminalId: '101', terminalName: '终端A' },
        '终端B': { zoneId: '1', zoneLabel: '教学区', terminalId: '102', terminalName: '终端B' }
      },
      uniqueStringList: methods.uniqueStringList,
      uniqueLocationPaths: methods.uniqueLocationPaths,
      normalizeLocationPaths: methods.normalizeLocationPaths,
      uniqueTerminalZoneCandidates: methods.uniqueTerminalZoneCandidates,
      terminalCandidatesById: methods.terminalCandidatesById,
      terminalCandidatesByName: methods.terminalCandidatesByName,
      matchingTerminalCandidatesForLocationEntry: methods.matchingTerminalCandidatesForLocationEntry,
      locationOptionZoneLabel: methods.locationOptionZoneLabel,
      locationPathsForZoneLabel: methods.locationPathsForZoneLabel,
      normalizeExplicitLocationEntry: methods.normalizeExplicitLocationEntry,
      buildTerminalNameIdMap: methods.buildTerminalNameIdMap,
      extractTerminalIdsFromLocation: methods.extractTerminalIdsFromLocation,
      resolvePlanTaskTerminalFields: methods.resolvePlanTaskTerminalFields,
      expandLocationSelection: methods.expandLocationSelection,
      syncTerminalFieldsFromLocation: methods.syncTerminalFieldsFromLocation
    }

    methods.repairStoredLocationBinding.call(ctx, task)

    expect(task.location).toEqual([['教学区', '终端A'], ['教学区', '终端B']])
    expect(task.terminalids).toEqual(['101', '102'])
  })

  it('preserves explicit broadcast location before terminal map reconstruction', () => {
    const { methods } = TaskSchedulerPage
    const ctx = {
      terminalIdMap: {
        '9': { zoneLabel: 'middle-school', name: 'right-1' }
      },
      terminalNameZoneMap: {
        'right-1': 'middle-school'
      },
      normalizeLocationPaths: methods.normalizeLocationPaths
    }

    const result = methods.resolveLocationFromRow.call(ctx, {
      location: [['zone-a', 'right-1']],
      terminalids: ['9'],
      terminalnames: ['right-1'],
      liveterminalname: 'right-1'
    })

    expect(result).toEqual([['zone-a', 'right-1']])
  })

  it('reconstructs broadcast location from terminal maps when explicit location is missing', () => {
    const { methods } = TaskSchedulerPage
    const ctx = {
      terminalIdMap: {
        '9': { zoneLabel: 'middle-school', name: 'right-1' }
      },
      terminalNameZoneMap: {
        'right-1': 'middle-school'
      },
      normalizeLocationPaths: methods.normalizeLocationPaths
    }

    const result = methods.resolveLocationFromRow.call(ctx, {
      terminalids: ['9'],
      terminalnames: ['right-1'],
      liveterminalname: 'right-1'
    })

    expect(result).toEqual([['middle-school', 'right-1']])
  })

  it('normalizeModules keeps explicit broadcast location when terminal map disagrees', () => {
    const { methods } = TaskSchedulerPage
    const ctx = {
      zoneValueMap: {},
      terminalIdMap: {
        '9': { zoneLabel: 'middle-school', name: 'right-1' }
      },
      terminalNameZoneMap: {
        'right-1': 'middle-school'
      },
      modules: {
        plans: [],
        broadcasts: [
          {
            id: '501',
            name: 'afternoon-bell',
            durationMode: 'loop',
            loop: 1,
            location: [['zone-a', 'right-1']],
            terminalids: ['9'],
            terminalnames: ['right-1'],
            liveterminalname: 'right-1'
          }
        ],
        livecasts: []
      },
      normalizeLocationPaths: methods.normalizeLocationPaths,
      uniqueStringList: methods.uniqueStringList,
      resolveLocationFromRow: methods.resolveLocationFromRow,
      repairStoredLocationBinding: methods.repairStoredLocationBinding,
      syncTerminalFieldsFromLocation: methods.syncTerminalFieldsFromLocation,
      expandLocationSelection: methods.expandLocationSelection,
      uniqueLocationPaths: methods.uniqueLocationPaths,
      locationOptionZoneLabel: methods.locationOptionZoneLabel,
      locationPathsForZoneLabel: methods.locationPathsForZoneLabel,
      normalizeExplicitLocationEntry: methods.normalizeExplicitLocationEntry,
      uniqueTerminalZoneCandidates: methods.uniqueTerminalZoneCandidates,
      terminalCandidatesById: methods.terminalCandidatesById,
      terminalCandidatesByName: methods.terminalCandidatesByName,
      matchingTerminalCandidatesForLocationEntry: methods.matchingTerminalCandidatesForLocationEntry,
      buildTerminalNameIdMap: methods.buildTerminalNameIdMap,
      extractTerminalIdsFromLocation: methods.extractTerminalIdsFromLocation,
      resolvePlanTaskTerminalFields: methods.resolvePlanTaskTerminalFields,
      formatDurationHms: (value) => value,
      normalizeWeekdays: (list) => (Array.isArray(list) ? list : []),
      newPlanTask: () => ({
        weekdays: [],
        location: [],
        powerOn: false,
        taskLevel: 'normal',
        sendMode: 'default',
        playMode: 'loop',
        ledSetting: false
      })
    }

    methods.normalizeModules.call(ctx)

    expect(ctx.modules.broadcasts[0].location).toEqual([['zone-a', 'right-1']])
  })

  it('loadBroadcasts does not persist a broadcast draft during formal data load', async() => {
    const { methods, watch } = TaskSchedulerPage
    const officialRows = [
      {
        id: '501',
        name: 'afternoon-bell'
      }
    ]
    fetchBroadcasts.mockResolvedValue({ broadcasts: officialRows })
    fetchAllTask.mockResolvedValue({ data: [{ taskid: '501', location: [['zone-a', 'right-1']] }] })

    const ctx = {
      broadcastsLoaded: false,
      broadcastsLoading: false,
      hasBroadcastDraft: false,
      draftState: { broadcasts: [], dirtyScopes: [] },
      lastSyncedBroadcasts: [],
      suspendBroadcastDraftSync: false,
      broadcastDraftSyncSuspendDepth: 0,
      modules: { broadcasts: [] },
      cloneRows: methods.cloneRows,
      startBroadcastDraftSyncSuspension: methods.startBroadcastDraftSyncSuspension,
      stopBroadcastDraftSyncSuspension: methods.stopBroadcastDraftSyncSuspension,
      withBroadcastDraftSyncSuspended: methods.withBroadcastDraftSyncSuspended,
      withBroadcastDraftSyncSuspendedAsync: methods.withBroadcastDraftSyncSuspendedAsync,
      setBroadcastRows: methods.setBroadcastRows,
      normalizeModules() {
        Promise.resolve().then(() => watch['modules.broadcasts'].handler.call(ctx))
      },
      applyTerminalInfoFromAllTask: jest.fn((rows) => {
        rows[0].location = [['zone-a', 'right-1']]
        return Promise.resolve().then(() => watch['modules.broadcasts'].handler.call(ctx))
      }),
      persistBroadcastDraftLocally: jest.fn(),
      setTableLoading: jest.fn(),
      setTableLoaded: jest.fn(),
      $message: { error: jest.fn() },
      $nextTick(callback) {
        const tick = Promise.resolve()
        if (typeof callback === 'function') {
          return tick.then(() => callback())
        }
        return tick
      }
    }

    await methods.loadBroadcasts.call(ctx)
    await flushMicrotasks()

    expect(fetchBroadcasts).toHaveBeenCalledTimes(1)
    expect(fetchAllTask).toHaveBeenCalledTimes(1)
    expect(ctx.applyTerminalInfoFromAllTask).toHaveBeenCalledTimes(1)
    expect(ctx.persistBroadcastDraftLocally).not.toHaveBeenCalled()
    expect(ctx.broadcastsLoaded).toBe(true)
    expect(ctx.modules.broadcasts).toEqual([
      {
        id: '501',
        name: 'afternoon-bell',
        location: [['zone-a', 'right-1']]
      }
    ])
    expect(ctx.lastSyncedBroadcasts).toEqual(officialRows)
    expect(ctx.suspendBroadcastDraftSync).toBe(false)
    expect(ctx.broadcastDraftSyncSuspendDepth).toBe(0)
  })

  it('loadBroadcasts keeps a real local broadcast draft without rewriting it during load', async() => {
    const { methods, watch } = TaskSchedulerPage
    const officialRows = [
      {
        id: '501',
        name: 'afternoon-bell',
        location: [['zone-a', 'right-1']],
        terminalids: ['9'],
        terminalnames: ['right-1'],
        liveterminalname: 'right-1'
      }
    ]
    const draftRows = [
      {
        id: '501',
        name: 'draft-bell',
        location: [['zone-a', 'right-1']],
        terminalids: ['9'],
        terminalnames: ['right-1'],
        liveterminalname: 'right-1'
      }
    ]
    fetchBroadcasts.mockResolvedValue({ broadcasts: officialRows })

    const ctx = {
      broadcastsLoaded: false,
      broadcastsLoading: false,
      hasBroadcastDraft: true,
      draftState: { broadcasts: draftRows, dirtyScopes: ['broadcasts'] },
      lastSyncedBroadcasts: [],
      suspendBroadcastDraftSync: false,
      broadcastDraftSyncSuspendDepth: 0,
      modules: { broadcasts: [] },
      cloneRows: methods.cloneRows,
      startBroadcastDraftSyncSuspension: methods.startBroadcastDraftSyncSuspension,
      stopBroadcastDraftSyncSuspension: methods.stopBroadcastDraftSyncSuspension,
      withBroadcastDraftSyncSuspended: methods.withBroadcastDraftSyncSuspended,
      withBroadcastDraftSyncSuspendedAsync: methods.withBroadcastDraftSyncSuspendedAsync,
      setBroadcastRows: methods.setBroadcastRows,
      normalizeModules() {
        Promise.resolve().then(() => watch['modules.broadcasts'].handler.call(ctx))
      },
      applyTerminalInfoFromAllTask: jest.fn(),
      persistBroadcastDraftLocally: jest.fn(),
      setTableLoading: jest.fn(),
      setTableLoaded: jest.fn(),
      $message: { error: jest.fn() },
      $nextTick(callback) {
        const tick = Promise.resolve()
        if (typeof callback === 'function') {
          return tick.then(() => callback())
        }
        return tick
      }
    }

    await methods.loadBroadcasts.call(ctx)
    await flushMicrotasks()

    expect(fetchBroadcasts).toHaveBeenCalledTimes(1)
    expect(fetchAllTask).not.toHaveBeenCalled()
    expect(ctx.persistBroadcastDraftLocally).not.toHaveBeenCalled()
    expect(ctx.broadcastsLoaded).toBe(true)
    expect(ctx.modules.broadcasts).toEqual(draftRows)
    expect(ctx.lastSyncedBroadcasts).toEqual(officialRows)
    expect(ctx.suspendBroadcastDraftSync).toBe(false)
    expect(ctx.broadcastDraftSyncSuspendDepth).toBe(0)
  })

  it('broadcastDraftCount uses unique dirty and deleted broadcast ids', () => {
    const { computed } = TaskSchedulerPage

    const count = computed.broadcastDraftCount.call({
      draftState: {
        broadcastDirtyIds: ['501', '502'],
        broadcastDeletedIds: ['502', '503']
      }
    })

    expect(count).toBe(3)
  })

  it('buildAllTaskRow keeps draft broadcast ids local and uploads taskid as 0', () => {
    const { methods } = TaskSchedulerPage
    const row = {
      id: 'draft-broadcast-1',
      taskid: 'draft-broadcast-1',
      name: 'new-bell',
      audio: 'classic-chime',
      durationMode: 'loop',
      loop: 1,
      location: [['教学区', '终端A']],
      terminalids: ['101'],
      terminalnames: ['终端A'],
      liveterminalid: '101',
      liveterminalname: '终端A'
    }

    const result = methods.buildAllTaskRow.call({
      normalizeRealTaskId: methods.normalizeRealTaskId,
      toTime: (value) => value,
      formatTaskinfoDurationForApi: (value) => String(value || 1),
      resolvePlanTaskTerminalFields: () => ({
        location: [['教学区', '终端A']],
        terminalids: ['101'],
        terminalnames: ['终端A'],
        liveterminalid: '101',
        liveterminalname: '终端A'
      })
    }, row, 2, '2026-03-23')

    expect(result.taskid).toBe('0')
    expect(result.taskname).toBe('new-bell')
    expect(result.medianame).toBe('classic-chime')
    expect(result.terminalids).toEqual(['101'])
    expect(result.location).toEqual([['教学区', '终端A']])
  })
  it('buildPlanOnceTask uses medianame and snapshot fields for once rows', () => {
    const { methods } = TaskSchedulerPage
    const result = methods.buildPlanOnceTask.call({
      newPlanTask: () => ({
        time: '00:00:00',
        duration: '00:00:05',
        volume: 50
      }),
      normalizeDate: (value) => value,
      toTime: (value) => value,
      durationToSeconds: methods.durationToSeconds,
      parseScheduleDurationSeconds: methods.parseScheduleDurationSeconds,
      parseClockDurationSeconds: methods.parseClockDurationSeconds,
      formatDurationHms: methods.formatDurationHms
    }, { id: 'override-1', action: 'migrate' }, {
      taskid: '93001',
      taskname: '早读开始铃',
      startdate: '2026-04-26',
      starttime: '07:50:00',
      duration_seconds: 20,
      medianame: '运动员进行曲.mp3'
    }, '0-0')

    expect(result.customName).toBe('早读开始铃')
    expect(result.audio).toBe('运动员进行曲.mp3')
    expect(result.duration).toBe('00:00:20')
    expect(result.once_task_id).toBe('93001')
  })
  it('buildPlanOnceTask falls back to dash when once media is missing', () => {
    const { methods } = TaskSchedulerPage
    const result = methods.buildPlanOnceTask.call({
      newPlanTask: () => ({
        time: '00:00:00',
        duration: '00:00:05',
        volume: 50
      }),
      normalizeDate: (value) => value,
      toTime: (value) => value,
      durationToSeconds: methods.durationToSeconds,
      parseScheduleDurationSeconds: methods.parseScheduleDurationSeconds,
      parseClockDurationSeconds: methods.parseClockDurationSeconds,
      formatDurationHms: methods.formatDurationHms
    }, { id: 'override-1', action: 'migrate' }, {
      taskid: '93002',
      taskname: '第一节课上课铃',
      startdate: '2026-04-26',
      starttime: '08:20:00',
      duration_seconds: 21
    }, '0-1')

    expect(result.audio).toBe('—')
    expect(result.duration).toBe('00:00:21')
  })
  it('buildPlanOnceTask keeps volume and terminal snapshot fields', () => {
    const { methods } = TaskSchedulerPage
    const result = methods.buildPlanOnceTask.call({
      newPlanTask: () => ({
        time: '00:00:00',
        duration: '00:00:05',
        volume: 50
      }),
      normalizeDate: (value) => value,
      toTime: (value) => value,
      durationToSeconds: methods.durationToSeconds,
      parseScheduleDurationSeconds: methods.parseScheduleDurationSeconds,
      parseClockDurationSeconds: methods.parseClockDurationSeconds,
      formatDurationHms: methods.formatDurationHms
    }, { id: 'override-2', action: 'migrate' }, {
      taskid: '93003',
      taskname: '上午提示',
      startdate: '2026-04-26',
      starttime: '09:10:00',
      duration_seconds: 8,
      medianame: '提示音.mp3',
      volume: 78,
      terminalids: ['50', '52'],
      terminalnames: ['定压备份功放', '操场音箱'],
      liveterminalid: '50',
      liveterminalname: '定压备份功放',
      location: [['无分区终端', '定压备份功放'], ['操场', '操场音箱']]
    }, '0-2')

    expect(result.volume).toBe(78)
    expect(result.terminalids).toEqual(['50', '52'])
    expect(result.terminalnames).toEqual(['定压备份功放', '操场音箱'])
    expect(result.liveterminalid).toBe('50')
    expect(result.liveterminalname).toBe('定压备份功放')
    expect(result.location).toEqual([['无分区终端', '定压备份功放'], ['操场', '操场音箱']])
  })
  it('buildPlanOnceTask does not invent duration or volume defaults for incomplete once specs', () => {
    const { methods } = TaskSchedulerPage
    const result = methods.buildPlanOnceTask.call({
      newPlanTask: () => ({
        time: '00:00:00',
        duration: '00:00:05',
        volume: 50
      }),
      normalizeDate: (value) => value,
      toTime: (value) => value,
      durationToSeconds: methods.durationToSeconds,
      parseScheduleDurationSeconds: methods.parseScheduleDurationSeconds,
      parseClockDurationSeconds: methods.parseClockDurationSeconds,
      formatDurationHms: methods.formatDurationHms
    }, { id: 'override-3', action: 'migrate' }, {
      taskid: '93004',
      taskname: '临时提示',
      startdate: '2026-04-26',
      starttime: '10:00:00'
    }, '0-3')

    expect(result.duration).toBe('')
    expect(result.volume).toBe('')
    expect(result.audio).toBe('—')
  })
  it('buildPlanOnceTask keeps zero volume for once specs', () => {
    const { methods } = TaskSchedulerPage
    const result = methods.buildPlanOnceTask.call({
      newPlanTask: () => ({
        time: '00:00:00',
        duration: '00:00:05',
        volume: 50
      }),
      normalizeDate: (value) => value,
      toTime: (value) => value,
      durationToSeconds: methods.durationToSeconds,
      parseScheduleDurationSeconds: methods.parseScheduleDurationSeconds,
      parseClockDurationSeconds: methods.parseClockDurationSeconds,
      formatDurationHms: methods.formatDurationHms
    }, { id: 'override-4', action: 'migrate' }, {
      taskid: '93005',
      taskname: '静音提示',
      startdate: '2026-04-26',
      starttime: '10:05:00',
      duration_seconds: 5,
      volume: 0
    }, '0-4')

    expect(result.volume).toBe(0)
  })
  it('applyPlanTasksPayload keeps only long-term plan tasks', () => {
    const { methods } = TaskSchedulerPage
    const plan = { name: '夏季作息', tasks: [] }
    const normalizeModules = jest.fn()
    const sortTasksByTime = jest.fn()

    methods.applyPlanTasksPayload.call({
      buildPlanTaskFromSchedule: (task, idx) => ({ id: `task-${idx}`, taskid: task.taskid }),
      normalizeModules,
      sortTasksByTime
    }, plan, [{ taskid: '11' }, { taskid: '12' }])

    expect(plan.tasks).toEqual([{ id: 'task-0', taskid: '11' }, { id: 'task-1', taskid: '12' }])
    expect(plan.taskCount).toBe(2)
    expect(normalizeModules).toHaveBeenCalled()
    expect(sortTasksByTime).toHaveBeenCalledWith(plan.tasks)
  })
  it('counts once changes from overrides instead of plan.tasks', () => {
    const { methods } = TaskSchedulerPage
    const count = methods.planOnceTaskCount.call({
      taskOverrides: [{
        mode: 'once',
        action: 'migrate',
        schedule_name: '夏季作息',
        execution_state: 'scheduled',
        active: true,
        remote_synced: true,
        cleanup_state: 'pending',
        once_task_specs: [{ taskid: '93001' }, { taskid: '93002' }]
      }, {
        mode: 'once',
        action: 'cancel',
        schedule_name: '夏季作息',
        execution_state: 'scheduled',
        active: true,
        remote_synced: true,
        cleanup_state: 'pending',
        time_start: '2026-04-26 18:00:00',
        time_end: '2026-04-26 18:30:00',
        task_ids: ['81291'],
        once_task_specs: []
      }],
      isActiveOnceOverride: methods.isActiveOnceOverride,
      activeOnceOverridesForPlan: methods.activeOnceOverridesForPlan
    }, { name: '夏季作息', tasks: [{ is_once_ephemeral: true }] })

    expect(count).toBe(3)
  })
  it('validates once tasks without requiring weekdays and requires a single execution date', () => {
    const { methods } = TaskSchedulerPage
    const ctx = {
      toTime: (value) => value,
      toDurationSeconds: () => 30,
      normalizeDate: (value) => value,
      expandLocationSelection: () => ({ paths: [['教学区', '终端A']], emptyZones: [] }),
      emptyZoneLocationMessage: methods.emptyZoneLocationMessage
    }

    const valid = methods.validateTaskDrawerDraft.call(ctx, {
      customName: '临时任务',
      audio: '提示铃',
      time: '08:00:00',
      durationMode: 'duration',
      duration: '00:00:30',
      weekdays: [],
      dateRange: ['2026-04-26', '2026-04-26'],
      location: [['教学区', '终端A']]
    }, { isOnceOverride: true })

    expect(valid.errors.weekdays).toBeUndefined()
    expect(valid.errors.dateRange).toBeUndefined()

    const invalid = methods.validateTaskDrawerDraft.call(ctx, {
      customName: '临时任务',
      audio: '提示铃',
      time: '08:00:00',
      durationMode: 'duration',
      duration: '00:00:30',
      weekdays: [],
      dateRange: [],
      location: [['教学区', '终端A']]
    }, { isOnceOverride: true })

    expect(invalid.errors.dateRange).toBe('请选择执行日期')
  })
  it('opens the once drawer from route query only once per query key', () => {
    const { methods } = TaskSchedulerPage
    const openOnceChangesDrawer = jest.fn()
    const ctx = {
      $route: { query: { oncePanel: '1', planName: '夏季作息', date: '2026-04-26' } },
      normalizeDate: (value) => value,
      openOnceChangesDrawer,
      onceRoutePanelKey: ''
    }

    methods.applyOnceDrawerRouteQuery.call(ctx)
    methods.applyOnceDrawerRouteQuery.call(ctx)

    expect(openOnceChangesDrawer).toHaveBeenCalledTimes(1)
    expect(openOnceChangesDrawer).toHaveBeenCalledWith('夏季作息', '2026-04-26')
  })
  it('keeps once edit drawer open when saving fails', async() => {
    const { methods } = TaskSchedulerPage
    updateOnceOverrideTask.mockRejectedValueOnce({ response: { data: { detail: 'remote failed' } } })
    const closeTaskDrawer = jest.fn()
    const loadModules = jest.fn()
    const message = { error: jest.fn(), success: jest.fn(), warning: jest.fn() }

    await methods.saveTaskDrawer.call({
      taskDrawer: {
        plan: { id: 'plan-1', name: '夏季作息' },
        task: null,
        draft: {
          customName: '临时任务',
          audio: '提示铃',
          time: '08:00:00',
          durationMode: 'duration',
          duration: '00:00:30',
          dateRange: ['2026-04-26', '2026-04-26'],
          volume: 60,
          terminalids: ['101'],
          terminalnames: ['终端A'],
          liveterminalid: '101',
          liveterminalname: '终端A',
          location: [['教学区', '终端A']]
        },
        isNew: false,
        isOnceOverride: true,
        overrideId: 'override-1',
        onceTaskId: '93001'
      },
      syncTerminalFieldsFromLocation: jest.fn(),
      validateTaskDrawerDraft: jest.fn(() => ({ errors: {}, firstField: '' })),
      focusTaskDrawerField: jest.fn(),
      isMidnightTime: jest.fn(() => false),
      normalizeDate: (value) => value,
      toTime: (value) => value,
      toDurationSeconds: () => 30,
      loadModules,
      closeTaskDrawer,
      $message: message
    })

    expect(closeTaskDrawer).not.toHaveBeenCalled()
    expect(loadModules).not.toHaveBeenCalled()
    expect(updateOnceOverrideTask).toHaveBeenCalledWith('override-1', '93001', expect.objectContaining({
      taskname: '临时任务',
      medianame: '提示铃',
      startdate: '2026-04-26',
      starttime: '08:00:00',
      timelength: '30',
      timelengthtype: '1'
    }))
    const payload = updateOnceOverrideTask.mock.calls[0][2]
    expect(payload.weekdays).toBeUndefined()
    expect(payload.onceAction).toBeUndefined()
    expect(payload.onceRole).toBeUndefined()
    expect(payload.execmode).toBeUndefined()
    expect(payload.tasktype).toBeUndefined()
    expect(message.error).toHaveBeenCalledWith('remote failed')
  })
  it('reloads server state when pending plan save fails', async() => {
    const { methods } = TaskSchedulerPage
    updateBroadcastSchedules.mockRejectedValueOnce({ response: { data: { detail: 'override cleanup failed' } } })
    const loadModules = jest.fn(() => Promise.resolve())
    const failSaveFeedback = jest.fn()
    const clearPlanDraftState = jest.fn()
    const message = { info: jest.fn(), success: jest.fn(), error: jest.fn(), warning: jest.fn() }

    await methods.persist.call({
      persisting: false,
      hasPlanDraft: true,
      hasBroadcastDraft: false,
      draftState: {
        planDirtyIds: ['plan-1'],
        planDeletedIds: ['plan-2']
      },
      activeTab: 'plans',
      normalizePlanDraftIds: (list) => Array.isArray(list) ? list.map((item) => String(item)) : [],
      setSaveFeedbackStep: jest.fn(),
      ensurePlanTasksLoaded: jest.fn(() => Promise.resolve()),
      sortAllModules: jest.fn(),
      ensurePlanPayloadReady: jest.fn(),
      buildPendingOverwritePayload: jest.fn(() => ({ schedules: [] })),
      clearPlanDraftState,
      schedulePayload: {},
      loadModules,
      finishSaveFeedback: jest.fn(),
      failSaveFeedback,
      $message: message
    }, '已保存上传', 'all', { pendingOnly: true })

    expect(updateBroadcastSchedules).toHaveBeenCalledWith({ schedules: [] })
    expect(loadModules).toHaveBeenCalledWith({ applyDraftOverlay: false })
    expect(failSaveFeedback).toHaveBeenCalled()
    expect(clearPlanDraftState).not.toHaveBeenCalled()
    expect(message.error).toHaveBeenCalled()
  })
  it('treats cancel-only panel items as readonly summaries', () => {
    const { computed, methods } = TaskSchedulerPage
    const groups = computed.onceDrawerGroups.call({
      taskOverrides: [{
        id: 'override-cancel',
        mode: 'once',
        action: 'cancel',
        schedule_name: '夏季作息',
        execution_state: 'scheduled',
        active: true,
        remote_synced: true,
        cleanup_state: 'pending',
        time_start: '2026-04-26 18:00:00',
        time_end: '2026-04-26 18:30:00',
        task_ids: ['81291'],
        once_task_specs: []
      }],
      onceChangesDrawer: { planName: '夏季作息', date: '2026-04-26' },
      isActiveOnceOverride: methods.isActiveOnceOverride,
      activeOnceOverridesForPlan: methods.activeOnceOverridesForPlan
    })

    expect(groups).toHaveLength(1)
    expect(groups[0].actionKey).toBe('cancel')
    expect(groups[0].items[0]).toEqual(expect.objectContaining({
      summaryOnly: true,
      canEdit: false,
      canDelete: false,
      taskIds: ['81291']
    }))
  })
  it('ignores delete requests for readonly cancel-only summary items', async() => {
    const { methods } = TaskSchedulerPage
    const confirmDelete = jest.fn()

    await methods.deleteOncePanelItem.call({
      confirmDelete,
      $message: { success: jest.fn(), error: jest.fn() }
    }, {
      overrideId: 'override-cancel',
      onceTaskId: '',
      canDelete: false,
      summaryOnly: true
    })

    expect(confirmDelete).not.toHaveBeenCalled()
    expect(deleteOnceOverrideTask).not.toHaveBeenCalled()
  })
  it('keeps once drawer state when deleting a once panel item fails', async() => {
    const { methods } = TaskSchedulerPage
    deleteOnceOverrideTask.mockRejectedValueOnce({ response: { data: { detail: 'delete failed' } } })
    const loadModules = jest.fn()
    const closeOnceChangesDrawer = jest.fn()
    const message = { success: jest.fn(), error: jest.fn() }

    await methods.deleteOncePanelItem.call({
      confirmDelete: jest.fn().mockResolvedValue(true),
      loadModules,
      onceDrawerGroups: [{ items: [{ onceTaskId: '93001' }] }],
      closeOnceChangesDrawer,
      $message: message
    }, {
      overrideId: 'override-1',
      onceTaskId: '93001',
      canDelete: true,
      taskLabel: '临时任务'
    })

    expect(loadModules).not.toHaveBeenCalled()
    expect(closeOnceChangesDrawer).not.toHaveBeenCalled()
    expect(message.error).toHaveBeenCalledWith('delete failed')
  })
  it('refreshes once data after deleting a once panel item', async() => {
    const { methods } = TaskSchedulerPage
    deleteOnceOverrideTask.mockResolvedValueOnce({ status: 'ok' })
    const loadModules = jest.fn()
    const closeOnceChangesDrawer = jest.fn()
    const message = { success: jest.fn(), error: jest.fn() }

    await methods.deleteOncePanelItem.call({
      confirmDelete: jest.fn().mockResolvedValue(true),
      loadModules,
      onceDrawerGroups: [{ items: [] }],
      closeOnceChangesDrawer,
      $message: message
    }, {
      overrideId: 'override-1',
      onceTaskId: '93001',
      canDelete: true,
      taskLabel: '临时任务'
    })

    expect(deleteOnceOverrideTask).toHaveBeenCalledWith('override-1', '93001')
    expect(loadModules).toHaveBeenCalled()
    expect(message.success).toHaveBeenCalledWith('临时任务已删除')
  })
  it('does not overwrite an existing local broadcast draft before broadcasts finish loading', () => {
    const { watch } = TaskSchedulerPage
    const ctx = {
      broadcastsLoaded: false,
      suspendBroadcastDraftSync: false,
      hasBroadcastDraft: true,
      persistBroadcastDraftLocally: jest.fn()
    }

    watch['modules.broadcasts'].handler.call(ctx)

    expect(ctx.persistBroadcastDraftLocally).not.toHaveBeenCalled()
  })
})
