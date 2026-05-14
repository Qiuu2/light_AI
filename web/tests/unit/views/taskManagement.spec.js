jest.mock('@/api/dataService', () => ({
  fetchBroadcastSchedules: jest.fn(),
  fetchCalendarHolidays: jest.fn(),
  fetchTaskOverrides: jest.fn(),
  updateScheduleEntry: jest.fn()
}))

import TaskManagementPage from '@/views/task-management/index.vue'

describe('TaskManagementPage', () => {
  it('computes holiday badges for holiday, makeup workday, and normal days', () => {
    const { computed } = TaskManagementPage

    const holiday = computed.selectedHoliday.call({
      currentDateKey: '2026-02-15',
      getHolidayByDateKey: () => ({ name: '春节', type: 'holiday', isWorkday: false }),
      isWeekendDateKey: () => false
    })
    expect(holiday).toEqual({ name: '春节', type: 'holiday', isWorkday: false })
    expect(computed.selectedHolidayBadge.call({ selectedHoliday: holiday })).toBe('放假')

    const workday = computed.selectedHoliday.call({
      currentDateKey: '2026-02-28',
      getHolidayByDateKey: () => ({ name: '春节调休', type: 'makeup_workday', isWorkday: true }),
      isWeekendDateKey: () => false
    })
    expect(workday).toEqual({ name: '春节调休', type: 'makeup_workday', isWorkday: true })
    expect(computed.selectedHolidayBadge.call({ selectedHoliday: workday })).toBe('调休上班')

    const normalDay = computed.selectedHoliday.call({
      currentDateKey: '2026-03-01',
      getHolidayByDateKey: () => null,
      isWeekendDateKey: () => false
    })
    expect(normalDay).toBeNull()
  })

  it('marks holiday and makeup workday cells in the picker grid', () => {
    const { methods } = TaskManagementPage

    const holidayClass = methods.holidayDateCellClassName.call(
      {
        getCalendarCellMeta: () => ({ title: '清明节', className: 'tm-holiday-cell' })
      },
      '2026-04-04'
    )
    expect(holidayClass).toBe('tm-holiday-cell')

    const workdayClass = methods.holidayDateCellClassName.call(
      {
        getCalendarCellMeta: () => ({ title: '调休', className: 'tm-workday-cell' })
      },
      '2026-04-06'
    )
    expect(workdayClass).toBe('tm-workday-cell')

    const normalClass = methods.holidayDateCellClassName.call(
      {
        getCalendarCellMeta: () => null
      },
      '2026-04-07'
    )
    expect(normalClass).toBe('')
  })

  it('shows the current-time marker only when the selected day is today', () => {
    const { computed } = TaskManagementPage

    const marker = computed.currentTimeMarker.call({
      isTodaySelected: true,
      nowTick: Date.parse('2026-03-21T04:30:15Z')
    })
    expect(marker.label).toBe('12:30')
    expect(parseFloat(marker.left)).toBeCloseTo((45015 / 86400) * 100, 4)

    const hidden = computed.currentTimeMarker.call({
      isTodaySelected: false,
      nowTick: Date.parse('2026-03-21T04:30:15Z')
    })
    expect(hidden).toBeNull()
  })

  it('computes timeline block left and width with a minimum visible width', () => {
    const { methods } = TaskManagementPage

    const style = methods.timelineBlockStyle.call(
      {
        timeToSeconds: methods.timeToSeconds,
        timelineBlockColor: methods.timelineBlockColor
      },
      {
        time: '12:00:00',
        duration: 10,
        status: 'playing',
        enabled: true,
        scheduleEnabled: true
      }
    )

    expect(style.left).toBe('50%')
    expect(style.width).toBe('max(0.0116%, 6px)')
    expect(style.backgroundColor).toBe('#409eff')
    expect(style.opacity).toBe(0.92)
  })

  it('resolves picker cell dates for current, previous, next, and cross-year cells', () => {
    const { methods } = TaskManagementPage
    const panelDate = new Date('2026-01-15T00:00:00')

    const currentCell = document.createElement('td')
    currentCell.innerHTML = '<div><span>15</span></div>'
    expect(methods.resolveHolidayPickerCellDateKey.call({}, currentCell, panelDate)).toBe('2026-01-15')

    const prevCell = document.createElement('td')
    prevCell.className = 'prev-month'
    prevCell.innerHTML = '<div><span>31</span></div>'
    expect(methods.resolveHolidayPickerCellDateKey.call({}, prevCell, panelDate)).toBe('2025-12-31')

    const nextCell = document.createElement('td')
    nextCell.className = 'next-month'
    nextCell.innerHTML = '<div><span>1</span></div>'
    expect(methods.resolveHolidayPickerCellDateKey.call({}, nextCell, panelDate)).toBe('2026-02-01')

    const decemberPanel = new Date('2026-12-10T00:00:00')
    const crossYearNextCell = document.createElement('td')
    crossYearNextCell.className = 'next-month'
    crossYearNextCell.innerHTML = '<div><span>3</span></div>'
    expect(methods.resolveHolidayPickerCellDateKey.call({}, crossYearNextCell, decemberPanel)).toBe('2027-01-03')
  })

  it('loads panel-adjacent years only when needed', async () => {
    const { methods } = TaskManagementPage
    const loadedYears = []
    const result = await methods.ensureHolidayPickerPanelYearsLoaded.call({
      holidayDaysByYear: { '2026': {} },
      holidayPickerPanelYears: () => ['2025', '2026'],
      ensureHolidayYearLoaded: async (year) => {
        loadedYears.push(year)
      }
    })

    expect(result).toBe(true)
    expect(loadedYears).toEqual(['2025'])

    const noLoad = await methods.ensureHolidayPickerPanelYearsLoaded.call({
      holidayDaysByYear: { '2025': {}, '2026': {} },
      holidayPickerPanelYears: () => ['2025', '2026'],
      ensureHolidayYearLoaded: async () => {
        throw new Error('should not load')
      }
    })
    expect(noLoad).toBe(false)
  })

  it('maps task title and audio source to separate fields', () => {
    const { methods } = TaskManagementPage
    const row = methods.mapScheduleTask.call(
      {
        taskKey: (scheduleName, taskId) => `${scheduleName}:${taskId}`,
        taskDisplayName: methods.taskDisplayName,
        taskSourceName: methods.taskSourceName,
        formatLocation: () => 'A区 / 讲台终端',
        toTime: () => '09:40:00',
        toDurationSeconds: () => 21
      },
      { schedule_name: '南校作息' },
      {
        taskid: '78997',
        customName: '第二节下课',
        taskname: '第二节下课',
        audio: '下课铃',
        starttime: '09:40:00',
        timelength: 21,
        enablestate: 1
      },
      0,
      0,
      '2026-04-09'
    )

    expect(row.displayName).toBe('第二节下课')
    expect(row.sourceName).toBe('下课铃')
  })

  it('falls back to medianame when audio is missing', () => {
    const { methods } = TaskManagementPage
    const row = methods.mapScheduleTask.call(
      {
        taskKey: (scheduleName, taskId) => `${scheduleName}:${taskId}`,
        taskDisplayName: methods.taskDisplayName,
        taskSourceName: methods.taskSourceName,
        formatLocation: () => 'A区 / 讲台终端',
        toTime: () => '10:10:00',
        toDurationSeconds: () => 20
      },
      { schedule_name: '南校作息' },
      {
        taskid: '78999',
        customName: '第三节上课',
        taskname: '第三节上课',
        medianame: '上课铃',
        starttime: '10:10:00',
        timelength: 20,
        enablestate: 1
      },
      0,
      0,
      '2026-04-09'
    )

    expect(row.displayName).toBe('第三节上课')
    expect(row.sourceName).toBe('上课铃')
  })

  it('saves task name and audio source independently during inline edit', async () => {
    const { methods } = TaskManagementPage
    let updatedTask = null
    const mutateTasks = jest.fn(async (targets, updater) => {
      const rawTask = {
        customName: '第二节下课',
        taskname: '第二节下课',
        audio: '下课铃',
        medianame: '下课铃'
      }
      updater(rawTask)
      updatedTask = rawTask
      return true
    })
    const cancelInlineEdit = jest.fn()

    await methods.saveInlineEdit.call(
      {
        editDraft: {
          displayName: '课间提示',
          sourceName: '提示铃',
          time: '09:45:00',
          volume: 66
        },
        taskDisplayName: methods.taskDisplayName,
        taskSourceName: methods.taskSourceName,
        normalizeTimeInput: (value) => value,
        isTaskReadonly: methods.isTaskReadonly,
        mutateTasks,
        cancelInlineEdit,
        $message: { error: jest.fn() }
      },
      {
        id: '南校作息:78997',
        displayName: '第二节下课',
        sourceName: '下课铃',
        time: '09:40:00',
        volume: 50
      }
    )

    expect(mutateTasks).toHaveBeenCalled()
    expect(updatedTask.customName).toBe('课间提示')
    expect(updatedTask.taskname).toBe('课间提示')
    expect(updatedTask.audio).toBe('提示铃')
    expect(updatedTask.medianame).toBe('提示铃')
    expect(cancelInlineEdit).toHaveBeenCalled()
  })

  it('uses the task display name in delete confirmation', async () => {
    const { methods } = TaskManagementPage
    const $confirm = jest.fn().mockResolvedValue(undefined)
    const mutateTasks = jest.fn().mockResolvedValue(true)

    await methods.deleteTask.call(
      {
        isTaskReadonly: methods.isTaskReadonly,
        $confirm,
        mutateTasks
      },
      {
        displayName: '第三节上课',
        sourceName: '上课铃'
      }
    )

    expect($confirm).toHaveBeenCalled()
    expect($confirm.mock.calls[0][0]).toContain('第三节上课')
    expect($confirm.mock.calls[0][0]).not.toContain('上课铃')
  })
  it('applyOverrides marks migrate source tasks and appends migrate-after once rows on target date', () => {
    const { methods } = TaskManagementPage
    const sourceDay = methods.applyOverrides.call({
      taskKey: methods.taskKey,
      selectLatestOnceOverrides: () => [{
        id: 'override-1',
        mode: 'once',
        action: 'migrate',
        schedule_name: '夏季作息',
        task_ids: ['81291'],
        time_start: '2026-04-23 07:50:00',
        new_time_start: '2026-04-26 07:50:00',
        once_task_specs: [{
          taskid: '93011',
          taskname: '早读开始铃',
          source_task_id: '81291',
          source_task_name: '早读开始铃',
          startdate: '2026-04-26',
          starttime: '07:50:00',
          duration_seconds: 20,
          medianame: '运动员进行曲.mp3',
          volume: 80,
          terminalids: ['50', '52'],
          terminalnames: ['定压备份功放', '操场音箱'],
          liveterminalid: '50',
          liveterminalname: '定压备份功放',
          location: [['无分区终端', '定压备份功放'], ['操场', '操场音箱']],
          once_action: 'migrate'
        }]
      }],
      normalizeOnceSpecs: methods.normalizeOnceSpecs,
      buildOnceDisplayTask: methods.buildOnceDisplayTask,
      normalizeDate: methods.normalizeDate,
      mergeClass: methods.mergeClass,
      formatLocation: methods.formatLocation,
      normalizeZoneLabel: (value) => value,
      toTime: methods.toTime,
      toDurationSeconds: methods.toDurationSeconds
    }, [{
      scheduleName: '夏季作息',
      taskId: '81291',
      time: '07:50:00',
      displayName: '早读开始铃',
      sourceName: '上课铃.mp3',
      itemClass: ''
    }], '2026-04-23')

    expect(sourceDay).toHaveLength(1)
    expect(sourceDay.some((item) => item.onceTaskId)).toBe(false)
    expect(sourceDay[0].badge).toBe('迁移前')
    expect(sourceDay[0].badgeType).toBe('badge-migrate-before')
    expect(sourceDay[0].itemClass).toContain('accent-gray')

    const targetDay = methods.applyOverrides.call({
      taskKey: methods.taskKey,
      selectLatestOnceOverrides: () => [{
        id: 'override-1',
        mode: 'once',
        action: 'migrate',
        schedule_name: '夏季作息',
        task_ids: ['81291'],
        time_start: '2026-04-23 07:50:00',
        new_time_start: '2026-04-26 07:50:00',
        once_task_specs: [{
          taskid: '93011',
          taskname: '早读开始铃',
          source_task_id: '81291',
          source_task_name: '早读开始铃',
          startdate: '2026-04-26',
          starttime: '07:50:00',
          duration_seconds: 20,
          medianame: '运动员进行曲.mp3',
          volume: 80,
          terminalids: ['50', '52'],
          terminalnames: ['定压备份功放', '操场音箱'],
          liveterminalid: '50',
          liveterminalname: '定压备份功放',
          location: [['无分区终端', '定压备份功放'], ['操场', '操场音箱']],
          once_action: 'migrate'
        }]
      }],
      normalizeOnceSpecs: methods.normalizeOnceSpecs,
      buildOnceDisplayTask: methods.buildOnceDisplayTask,
      normalizeDate: methods.normalizeDate,
      mergeClass: methods.mergeClass,
      formatLocation: methods.formatLocation,
      normalizeZoneLabel: (value) => value,
      toTime: methods.toTime,
      toDurationSeconds: methods.toDurationSeconds
    }, [{
      scheduleName: '夏季作息',
      taskId: '81291',
      time: '07:50:00',
      displayName: '早读开始铃',
      sourceName: '上课铃.mp3',
      itemClass: ''
    }], '2026-04-26')

    expect(targetDay).toHaveLength(2)
    const onceRow = targetDay.find((item) => item.onceTaskId === '93011')
    expect(onceRow).toEqual(expect.objectContaining({
      badge: '迁移后',
      badgeType: 'badge-migrate-after',
      isOnceEphemeral: true,
      displayName: '早读开始铃'
    }))
  })
  it('applyOverrides marks swap tasks and appends swap-after once rows on both dates', () => {
    const { methods } = TaskManagementPage
    const sourceDay = methods.applyOverrides.call({
      taskKey: methods.taskKey,
      selectLatestOnceOverrides: () => [{
        id: 'override-2',
        mode: 'once',
        action: 'swap',
        schedule_name: '夏季作息',
        source_task_ids: ['81291'],
        target_task_ids: ['81311'],
        source_time_start: '2026-04-23 07:50:00',
        target_time_start: '2026-04-23 14:25:00',
        once_task_specs: [{
          taskid: '93021',
          taskname: '早读开始铃',
          source_task_id: '81291',
          source_task_name: '早读开始铃',
          startdate: '2026-04-23',
          starttime: '14:25:00',
          duration_seconds: 20,
          medianame: '运动员进行曲.mp3',
          role: 'source_to_target',
          once_action: 'swap'
        }, {
          taskid: '93022',
          taskname: '下午第一节课上课',
          source_task_id: '81311',
          source_task_name: '下午第一节课上课',
          startdate: '2026-04-23',
          starttime: '07:50:00',
          duration_seconds: 20,
          medianame: '运动员进行曲.mp3',
          role: 'target_to_source',
          once_action: 'swap'
        }]
      }],
      normalizeOnceSpecs: methods.normalizeOnceSpecs,
      buildOnceDisplayTask: methods.buildOnceDisplayTask,
      normalizeDate: methods.normalizeDate,
      mergeClass: methods.mergeClass,
      formatLocation: methods.formatLocation,
      normalizeZoneLabel: (value) => value,
      toTime: methods.toTime,
      toDurationSeconds: methods.toDurationSeconds
    }, [{
      scheduleName: '夏季作息',
      taskId: '81291',
      time: '07:50:00',
      displayName: '早读开始铃',
      sourceName: '上课铃.mp3',
      itemClass: ''
      }, {
        scheduleName: '夏季作息',
        taskId: '81311',
        time: '14:25:00',
        displayName: '下午第一节课上课',
        sourceName: '上课铃.mp3',
        itemClass: ''
      }], '2026-04-23')

    expect(sourceDay).toHaveLength(4)
    expect(sourceDay[0].badge).toBe('互换前')
    expect(sourceDay[1].badge).toBe('互换前')
    const sourceOnceRow = sourceDay.find((item) => item.onceTaskId === '93022')
    expect(sourceOnceRow).toEqual(expect.objectContaining({
      badge: '互换后',
      badgeType: 'badge-swap-after-b',
      isOnceEphemeral: true,
      onceRole: 'target_to_source'
    }))
    const targetOnceRowSameDay = sourceDay.find((item) => item.onceTaskId === '93021')
    expect(targetOnceRowSameDay).toEqual(expect.objectContaining({
      badge: '互换后',
      badgeType: 'badge-swap-after-a',
      isOnceEphemeral: true,
      onceRole: 'source_to_target'
    }))

    const targetDay = methods.applyOverrides.call({
      taskKey: methods.taskKey,
      selectLatestOnceOverrides: () => [{
        id: 'override-2',
        mode: 'once',
        action: 'swap',
        schedule_name: '夏季作息',
        source_task_ids: ['81291'],
        target_task_ids: ['81311'],
        source_time_start: '2026-04-23 07:50:00',
        target_time_start: '2026-04-23 14:25:00',
        once_task_specs: [{
          taskid: '93021',
          taskname: '早读开始铃',
          source_task_id: '81291',
          source_task_name: '早读开始铃',
          startdate: '2026-04-23',
          starttime: '14:25:00',
          duration_seconds: 20,
          medianame: '运动员进行曲.mp3',
          role: 'source_to_target',
          once_action: 'swap'
        }, {
          taskid: '93022',
          taskname: '下午第一节课上课',
          source_task_id: '81311',
          source_task_name: '下午第一节课上课',
          startdate: '2026-04-23',
          starttime: '07:50:00',
          duration_seconds: 20,
          medianame: '运动员进行曲.mp3',
          role: 'target_to_source',
          once_action: 'swap'
        }]
      }],
      normalizeOnceSpecs: methods.normalizeOnceSpecs,
      buildOnceDisplayTask: methods.buildOnceDisplayTask,
      normalizeDate: methods.normalizeDate,
      mergeClass: methods.mergeClass,
      formatLocation: methods.formatLocation,
      normalizeZoneLabel: (value) => value,
      toTime: methods.toTime,
      toDurationSeconds: methods.toDurationSeconds
    }, [{
      scheduleName: '夏季作息',
      taskId: '81291',
      time: '07:50:00',
      displayName: '早读开始铃',
      sourceName: '上课铃.mp3',
      itemClass: ''
    }, {
      scheduleName: '夏季作息',
      taskId: '81311',
      time: '14:25:00',
      displayName: '下午第一节课上课',
      sourceName: '上课铃.mp3',
      itemClass: ''
    }], '2026-04-23')

    const targetOnceRow = targetDay.find((item) => item.onceTaskId === '93021')
    expect(targetOnceRow).toEqual(expect.objectContaining({
      badge: '互换后',
      badgeType: 'badge-swap-after-a',
      isOnceEphemeral: true,
      onceRole: 'source_to_target'
    }))
  })
  it('isRenderableOnceOverride hides cleaned once overrides', () => {
    const { methods } = TaskManagementPage

    expect(methods.isRenderableOnceOverride({
      mode: 'once',
      execution_state: 'scheduled',
      active: true,
      remote_synced: true,
      cleanup_state: 'cleaned'
    })).toBe(false)
  })
  it('buildOnceDisplayTask does not invent duration and keeps zero volume', () => {
    const { methods } = TaskManagementPage
    const ctx = {
      normalizeDate: methods.normalizeDate,
      toTime: methods.toTime,
      formatLocation: methods.formatLocation,
      taskDurationValue: methods.taskDurationValue,
      taskDurationText: methods.taskDurationText,
      taskVolumeText: methods.taskVolumeText
    }
    const result = methods.buildOnceDisplayTask.call({
      normalizeDate: methods.normalizeDate,
      toTime: methods.toTime,
      formatLocation: methods.formatLocation
    }, { id: 'override-3', schedule_name: '夏季作息' }, {
      taskId: '93031',
      label: '静音提示',
      mediaName: '',
      mediaDisplay: '—',
      hasMediaName: false,
      time: '10:00:00',
      onceDate: '2026-04-26',
      hasDurationSeconds: false,
      durationSeconds: null,
      hasVolume: true,
      volume: 0,
      timelengthtype: '1',
      terminalids: [],
      terminalnames: [],
      liveterminalid: '',
      liveterminalname: '',
      location: [],
      onceAction: 'migrate',
      onceRole: ''
    }, '0-2')

    expect(result.duration).toBe('')
    expect(result.volume).toBe(0)
    expect(methods.taskDurationText.call(ctx, result)).toBe('时长 —')
    expect(methods.taskVolumeText.call(ctx, result)).toBe('0%')
  })
  it('selectedTasks and select-all ignore readonly once rows', () => {
    const { computed, methods } = TaskManagementPage
    const tasksForDay = [{
      id: 'base-1',
      isOnceEphemeral: false
    }, {
      id: 'once-1',
      isOnceEphemeral: true
    }]

    const selected = computed.selectedTasks.call({
      selectedTaskIds: ['base-1', 'once-1'],
      tasksForDay,
      isTaskReadonly: methods.isTaskReadonly
    })
    expect(selected.map((item) => item.id)).toEqual(['base-1'])

    const allVisible = computed.allVisibleSelected.call({
      filteredTasks: tasksForDay,
      selectedTaskIds: ['base-1'],
      isTaskReadonly: methods.isTaskReadonly
    })
    expect(allVisible).toBe(true)

    const ctx = {
      filteredTasks: tasksForDay,
      selectedTaskIds: [],
      isTaskReadonly: methods.isTaskReadonly
    }
    methods.toggleSelectAll.call(ctx, true)
    expect(ctx.selectedTaskIds).toEqual(['base-1'])
  })
  it('blocks readonly once rows from inline edit, toggle, delete, and mutate flows', async() => {
    const { methods } = TaskManagementPage
    const onceTask = { id: 'once-1', isOnceEphemeral: true, enabled: true, displayName: '临时任务' }

    const startCtx = {
      editingTaskId: '',
      editDraft: {},
      isTaskReadonly: methods.isTaskReadonly
    }
    methods.startInlineEdit.call(startCtx, onceTask)
    expect(startCtx.editingTaskId).toBe('')

    const mutateTasks = jest.fn()
    await methods.toggleTaskEnabled.call({
      isTaskReadonly: methods.isTaskReadonly,
      setTaskEnabled: mutateTasks
    }, onceTask)
    expect(mutateTasks).not.toHaveBeenCalled()

    const confirm = jest.fn()
    await methods.deleteTask.call({
      isTaskReadonly: methods.isTaskReadonly,
      $confirm: confirm,
      mutateTasks: jest.fn()
    }, onceTask)
    expect(confirm).not.toHaveBeenCalled()

    const message = { warning: jest.fn() }
    const saved = await methods.mutateTasks.call({
      isTaskReadonly: methods.isTaskReadonly,
      uniqueTaskRefs: methods.uniqueTaskRefs,
      normalizeTaskRef: methods.normalizeTaskRef,
      taskKey: methods.taskKey,
      $message: message
    }, [onceTask], () => true, 'done')
    expect(saved).toBe(false)
    expect(message.warning).toHaveBeenCalledWith('请先选择任务')
  })
  it('summarizes selected date once overrides by current day', () => {
    const { computed } = TaskManagementPage
    const summary = computed.selectedDateOnceSummary.call({
      overrides: [{
        id: 'override-1',
        mode: 'once',
        action: 'migrate',
        schedule_name: '夏季作息',
        execution_state: 'scheduled',
        active: true,
        remote_synced: true,
        cleanup_state: 'pending',
        once_task_specs: [{
          taskid: '93011',
          taskname: '早读开始铃',
          startdate: '2026-04-26',
          starttime: '07:50:00',
          once_action: 'migrate'
        }]
      }, {
        id: 'override-2',
        mode: 'once',
        action: 'swap',
        schedule_name: '夏季作息',
        execution_state: 'scheduled',
        active: true,
        remote_synced: true,
        cleanup_state: 'pending',
        once_task_specs: [{
          taskid: '93021',
          taskname: '下午第一节课上课',
          startdate: '2026-04-26',
          starttime: '14:25:00',
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
        cleanup_state: 'pending',
        time_start: '2026-04-26 18:00:00',
        time_end: '2026-04-26 18:30:00',
        task_ids: ['81291'],
        once_task_specs: []
      }],
      currentDateKey: '2026-04-26'
    })

    expect(summary.count).toBe(3)
    expect(summary.actionCounts.migrate).toBe(1)
    expect(summary.actionCounts.swap).toBe(1)
    expect(summary.actionCounts.cancel).toBe(1)
  })
  it('opens task-scheduler once panel for the selected date', () => {
    const { methods } = TaskManagementPage
    const push = jest.fn()

    methods.openSelectedDateOncePanel.call({
      $router: { push },
      currentDateKey: '2026-04-26'
    })

    expect(push).toHaveBeenCalledWith({
      name: 'TaskScheduler',
      query: { oncePanel: '1', date: '2026-04-26' }
    })
  })
})
