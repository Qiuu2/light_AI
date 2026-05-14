const ONCE_PLACEHOLDER = '\u2014'
const DEFAULT_ONCE_LABEL = '\u4e00\u6b21\u6027\u4efb\u52a1'

const normalizeString = (value) => String(value ?? '').trim()

const hasValue = (value) => {
  if (value === undefined || value === null) return false
  if (typeof value === 'string') return value.trim() !== ''
  return true
}

const normalizeStringList = (value) => {
  if (!Array.isArray(value)) return []
  const seen = new Set()
  const items = []
  value.forEach((item) => {
    const text = normalizeString(item)
    if (!text || seen.has(text)) return
    seen.add(text)
    items.push(text)
  })
  return items
}

const cloneLocation = (value) => {
  if (!Array.isArray(value)) return []
  return value.map((item) => {
    if (Array.isArray(item)) return item.map((part) => normalizeString(part)).filter(Boolean)
    return normalizeString(item)
  })
}

const normalizeDate = (value) => {
  const text = normalizeString(value)
  if (!text) return ''
  const match = text.match(/\d{4}-\d{2}-\d{2}/)
  return match ? match[0] : ''
}

const normalizeTime = (value) => {
  const text = normalizeString(value)
  if (!text) return ''
  if (/^\d{2}:\d{2}:\d{2}$/.test(text)) return text
  if (/^\d{2}:\d{2}$/.test(text)) return `${text}:00`
  const match = text.match(/(\d{1,2}):(\d{1,2})(?::(\d{1,2}))?/)
  if (!match) return ''
  const h = Number(match[1])
  const m = Number(match[2])
  const s = Number(match[3] || 0)
  if ([h, m, s].some((item) => Number.isNaN(item))) return ''
  if (h > 23 || m > 59 || s > 59) return ''
  return `${`${h}`.padStart(2, '0')}:${`${m}`.padStart(2, '0')}:${`${s}`.padStart(2, '0')}`
}

const parseDateTime = (value) => {
  const text = normalizeString(value)
  if (!text) return null
  const normalized = text.includes('T') ? text : text.replace(' ', 'T')
  const parsed = new Date(normalized)
  if (Number.isNaN(parsed.getTime())) return null
  return parsed
}

const normalizeNumeric = (value, fallback = 0) => {
  const num = Number(value)
  if (Number.isNaN(num)) return fallback
  return num
}

const parseOptionalNumber = (value) => {
  if (!hasValue(value)) return null
  const num = Number(value)
  if (Number.isNaN(num)) return null
  return num
}

const isActiveOnceOverride = (override) => {
  if (!override || normalizeString(override.mode) !== 'once') return false
  if (normalizeString(override.execution_state) !== 'scheduled') return false
  if (override.active !== true) return false
  if (override.remote_synced === false) return false
  if (normalizeString(override.cleanup_state) === 'cleaned') return false
  return true
}

const onceOverrideKey = (override = {}, idx = 0) => {
  const action = normalizeString(override.action)
  const scheduleName = normalizeString(override.schedule_name)
  if (!action || !scheduleName) return `idx:${idx}`
  if (action === 'cancel') {
    const date = normalizeDate(override.time_start)
    const taskIds = normalizeStringList(override.task_ids).sort().join(',')
    return `${action}|${scheduleName}|${date}|${taskIds}`
  }
  if (action === 'migrate') {
    const oldDate = normalizeDate(override.time_start)
    const newDate = normalizeDate(override.new_time_start)
    const taskIds = normalizeStringList(override.task_ids).sort().join(',')
    return `${action}|${scheduleName}|${oldDate}|${newDate}|${taskIds}`
  }
  if (action === 'swap') {
    const sourceDate = normalizeDate(override.source_time_start)
    const targetDate = normalizeDate(override.target_time_start)
    const sourceIds = normalizeStringList(override.source_task_ids).sort().join(',')
    const targetIds = normalizeStringList(override.target_task_ids).sort().join(',')
    return `${action}|${scheduleName}|${sourceDate}|${targetDate}|${sourceIds}|${targetIds}`
  }
  return `${action}|${scheduleName}|idx:${idx}`
}

