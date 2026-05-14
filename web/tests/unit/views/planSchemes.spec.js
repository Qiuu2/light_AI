jest.mock('@/api/dataService', () => ({
  fetchBroadcastSchedules: jest.fn(),
  fetchTaskOverrides: jest.fn()
}))

jest.mock('@/utils/assistantRefreshBus', () => ({
  onAssistantRefresh: jest.fn(),
  offAssistantRefresh: jest.fn()
}))

jest.mock('@/utils/schedulerStorage', () => ({
  clearPlanDraft: jest.fn(() => ({
    plans: [],
    planDirtyIds: [],
    planBaseSnapshot: [],
    dirtyScopes: [],
    updatedAt: ''
  })),
  discardInvalidPlanDrafts: jest.fn(() => ({
    plans: [],
    planDirtyIds: [],
    planBaseSnapshot: [],
    dirtyScopes: [],
    updatedAt: ''
  })),
  hasSchedulerDirtyScope: jest.fn(() => false),
  loadSchedulerDrafts: jest.fn(() => ({
    plans: [],
    planDirtyIds: [],
    planBaseSnapshot: [],
    dirtyScopes: [],
    updatedAt: ''
  })),
  recoverInvalidPlanDrafts: jest.fn(() => ({
    plans: [],
    planDirtyIds: [],
    planBaseSnapshot: [],
    dirtyScopes: [],
    updatedAt: ''
  }))
}))

import PlanSchemesPage from '@/views/plan-schemes/index.vue'

const activeOnceOverride = {
  id: 'override-1',
  mode: 'once',
  action: 'migrate',
  schedule_name: '夏季作息',
  execution_state: 'scheduled',
  active: true,
  remote_synced: true,
  cleanup_state: 'pending',
  once_task_specs: [{
    taskid: '93001',
    taskname: '早读开始铃',
    startdate: '2026-04-26',
    starttime: '07:50:00',
    duration_seconds: 20,
    medianame: '运动员进行曲.mp3',
    once_action: 'migrate'
  }]
}

describe('PlanSchemesPage', () => {
  it('maps only long-term tasks into expanded plan rows', () => {
    const { methods } = PlanSchemesPage
    const plans = methods.mapPlans.call({
      mapTask: (task, idx) => ({ id: `task-${idx}`, customName: task.taskname }),
      taskOverrides: [activeOnceOverride]
    }, {
      schedules: [{
        schedule_name: '夏季作息',
        status: '启用',
        tasks: [{ taskname: '长期铃声' }]
      }]
    })

    expect(plans).toHaveLength(1)
    expect(plans[0].tasks).toEqual([{ id: 'task-0', customName: '长期铃声' }])
  })

  it('keeps task count limited to long-term tasks', () => {
    const { methods } = PlanSchemesPage
    const label = methods.planTaskCountLabel.call({
      planBaseTaskCount: methods.planBaseTaskCount
    }, {
      tasks: [{ id: 'task-1' }, { id: 'task-2' }]
    })

    expect(label).toBe('2')
  })

  it('summarizes once overrides without flattening them into plan tasks', () => {
    const { methods } = PlanSchemesPage
    const summary = methods.planOnceSummary.call({
      taskOverrides: [
        activeOnceOverride,
        {
          id: 'override-2',
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
        }
      ]
    }, {
      name: '夏季作息',
      tasks: [{ id: 'task-1' }]
    })

    expect(summary.count).toBe(2)
    expect(summary.dates).toEqual(['2026-04-26'])
    expect(summary.actionCounts.migrate).toBe(1)
    expect(summary.actionCounts.cancel).toBe(1)
  })

  it('opens task-scheduler once panel for the selected plan', () => {
    const { methods } = PlanSchemesPage
    const push = jest.fn()

    methods.openPlanOncePanel.call({
      $router: { push }
    }, {
      name: '夏季作息'
    })

    expect(push).toHaveBeenCalledWith({
      name: 'TaskScheduler',
      query: { oncePanel: '1', planName: '夏季作息' }
    })
  })
})
