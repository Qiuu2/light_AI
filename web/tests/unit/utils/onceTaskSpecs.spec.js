import {
  ONCE_PLACEHOLDER,
  buildOnceDisplaySnapshot,
  countOnceSpecs,
  groupOncePanelItems,
  normalizeOnceTaskSpec,
  summarizeOnceSpecs
} from '@/utils/onceTaskSpecs'

describe('onceTaskSpecs', () => {
  it('normalizes once task specs without changing persisted shape assumptions', () => {
    const once = normalizeOnceTaskSpec({
      taskid: '93001',
      taskname: '早读开始铃',
      medianame: '运动员进行曲.mp3',
      startdate: '2026-04-26',
      starttime: '07:50:00',
      duration_seconds: 20,
      volume: 80,
      terminalids: ['50', '50', '52'],
      terminalnames: ['定压备份功放', '定压备份功放', '操场音箱'],
      liveterminalid: '50',
      liveterminalname: '定压备份功放',
      location: [['无分区终端', '定压备份功放'], ['操场', '操场音箱']],
      once_action: 'migrate'
    }, {
      action: 'migrate',
      schedule_name: '夏季作息'
    })

    expect(once.taskId).toBe('93001')
    expect(once.label).toBe('早读开始铃')
    expect(once.mediaName).toBe('运动员进行曲.mp3')
    expect(once.durationSeconds).toBe(20)
    expect(once.terminalids).toEqual(['50', '52'])
    expect(once.scheduleName).toBe('夏季作息')
  })

  it('builds a shared display snapshot with explicit placeholder state', () => {
    const snapshot = buildOnceDisplaySnapshot({
      taskid: '93002',
      taskname: '静音提示',
      startdate: '2026-04-26',
      starttime: '10:00:00',
      volume: 0
    }, {
      action: 'migrate',
      schedule_name: '夏季作息'
    })

    expect(snapshot.taskId).toBe('93002')
    expect(snapshot.mediaDisplay).toBe(ONCE_PLACEHOLDER)
    expect(snapshot.hasMediaName).toBe(false)
    expect(snapshot.durationSeconds).toBeNull()
    expect(snapshot.hasDurationSeconds).toBe(false)
    expect(snapshot.volume).toBe(0)
    expect(snapshot.hasVolume).toBe(true)
    expect(snapshot.placeholder).toBe(ONCE_PLACEHOLDER)
  })

  it('counts and summarizes active once specs with filters', () => {
    const overrides = [{
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
        once_action: 'migrate'
      }, {
        taskid: '93002',
        taskname: '课间提示',
        startdate: '2026-04-27',
        starttime: '10:00:00',
        once_action: 'migrate'
      }]
    }, {
      id: 'override-2',
      mode: 'once',
      action: 'swap',
      schedule_name: '春季作息',
      execution_state: 'scheduled',
      active: true,
      remote_synced: true,
      cleanup_state: 'pending',
      once_task_specs: [{
        taskid: '93011',
        taskname: '下午第一节课上课',
        startdate: '2026-04-26',
        starttime: '14:25:00',
        role: 'source_to_target',
        once_action: 'swap'
      }]
    }, {
      id: 'override-3',
      mode: 'once',
      action: 'cancel',
      schedule_name: '夏季作息',
      execution_state: 'scheduled',
      active: true,
      remote_synced: true,
      cleanup_state: 'cleaned',
      once_task_specs: [{
        taskid: '93099',
        taskname: '已清理',
        startdate: '2026-04-26',
        starttime: '18:00:00',
        once_action: 'cancel'
      }]
    }, {
      id: 'override-4',
      mode: 'once',
      action: 'cancel',
      schedule_name: '夏季作息',
      execution_state: 'scheduled',
      active: true,
      remote_synced: true,
      cleanup_state: 'pending',
      time_start: '2026-04-26 18:00:00',
      time_end: '2026-04-26 18:30:00',
      task_ids: ['81291', '81292'],
      once_task_specs: []
    }]

    expect(countOnceSpecs(overrides)).toBe(4)
    expect(countOnceSpecs(overrides, { planName: '夏季作息' })).toBe(3)
    expect(countOnceSpecs(overrides, { date: '2026-04-26', action: 'migrate' })).toBe(1)
    expect(countOnceSpecs(overrides, { date: '2026-04-26', action: 'cancel' })).toBe(1)

    const summary = summarizeOnceSpecs(overrides, { date: '2026-04-26' })
    expect(summary.count).toBe(3)
    expect(summary.dates).toEqual(['2026-04-26'])
    expect(summary.actionCounts.migrate).toBe(1)
    expect(summary.actionCounts.swap).toBe(1)
    expect(summary.actionCounts.cancel).toBe(1)
  })

  it('groups once panel items by date and action after filtering', () => {
    const groups = groupOncePanelItems([{
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
        once_action: 'migrate'
      }, {
        taskid: '93002',
        taskname: '课间提示',
        startdate: '2026-04-26',
        starttime: '10:00:00',
        once_action: 'migrate'
      }, {
        taskid: '93003',
        taskname: '下午第一节课上课',
        startdate: '2026-04-27',
        starttime: '14:25:00',
        once_action: 'swap'
      }]
    }, {
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
    }], { planName: '夏季作息', date: '2026-04-26' })

    expect(groups).toHaveLength(2)
    expect(groups[0].dateKey).toBe('2026-04-26')
    expect(groups[0].actionKey).toBe('migrate')
    expect(groups[0].items).toHaveLength(2)
    expect(groups[1].actionKey).toBe('cancel')
    expect(groups[1].items[0].summaryOnly).toBe(true)
    expect(groups[1].items[0].canEdit).toBe(false)
    expect(groups[1].items[0].taskIds).toEqual(['81291'])
  })

  it('keeps only the latest duplicate once override in summaries and groups', () => {
    const duplicateOverrides = [{
      id: 'override-old',
      mode: 'once',
      action: 'migrate',
      schedule_name: '夏季作息',
      execution_state: 'scheduled',
      active: true,
      remote_synced: true,
      cleanup_state: 'pending',
      created_at: '2026-04-20 08:00:00',
      time_start: '2026-04-26 07:50:00',
      new_time_start: '2026-04-26 08:10:00',
      task_ids: ['81291'],
      once_task_specs: [{
        taskid: '93001',
        taskname: '旧临时铃声',
        startdate: '2026-04-26',
        starttime: '08:10:00',
        once_action: 'migrate'
      }]
    }, {
      id: 'override-new',
      mode: 'once',
      action: 'migrate',
      schedule_name: '夏季作息',
      execution_state: 'scheduled',
      active: true,
      remote_synced: true,
      cleanup_state: 'pending',
      created_at: '2026-04-20 09:00:00',
      time_start: '2026-04-26 07:50:00',
      new_time_start: '2026-04-26 08:10:00',
      task_ids: ['81291'],
      once_task_specs: [{
        taskid: '93002',
        taskname: '新临时铃声',
        startdate: '2026-04-26',
        starttime: '08:10:00',
        once_action: 'migrate'
      }]
    }]

    expect(countOnceSpecs(duplicateOverrides)).toBe(1)
    expect(summarizeOnceSpecs(duplicateOverrides).count).toBe(1)
    const groups = groupOncePanelItems(duplicateOverrides)
    expect(groups).toHaveLength(1)
    expect(groups[0].items).toHaveLength(1)
    expect(groups[0].items[0].overrideId).toBe('override-new')
    expect(groups[0].items[0].taskLabel).toBe('新临时铃声')
  })
})