const onceOverrideRank = (override = {}, idx = 0) => {
  const createdAt = parseDateTime(override.created_at)
  const base = createdAt ? createdAt.getTime() : 0
  return base + (idx / 1000)
}

const selectLatestOnceOverrides = (overrides = [], options = {}) => {
  const includeInactive = options.includeInactive === true
  const list = Array.isArray(overrides) ? overrides : []
  const picked = new Map()
  list.forEach((override, idx) => {
    if (!override || normalizeString(override.mode) !== 'once') return
    if (!includeInactive && !isActiveOnceOverride(override)) return
    const key = onceOverrideKey(override, idx)
    const rank = onceOverrideRank(override, idx)
    const prev = picked.get(key)
    if (!prev || rank >= prev.rank) {
      picked.set(key, { rank, override })
    }
  })
  return Array.from(picked.values())
    .sort((left, right) => left.rank - right.rank)
    .map((item) => item.override)
}

export const normalizeOnceTaskSpec = (spec = {}, override = {}) => {
  const location = cloneLocation(spec.location)
  return {
    taskId: normalizeString(spec.taskid),
    label: normalizeString(spec.taskname || spec.source_task_name || spec.remote_taskname) || DEFAULT_ONCE_LABEL,
    mediaName: normalizeString(spec.medianame || spec.media_name),
    mediaId: normalizeString(spec.mediaid),
    time: normalizeTime(spec.starttime),
    onceDate: normalizeDate(spec.startdate || spec.once_date),
    durationSeconds: Math.max(0, Math.round(normalizeNumeric(spec.duration_seconds, 0))),
    volume: normalizeNumeric(spec.volume, 0),
    timelength: normalizeString(spec.timelength),
    timelengthtype: normalizeString(spec.timelengthtype),
    terminalids: normalizeStringList(spec.terminalids),
    terminalnames: normalizeStringList(spec.terminalnames),
    liveterminalid: normalizeString(spec.liveterminalid),
    liveterminalname: normalizeString(spec.liveterminalname),
    location,
    onceAction: normalizeString(spec.once_action || override.action),
    onceRole: normalizeString(spec.role),
    scheduleName: normalizeString(spec.schedule_name || override.schedule_name),
    sourceTaskId: normalizeString(spec.source_task_id),
    sourceTaskName: normalizeString(spec.source_task_name)
  }
}

export const buildOnceDisplaySnapshot = (spec = {}, override = {}) => {
  const once = normalizeOnceTaskSpec(spec, override)
  const durationValue = parseOptionalNumber(spec.duration_seconds)
  const volumeValue = parseOptionalNumber(spec.volume)
  const hasDurationSeconds = durationValue !== null && durationValue > 0
  const hasVolume = volumeValue !== null && volumeValue >= 0
  const hasMediaName = Boolean(once.mediaName)
  const hasLocation = Array.isArray(once.location) && once.location.some((item) => {
    if (Array.isArray(item)) return item.some(Boolean)
    return Boolean(item)
  })
  const hasTerminalSnapshot = Boolean(
    once.terminalids.length ||
    once.terminalnames.length ||
    once.liveterminalid ||
    once.liveterminalname ||
    hasLocation
  )

  return {
    ...once,
    durationSeconds: hasDurationSeconds ? Math.max(1, Math.round(durationValue)) : null,
    hasDurationSeconds,
    durationPlaceholder: hasDurationSeconds ? '' : ONCE_PLACEHOLDER,
    mediaDisplay: hasMediaName ? once.mediaName : ONCE_PLACEHOLDER,
    hasMediaName,
    volume: hasVolume ? volumeValue : null,
    hasVolume,
    volumePlaceholder: hasVolume ? '' : ONCE_PLACEHOLDER,
    hasLocation,
    hasTerminalSnapshot,
    placeholder: ONCE_PLACEHOLDER
  }
}

