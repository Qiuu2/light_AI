jest.mock('@/api/dataService', () => ({
  fetchAllAudio: jest.fn(),
  fetchAllLoc: jest.fn(),
  fetchAllTerminalData: jest.fn(),
  fetchAllTask: jest.fn(),
  fetchBroadcasts: jest.fn(),
  fetchLivecasts: jest.fn(),
  fetchRuntimePlayTasks: jest.fn(),
  stopRuntimePlayTasks: jest.fn(),
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
    livecasts: [],
    runtimePlays: []
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
  hasSchedulerDirtyScope: jest.fn(() => false),
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
  saveBroadcastDraft: jest.fn(() => ({
    plans: [],
    planDirtyIds: [],
    planBaseSnapshot: [],
    broadcasts: [],
    broadcastDirtyIds: [],
    broadcastDeletedIds: [],
    dirtyScopes: [],
    updatedAt: ''
  })),
  savePlanDraft: jest.fn(() => ({
    plans: [],
    planDirtyIds: [],
    planBaseSnapshot: [],
    broadcasts: [],
    broadcastDirtyIds: [],
    broadcastDeletedIds: [],
    dirtyScopes: [],
    updatedAt: ''
  }))
}))

jest.mock('@/utils/assistantRefreshBus', () => ({
  emitAssistantRefresh: jest.fn(),
  onAssistantRefresh: jest.fn(),
  offAssistantRefresh: jest.fn()
}))

import { fetchRuntimePlayTasks, stopRuntimePlayTasks } from '@/api/dataService'
import { emitAssistantRefresh } from '@/utils/assistantRefreshBus'
import TaskSchedulerPage from '@/views/task-scheduler/index.vue'

const flushMicrotasks = async(count = 3) => {
  for (let index = 0; index < count; index += 1) {
    await Promise.resolve()
  }
}

