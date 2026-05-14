jest.mock('@/api/dataService', () => ({
  fetchAllAudio: jest.fn(),
  fetchAllLoc: jest.fn(),
  fetchAllTerminalData: jest.fn(),
  fetchAllTask: jest.fn(),
  fetchBroadcasts: jest.fn(),
  fetchLivecasts: jest.fn(),
  fetchBroadcastSchedulesSummary: jest.fn(),
  fetchScheduleTasks: jest.fn(),
  setTaskStatus: jest.fn(),
  setScheduleStatus: jest.fn(),
  syncBackendData: jest.fn(),
  createScheduleEntry: jest.fn(),
  updateScheduleEntry: jest.fn(),
  deleteScheduleEntry: jest.fn(),
  updateBroadcastSchedules: jest.fn(),
  updateAllTask: jest.fn()
}))

jest.mock('@/utils/schedulerStorage', () => ({
  clearBroadcastDraft: jest.fn(() => ({ plans: [], planDirtyIds: [], planBaseSnapshot: [], broadcasts: [], broadcastDirtyIds: [], broadcastDeletedIds: [], dirtyScopes: [], updatedAt: '' })),
  clearPlanDraft: jest.fn(() => ({ plans: [], planDirtyIds: [], planBaseSnapshot: [], broadcasts: [], broadcastDirtyIds: [], broadcastDeletedIds: [], dirtyScopes: [], updatedAt: '' })),
  getDefaultSchedulerData: jest.fn(() => ({ plans: [], broadcasts: [], livecasts: [] })),
  getDefaultSchedulerDrafts: jest.fn(() => ({ plans: [], planDirtyIds: [], planBaseSnapshot: [], broadcasts: [], broadcastDirtyIds: [], broadcastDeletedIds: [], dirtyScopes: [], updatedAt: '' })),
  hasSchedulerDirtyScope: jest.fn(() => false),
  loadSchedulerDrafts: jest.fn(() => ({ plans: [], planDirtyIds: [], planBaseSnapshot: [], broadcasts: [], broadcastDirtyIds: [], broadcastDeletedIds: [], dirtyScopes: [], updatedAt: '' })),
  saveBroadcastDraft: jest.fn(() => ({ plans: [], planDirtyIds: [], planBaseSnapshot: [], broadcasts: [], broadcastDirtyIds: [], broadcastDeletedIds: [], dirtyScopes: [], updatedAt: '' })),
  savePlanDraft: jest.fn(() => ({ plans: [], planDirtyIds: [], planBaseSnapshot: [], broadcasts: [], broadcastDirtyIds: [], broadcastDeletedIds: [], dirtyScopes: [], updatedAt: '' }))
}))

import TaskSchedulerPage from '@/views/task-scheduler/index.vue'

describe('TaskSchedulerPage zone ambiguity', () => {
  it('buildTerminalMaps keeps multiple zone candidates for the same terminal', () => {
    const { methods } = TaskSchedulerPage
    const result = methods.buildTerminalMaps.call(
      {
        zoneValueLabel: methods.zoneValueLabel,
        zoneNameFromItem: methods.zoneNameFromItem
      },
      [{ id: 1, name: 'A区' }, { id: 19, name: '初中部' }],
      {
        '1': [{ id: 9, name: '右一终端' }],
        '19': [{ id: 9, name: '右一终端' }]
      },
      []
    )

    expect(result.terminalIdMap['9']).toEqual([
      { zoneId: '1', zoneLabel: 'A区', terminalId: '9', terminalName: '右一终端' },
      { zoneId: '19', zoneLabel: '初中部', terminalId: '9', terminalName: '右一终端' }
    ])
  })

  it('resolveLocationFromRow refuses to auto-fill an ambiguous terminal', () => {
    const { methods } = TaskSchedulerPage
    const ctx = {
      terminalIdMap: {
        '9': [
          { zoneId: '1', zoneLabel: 'A区', terminalId: '9', terminalName: '右一终端' },
          { zoneId: '19', zoneLabel: '初中部', terminalId: '9', terminalName: '右一终端' }
        ]
      },
      terminalNameZoneMap: {
        '右一终端': [
          { zoneId: '1', zoneLabel: 'A区', terminalId: '9', terminalName: '右一终端' },
          { zoneId: '19', zoneLabel: '初中部', terminalId: '9', terminalName: '右一终端' }
        ]
      },
      uniqueTerminalZoneCandidates: methods.uniqueTerminalZoneCandidates,
      terminalCandidatesById: methods.terminalCandidatesById,
      terminalCandidatesByName: methods.terminalCandidatesByName,
      singleLocationPathFromCandidates: methods.singleLocationPathFromCandidates,
      normalizeLocationPaths: methods.normalizeLocationPaths
    }

    expect(methods.resolveLocationFromRow.call(ctx, {
      terminalids: ['9'],
      terminalnames: ['右一终端'],
      liveterminalname: '右一终端'
    })).toEqual([])
  })

  it('extractTerminalIdsFromLocation uses the explicit zone to resolve an ambiguous terminal', () => {
    const { methods } = TaskSchedulerPage
    const ctx = {
      zoneValueMap: {},
      terminalIdMap: {
        '9': [
          { zoneId: '1', zoneLabel: 'A区', terminalId: '9', terminalName: '右一终端' },
          { zoneId: '19', zoneLabel: '初中部', terminalId: '9', terminalName: '右一终端' }
        ]
      },
      terminalNameZoneMap: {
        '右一终端': [
          { zoneId: '1', zoneLabel: 'A区', terminalId: '9', terminalName: '右一终端' },
          { zoneId: '19', zoneLabel: '初中部', terminalId: '9', terminalName: '右一终端' }
        ]
      },
      uniqueStringList: methods.uniqueStringList,
      uniqueTerminalZoneCandidates: methods.uniqueTerminalZoneCandidates,
      terminalCandidatesById: methods.terminalCandidatesById,
      terminalCandidatesByName: methods.terminalCandidatesByName,
      matchingTerminalCandidatesForLocationEntry: methods.matchingTerminalCandidatesForLocationEntry,
      buildTerminalNameIdMap: methods.buildTerminalNameIdMap,
      normalizeLocationPaths: methods.normalizeLocationPaths
    }

    expect(methods.extractTerminalIdsFromLocation.call(ctx, [['A区', '右一终端']])).toEqual(['9'])
  })
})