const onceActionPanelLabel = (action) => {
  const text = normalizeString(action)
  if (text === 'migrate') return '迁移后'
  if (text === 'swap') return '互换后'
  if (text === 'cancel') return '取消'
  return '一次性'
}

export const buildOncePanelItem = (spec = {}, override = {}) => {
  const once = buildOnceDisplaySnapshot(spec, override)
  const canEdit = Boolean(once.taskId)
  return {
    overrideId: normalizeString(override.id),
    onceTaskId: once.taskId,
    scheduleName: once.scheduleName,
    taskId: once.taskId,
    taskLabel: once.label,
    sourceTaskId: once.sourceTaskId,
    sourceTaskName: once.sourceTaskName,
    onceDate: once.onceDate,
    onceAction: once.onceAction,
    onceActionLabel: onceActionPanelLabel(once.onceAction),
    onceRole: once.onceRole,
    time: once.time,
    durationSeconds: once.durationSeconds,
    hasDurationSeconds: once.hasDurationSeconds,
    mediaName: once.mediaName,
    mediaDisplay: once.mediaDisplay,
    hasMediaName: once.hasMediaName,
    mediaId: once.mediaId,
    volume: once.volume,
    hasVolume: once.hasVolume,
    terminalids: once.terminalids,
    terminalnames: once.terminalnames,
    liveterminalid: once.liveterminalid,
    liveterminalname: once.liveterminalname,
    location: once.location,
    hasLocation: once.hasLocation,
    hasTerminalSnapshot: once.hasTerminalSnapshot,
    editablePayload: {
      taskname: once.label,
      mediaid: once.mediaId || '',
      medianame: once.mediaName || '',
      startdate: once.onceDate || '',
      starttime: once.time || '',
      timelength: once.timelength || '',
      timelengthtype: once.timelengthtype || '',
      volume: once.hasVolume ? once.volume : '',
      terminalids: [...once.terminalids],
      terminalnames: [...once.terminalnames],
      liveterminalid: once.liveterminalid || '',
      liveterminalname: once.liveterminalname || '',
      location: cloneLocation(once.location)
    },
    sourceSummary: once.sourceTaskName
      ? `${onceActionPanelLabel(once.onceAction)} · ${once.sourceTaskName}`
      : onceActionPanelLabel(once.onceAction),
    placeholder: once.placeholder,
    summaryOnly: false,
    mode: canEdit ? 'editable' : 'readonly',
    canEdit,
    canDelete: canEdit,
    endTime: '',
    taskIds: once.sourceTaskId ? [once.sourceTaskId] : [],
    note: ''
  }
}

const buildCancelSummaryItem = (override = {}) => {
  const taskIds = normalizeStringList(override.task_ids)
  const onceDate = normalizeDate(override.time_start)
  const startTime = normalizeTime(override.time_start)
  const endTime = normalizeTime(override.time_end)
  const sourceTaskName = taskIds.length
    ? `任务 ID：${taskIds.join('、')}`
    : '未定位来源任务'
  const taskLabel = taskIds.length <= 1
    ? '取消任务'
    : `取消 ${taskIds.length} 个任务`
  return {
    overrideId: normalizeString(override.id),
    onceTaskId: '',
    scheduleName: normalizeString(override.schedule_name),
    taskId: '',
    taskLabel,
    sourceTaskId: taskIds.join(','),
    sourceTaskName,
    onceDate,
    onceAction: 'cancel',
    onceActionLabel: onceActionPanelLabel('cancel'),
    onceRole: '',
    time: startTime,
    endTime,
    durationSeconds: null,
    hasDurationSeconds: false,
    mediaName: '',
    mediaDisplay: ONCE_PLACEHOLDER,
    hasMediaName: false,
    mediaId: '',
    volume: null,
    hasVolume: false,
    terminalids: [],
    terminalnames: [],
    liveterminalid: '',
    liveterminalname: '',
    location: [],
    hasLocation: false,
    hasTerminalSnapshot: false,
    editablePayload: null,
    sourceSummary: sourceTaskName,
    placeholder: ONCE_PLACEHOLDER,
    summaryOnly: true,
    mode: 'readonly',
    canEdit: false,
    canDelete: false,
    taskIds,
    note: '该条目仅用于说明本次取消，不存在可编辑的临时任务实体。'
  }
}