describe('TaskSchedulerPage runtime plays', () => {
  beforeEach(() => {
    jest.clearAllMocks()
  })

  it('loadRuntimePlays loads runtime play rows and marks the tab as loaded', async() => {
    const { methods } = TaskSchedulerPage
    fetchRuntimePlayTasks.mockResolvedValue({
      runtime_play_tasks: [
        {
          task_id: '998',
          media_name: '课间铃',
          terminal_names: ['终端101'],
          playtype: 1,
          playlength: 300,
          volume: 80,
          status: '执行中'
        }
      ]
    })

    const ctx = {
      runtimePlaysLoaded: false,
      runtimePlaysLoading: false,
      activeTab: 'runtimePlays',
      modules: { runtimePlays: [] },
      syncRuntimePlayPolling: jest.fn(),
      setTableLoading: jest.fn(),
      setTableLoaded: jest.fn(),
      $message: { error: jest.fn() }
    }

    await methods.loadRuntimePlays.call(ctx, { force: true })

    expect(fetchRuntimePlayTasks).toHaveBeenCalledWith(true)
    expect(ctx.modules.runtimePlays).toEqual([
      expect.objectContaining({
        task_id: '998',
        media_name: '课间铃'
      })
    ])
    expect(ctx.runtimePlaysLoaded).toBe(true)
    expect(ctx.setTableLoaded).toHaveBeenCalledWith('runtimePlays', true)
    expect(ctx.syncRuntimePlayPolling).toHaveBeenCalledWith(ctx.modules.runtimePlays)
  })

  it('handleAssistantRefresh refreshes runtime plays even when another tab is active', async() => {
    const { methods } = TaskSchedulerPage
    const ctx = {
      activeTab: 'plans',
      loadModules: jest.fn(() => Promise.resolve()),
      applyAssistantRuntimePlayPreview: jest.fn(),
      loadRuntimePlays: jest.fn(() => Promise.resolve()),
      loadBroadcasts: jest.fn(),
      loadLivecasts: jest.fn()
    }

    methods.handleAssistantRefresh.call(ctx, {
      runtime_scope: 'temp_task',
      action_log: [{ action: 'play_media', details: { runtime_scope: 'temp_task' }}]
    })
    await flushMicrotasks()

    expect(ctx.loadModules).toHaveBeenCalledTimes(1)
    expect(ctx.applyAssistantRuntimePlayPreview).toHaveBeenCalledTimes(1)
    expect(ctx.loadRuntimePlays).toHaveBeenCalledWith({ force: true })
    expect(ctx.loadBroadcasts).not.toHaveBeenCalled()
    expect(ctx.loadLivecasts).not.toHaveBeenCalled()
  })

  it('applyAssistantRuntimePlayPreview marks optimistic rows as active remote_state=0', () => {
    const { methods } = TaskSchedulerPage
    const ctx = {
      modules: { runtimePlays: [] },
      runtimePlaysLoaded: false,
      cloneRows: (rows) => JSON.parse(JSON.stringify(rows || [])),
      setTableLoaded: jest.fn(),
      syncRuntimePlayPolling: jest.fn()
    }

    methods.applyAssistantRuntimePlayPreview.call(ctx, {
      action_log: [{
        action: 'play_media',
        task_ids: ['998'],
        details: {
          task_id: '998',
          media_name: '课间铃',
          media_id: '11',
          terminal_ids: ['101'],
          terminal_names: ['终端101'],
          playtype: 1,
          playlength: 30,
          volume: 40,
          created_at: '2026-04-02 10:00:00'
        }
      }]
    })

    expect(ctx.modules.runtimePlays[0]).toEqual(expect.objectContaining({
      task_id: '998',
      remote_state: 0,
      status: '执行中'
    }))
    expect(ctx.syncRuntimePlayPolling).toHaveBeenCalledWith(ctx.modules.runtimePlays)
  })

  it('stopRuntimePlay stops the task and emits a runtime refresh event', async() => {
    const { methods } = TaskSchedulerPage
    stopRuntimePlayTasks.mockResolvedValue({
      runtime_play_tasks: [
        {
          task_id: '998',
          status: '停止',
          remote_state: -1
        }
      ]
    })
    const row = {
      task_id: '998',
      status: '执行中',
      remote_state: 0
    }
    const ctx = {
      modules: { runtimePlays: [] },
      runtimePlaysLoaded: false,
      syncRuntimePlayPolling: jest.fn(),
      setTableLoaded: jest.fn(),
      loadRuntimePlays: jest.fn(() => Promise.resolve()),
      $message: {
        warning: jest.fn(),
        success: jest.fn(),
        error: jest.fn()
      }
    }

    await methods.stopRuntimePlay.call(ctx, row)

    expect(stopRuntimePlayTasks).toHaveBeenCalledWith(['998'])
    expect(row.status).toBe('停止')
    expect(row.remote_state).toBe(-1)
    expect(ctx.modules.runtimePlays).toEqual([
      expect.objectContaining({ task_id: '998', status: '停止', remote_state: -1 })
    ])
    expect(ctx.setTableLoaded).toHaveBeenCalledWith('runtimePlays', true)
    expect(ctx.syncRuntimePlayPolling).toHaveBeenCalledWith(ctx.modules.runtimePlays)
    expect(emitAssistantRefresh).toHaveBeenCalledWith(expect.objectContaining({
      runtime_scope: 'temp_task'
    }))
    expect(ctx.$message.success).toHaveBeenCalled()
  })

  it('syncRuntimePlayPolling only keeps polling when runtime tab has active tasks', () => {
    const { methods } = TaskSchedulerPage
    const ctx = {
      activeTab: 'runtimePlays',
      modules: {
        runtimePlays: [
          { task_id: '1', remote_state: 0, status: '执行中' }
        ]
      },
      runtimePlayRemoteState: methods.runtimePlayRemoteState,
      hasActiveRuntimePlays: methods.hasActiveRuntimePlays,
      startRuntimePlayPolling: jest.fn(),
      stopRuntimePlayPolling: jest.fn()
    }

    methods.syncRuntimePlayPolling.call(ctx, ctx.modules.runtimePlays)
    expect(ctx.startRuntimePlayPolling).toHaveBeenCalledTimes(1)
    expect(ctx.stopRuntimePlayPolling).not.toHaveBeenCalled()

    ctx.activeTab = 'plans'
    methods.syncRuntimePlayPolling.call(ctx, ctx.modules.runtimePlays)
    expect(ctx.stopRuntimePlayPolling).toHaveBeenCalledTimes(1)
  })

  it('status text without remote_state does not count as an active runtime play', () => {
    const { methods } = TaskSchedulerPage
    const ctx = {
      activeTab: 'runtimePlays',
      modules: {
        runtimePlays: [
          { task_id: '1', status: '执行中' }
        ]
      },
      runtimePlayRemoteState: methods.runtimePlayRemoteState,
      hasActiveRuntimePlays: methods.hasActiveRuntimePlays,
      startRuntimePlayPolling: jest.fn(),
      stopRuntimePlayPolling: jest.fn()
    }

    expect(methods.runtimePlayRemoteState.call(ctx, { task_id: '1', status: '执行中' })).toBeNull()
    methods.syncRuntimePlayPolling.call(ctx, ctx.modules.runtimePlays)
    expect(ctx.startRuntimePlayPolling).not.toHaveBeenCalled()
    expect(ctx.stopRuntimePlayPolling).toHaveBeenCalledTimes(1)
  })

  it('blank remote_state does not count as an active runtime play', () => {
    const { methods } = TaskSchedulerPage
    const ctx = {
      activeTab: 'runtimePlays',
      modules: {
        runtimePlays: [
          { task_id: '1', remote_state: '', status: '待确认' }
        ]
      },
      runtimePlayRemoteState: methods.runtimePlayRemoteState,
      hasActiveRuntimePlays: methods.hasActiveRuntimePlays,
      startRuntimePlayPolling: jest.fn(),
      stopRuntimePlayPolling: jest.fn()
    }

    expect(methods.runtimePlayRemoteState.call(ctx, { task_id: '1', remote_state: '', status: '待确认' })).toBeNull()
    methods.syncRuntimePlayPolling.call(ctx, ctx.modules.runtimePlays)
    expect(ctx.startRuntimePlayPolling).not.toHaveBeenCalled()
    expect(ctx.stopRuntimePlayPolling).toHaveBeenCalledTimes(1)
  })
})