const matchesOnceFilters = (item = {}, filters = {}) => {
  const date = normalizeDate(filters.date)
  const action = normalizeString(filters.action)
  if (date && item.onceDate !== date) return false
  if (action && item.onceAction !== action) return false
  return true
}

export const buildOncePanelItems = (overrides = [], options = {}) => {
  const scheduleName = normalizeString(options.scheduleName || options.planName)
  const includeInactive = options.includeInactive === true
  const includeItemsWithoutTaskId = options.includeItemsWithoutTaskId === true
  const includeSummaryOnly = options.includeSummaryOnly !== false
  const items = []
  selectLatestOnceOverrides(overrides, { includeInactive }).forEach((override) => {
    if (scheduleName && normalizeString(override.schedule_name) !== scheduleName) return
    const specs = Array.isArray(override?.once_task_specs) ? override.once_task_specs : []
    if (
      includeSummaryOnly &&
      normalizeString(override?.action) === 'cancel' &&
      specs.length === 0
    ) {
      const summaryItem = buildCancelSummaryItem(override)
      if (matchesOnceFilters(summaryItem, options)) {
        items.push(summaryItem)
      }
    }
    specs.forEach((spec) => {
      const item = buildOncePanelItem(spec, override)
      if (!includeItemsWithoutTaskId && !item.onceTaskId) return
      if (!matchesOnceFilters(item, options)) return
      items.push(item)
    })
  })
  items.sort((left, right) => {
    const leftKey = `${left.onceDate} ${left.time} ${left.taskLabel} ${left.mode}`
    const rightKey = `${right.onceDate} ${right.time} ${right.taskLabel} ${right.mode}`
    return leftKey.localeCompare(rightKey, 'zh-Hans-CN')
  })
  return items
}

export const groupOncePanelItems = (overrides = [], options = {}) => {
  const items = buildOncePanelItems(overrides, options)
  const groups = []
  const groupMap = new Map()
  items.forEach((item) => {
    const dateKey = item.onceDate || ''
    const actionKey = item.onceAction || ''
    const groupKey = `${dateKey}|${actionKey}`
    let group = groupMap.get(groupKey)
    if (!group) {
      group = {
        dateKey,
        actionKey,
        actionLabel: onceActionPanelLabel(actionKey),
        items: []
      }
      groupMap.set(groupKey, group)
      groups.push(group)
    }
    group.items.push(item)
  })
  return groups
}

export const countOnceSpecs = (overrides = [], filters = {}) => buildOncePanelItems(overrides, filters).length

export const summarizeOnceSpecs = (overrides = [], filters = {}) => {
  const items = buildOncePanelItems(overrides, filters)
  const actionCounts = {}
  const dates = []
  const dateSet = new Set()
  items.forEach((item) => {
    const action = item.onceAction || ''
    actionCounts[action] = (actionCounts[action] || 0) + 1
    if (item.onceDate && !dateSet.has(item.onceDate)) {
      dateSet.add(item.onceDate)
      dates.push(item.onceDate)
    }
  })
  dates.sort((left, right) => left.localeCompare(right))
  return {
    count: items.length,
    dates,
    actionCounts,
    items,
    dateLabel: dates.length > 2 ? `${dates.slice(0, 2).join(', ')} 等 ${dates.length} 天` : dates.join(', ')
  }
}

export { ONCE_PLACEHOLDER }
