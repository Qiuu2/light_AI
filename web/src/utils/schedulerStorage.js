const STORAGE_KEY = 'AI_SCHEDULER_DATA'
const DRAFT_STORAGE_KEY = 'AI_SCHEDULER_DRAFTS_V1'

const defaultData = {
  plans: [
    {
      id: 1,
      name: 'default-plan-a',
      status: '启用',
      tasks: [
        {
          id: 'p1-t1',
          customName: 'morning-bell',
          audio: 'campus-bell.mp3',
          time: '08:00:00',
          duration: '05',
          loop: 1,
          durationMode: 'loop',
          weekdays: ['周一', '周二', '周三', '周四', '周五'],
          dateRange: ['2025-12-29', '2025-12-31'],
          volume: 45,
          location: [['教学楼', '一层', '101音箱']],
          powerOn: true,
          taskLevel: 'normal',
          sendMode: 'single',
          playMode: 'serial',
          ledSetting: 'text'
        }
      ]
    },
    {
      id: 2,
      name: 'default-plan-b',
      status: '停用',
      tasks: []
    }
  ],
  broadcasts: [
    {
      id: 1,
      name: 'manual-broadcast-a',
      status: '待执行',
      volume: 55,
      emergency: false,
      audio: 'safety.wav',
      duration: '08',
      loop: 1,
      durationMode: 'loop',
      location: [['教学楼', '一层', '101音箱']]
    },
    {
      id: 2,
      name: 'manual-broadcast-b',
      status: '执行中',
      volume: 50,
      emergency: false,
      audio: 'notice.mp3',
      duration: '05',
      loop: 1,
      durationMode: 'loop',
      location: [['操场', '东侧', '东1']]
    }
  ],
  livecasts: [
    {
      id: 1,
      name: 'livecast-a',
      status: '启用',
      volume: 48,
      audio: 'source-a',
      time: '14:00',
      duration: '20',
      loop: 1,
      durationMode: 'loop',
      location: [['体育馆', '看台区', '北侧音箱']]
    },
    {
      id: 2,
      name: 'livecast-b',
      status: '停用',
      volume: 38,
      audio: 'source-b',
      time: '16:00',
      duration: '15',
      loop: 1,
      durationMode: 'loop',
      location: [['操场', '西侧', '西1']]
    }
  ],
  runtimePlays: []
}

const defaultDrafts = {
  plans: [],
  planDirtyIds: [],
  planDeletedIds: [],
  planBaseSnapshot: [],
  invalidPlanDrafts: [],
  invalidPlanBaseSnapshot: [],
  planDraftIssues: [],
  broadcasts: [],
  broadcastDirtyIds: [],
  broadcastDeletedIds: [],
  broadcastBaseSnapshot: [],
  dirtyScopes: [],
  updatedAt: ''
}

function clone(value) {
  return JSON.parse(JSON.stringify(value))
}

function normalizeDirtyScopes(value) {
  const scopes = Array.isArray(value) ? value : []
  return Array.from(new Set(scopes.map((item) => String(item || '').trim()).filter((item) => item)))
}

function normalizePlanIdentifiers(value) {
  const ids = Array.isArray(value) ? value : []
  return Array.from(new Set(ids.map((item) => String(item || '').trim()).filter((item) => item)))
}

function getPlanRowId(row) {
  if (!row || typeof row !== 'object') return ''
  const candidate = row.id
  if (candidate === undefined || candidate === null) return ''
  return String(candidate).trim()
}

function getPlanName(row) {
  if (!row || typeof row !== 'object') return ''
  const candidate = row.name ?? row.schedule_name
  return String(candidate || '').trim()
}

function normalizePlanDraftRows(value) {
  const list = Array.isArray(value) ? clone(value) : []
  const rows = []
  const invalidRows = []

  list.forEach((plan) => {
    if (!plan || typeof plan !== 'object') {
      invalidRows.push(clone(plan))
      return
    }
    const nextPlan = { ...plan }
    const name = getPlanName(nextPlan)
    if (!name) {
      invalidRows.push(nextPlan)
      return
    }
    nextPlan.name = name
    delete nextPlan.schedule_name
    if (typeof nextPlan.originName === 'string') {
      nextPlan.originName = nextPlan.originName.trim()
    }
    rows.push(nextPlan)
  })

  return {
    rows,
    invalidRows
  }
}

function buildPlanDraftIssues(report) {
  const issues = []
  const invalidPlans = Number(report?.invalidPlans || 0)
  const invalidBasePlans = Number(report?.invalidBasePlans || 0)
  const droppedDirtyIds = Number(report?.droppedDirtyIds || 0)
  const droppedDeletedIds = Number(report?.droppedDeletedIds || 0)

  if (invalidPlans) {
    issues.push({
      type: 'invalid-plan-drafts',
      scope: 'plans',
      count: invalidPlans
    })
  }
  if (invalidBasePlans) {
    issues.push({
      type: 'invalid-plan-base-snapshot',
      scope: 'planBaseSnapshot',
      count: invalidBasePlans
    })
  }
  if (droppedDirtyIds) {
    issues.push({
      type: 'dropped-plan-dirty-ids',
      scope: 'planDirtyIds',
      count: droppedDirtyIds
    })
  }
  if (droppedDeletedIds) {
    issues.push({
      type: 'dropped-plan-deleted-ids',
      scope: 'planDeletedIds',
      count: droppedDeletedIds
    })
  }
  return issues
}

function normalizePlanDraftState(drafts) {
  const planState = normalizePlanDraftRows(drafts?.plans)
  const baseSnapshotState = normalizePlanDraftRows(drafts?.planBaseSnapshot)
  const explicitInvalidPlans = Array.isArray(drafts?.invalidPlanDrafts) ? clone(drafts.invalidPlanDrafts) : []
  const explicitInvalidBasePlans = Array.isArray(drafts?.invalidPlanBaseSnapshot) ? clone(drafts.invalidPlanBaseSnapshot) : []
  const invalidPlanDrafts = [...explicitInvalidPlans, ...planState.invalidRows]
  const invalidPlanBaseSnapshot = [...explicitInvalidBasePlans, ...baseSnapshotState.invalidRows]
  const validIds = new Set([
    ...planState.rows.map((plan) => getPlanRowId(plan)),
    ...baseSnapshotState.rows.map((plan) => getPlanRowId(plan))
  ].filter((item) => item))
  const originalDirtyIds = normalizePlanIdentifiers(drafts?.planDirtyIds)
  const originalDeletedIds = normalizePlanIdentifiers(drafts?.planDeletedIds)
  const planDirtyIds = originalDirtyIds.filter((id) => validIds.has(id))
  const planDeletedIds = originalDeletedIds.filter((id) => validIds.has(id))
  const report = {
    invalidPlans: invalidPlanDrafts.length,
    invalidBasePlans: invalidPlanBaseSnapshot.length,
    droppedDirtyIds: originalDirtyIds.length - planDirtyIds.length,
    droppedDeletedIds: originalDeletedIds.length - planDeletedIds.length,
    totalInvalidPlans: invalidPlanDrafts.length + invalidPlanBaseSnapshot.length
  }

  return {
    plans: planState.rows,
    planBaseSnapshot: baseSnapshotState.rows,
    planDirtyIds,
    planDeletedIds,
    invalidPlanDrafts,
    invalidPlanBaseSnapshot,
    planDraftIssues: buildPlanDraftIssues(report),
    report
  }
}

function mergePlanRowsById(existingRows, appendedRows, options = {}) {
  const { dirtyIds = [] } = options
  const baseRows = normalizePlanDraftRows(existingRows).rows
  const nextRows = clone(baseRows)
  const rowMap = new Map(nextRows.map((plan) => [getPlanRowId(plan), plan]))
  const appended = normalizePlanDraftRows(appendedRows).rows
  const recoveredDirtyIds = []

  appended.forEach((plan) => {
    const rowId = getPlanRowId(plan)
    if (!rowId) return
    const nextPlan = clone(plan)
    if (rowMap.has(rowId)) {
      const index = nextRows.findIndex((item) => getPlanRowId(item) === rowId)
      if (index >= 0) {
        nextRows.splice(index, 1, nextPlan)
      }
    } else {
      nextRows.push(nextPlan)
    }
    rowMap.set(rowId, nextPlan)
    recoveredDirtyIds.push(rowId)
  })

  return {
    rows: nextRows,
    dirtyIds: normalizePlanIdentifiers([...(Array.isArray(dirtyIds) ? dirtyIds : []), ...recoveredDirtyIds])
  }
}

function buildPlanMap(rows) {
  const map = new Map()
  normalizePlanDraftRows(rows).rows.forEach((plan) => {
    const rowId = getPlanRowId(plan)
    if (!rowId) return
    map.set(rowId, plan)
  })
  return map
}

export function diffPlanDraft(baseSnapshot, currentPlans, dirtyIds, deletedIds) {
  const baseRows = normalizePlanDraftRows(baseSnapshot).rows
  const currentRows = normalizePlanDraftRows(currentPlans).rows
  const dirtyIdList = normalizePlanIdentifiers(dirtyIds)
  const deletedIdList = normalizePlanIdentifiers(deletedIds)
  const dirtyIdSet = new Set(dirtyIdList)
  const deletedIdSet = new Set(deletedIdList)
  const baseMap = buildPlanMap(baseRows)
  const currentMap = buildPlanMap(currentRows)
  const added = []
  const updated = []
  const removed = []
  const unchanged = []

  dirtyIdList.forEach((planId) => {
    if (deletedIdSet.has(planId)) return
    if (!currentMap.has(planId) && !baseMap.has(planId)) {
      throw new Error(`瀛樺湪鏃犳硶瑙ｆ瀽鐨勪綔鎭崏绋挎爣璇嗭細${planId}`)
    }
    if (!currentMap.has(planId) && baseMap.has(planId)) {
      throw new Error(`浣滄伅鏂规 ${planId} 褰撳墠鏈嚭鐜板湪缂栬緫鍒楄〃涓紝宸查樆姝㈤殣寮忓垹闄?`)
    }
  })

  deletedIdList.forEach((planId) => {
    if (!currentMap.has(planId) && !baseMap.has(planId)) {
      throw new Error(`瀛樺湪鏃犳硶瑙ｆ瀽鐨勫垹闄ゆ爣璇嗭細${planId}`)
    }
  })

  baseRows.forEach((plan) => {
    const rowId = getPlanRowId(plan)
    if (!rowId) return
    if (deletedIdSet.has(rowId)) {
      removed.push(plan)
      return
    }
    if (dirtyIdSet.has(rowId)) {
      const currentPlan = currentMap.get(rowId)
      if (!currentPlan) {
        throw new Error(`浣滄伅鏂规 ${rowId} 缂哄皯鏄惧紡鍒犻櫎鏍囪锛屼笉鍏佽鎸夌己澶卞嵆鍒犻櫎澶勭悊`)
      }
      updated.push(currentPlan)
      return
    }
    unchanged.push(plan)
  })

  currentRows.forEach((plan) => {
    const rowId = getPlanRowId(plan)
    if (!rowId || baseMap.has(rowId) || deletedIdSet.has(rowId)) return
    if (!dirtyIdSet.has(rowId)) {
      throw new Error(`鏂板缓浣滄伅鏂规 ${rowId} 鏈鏍囪涓哄彉鏇达紝宸查樆姝㈠紓甯镐笂浼?`)
    }
    added.push(plan)
  })

  return {
    added,
    updated,
    removed,
    unchanged
  }
}

function normalizeBroadcastDirtyIds(value) {
  const ids = Array.isArray(value) ? value : []
  return Array.from(new Set(ids.map((item) => String(item || '').trim()).filter((item) => item)))
}

function normalizeBroadcastSnapshot(value) {
  return Array.isArray(value) ? clone(value) : []
}

function areBroadcastSnapshotsEqual(left, right) {
  return JSON.stringify(normalizeBroadcastSnapshot(left)) === JSON.stringify(normalizeBroadcastSnapshot(right))
}

function getBroadcastRowId(row) {
  if (!row || typeof row !== 'object') return ''
  const candidates = [
    row.id,
    row.taskid,
    row.task_id,
    row.broadcastDraftId,
    row.broadcast_draft_id
  ]
  for (const candidate of candidates) {
    if (candidate === undefined || candidate === null) continue
    const text = String(candidate).trim()
    if (text) return text
  }
  return ''
}

function buildBroadcastRowMap(rows) {
  const map = new Map()
  normalizeBroadcastSnapshot(rows).forEach((row) => {
    const rowId = getBroadcastRowId(row)
    if (!rowId) return
    map.set(rowId, row)
  })
  return map
}

function calculateBroadcastDraftMeta(broadcasts, broadcastBaseSnapshot) {
  const currentRows = normalizeBroadcastSnapshot(broadcasts)
  const baseRows = normalizeBroadcastSnapshot(broadcastBaseSnapshot)
  const hasComparableBase = Array.isArray(broadcastBaseSnapshot)

  if (!hasComparableBase) {
    const broadcastDirtyIds = currentRows
      .map((row) => getBroadcastRowId(row))
      .filter((item) => item)
    return {
      broadcastDirtyIds: normalizeBroadcastDirtyIds(broadcastDirtyIds),
      broadcastDeletedIds: [],
      hasBroadcastDiff: currentRows.length > 0
    }
  }

  const currentMap = buildBroadcastRowMap(currentRows)
  const baseMap = buildBroadcastRowMap(baseRows)
  const broadcastDirtyIds = []
  const broadcastDeletedIds = []

  currentMap.forEach((row, rowId) => {
    const baseRow = baseMap.get(rowId)
    if (!baseRow || JSON.stringify(row) !== JSON.stringify(baseRow)) {
      broadcastDirtyIds.push(rowId)
    }
  })

  baseMap.forEach((row, rowId) => {
    if (!currentMap.has(rowId)) {
      broadcastDeletedIds.push(rowId)
    }
  })

  const hasBroadcastDiff = broadcastDirtyIds.length > 0 || broadcastDeletedIds.length > 0 || !areBroadcastSnapshotsEqual(currentRows, baseRows)
  return {
    broadcastDirtyIds: normalizeBroadcastDirtyIds(broadcastDirtyIds),
    broadcastDeletedIds: normalizeBroadcastDirtyIds(broadcastDeletedIds),
    hasBroadcastDiff
  }
}

function inferDirtyScopes(drafts) {
  const scopes = normalizeDirtyScopes(drafts?.dirtyScopes)
  const hasPlanDiff = (
    (Array.isArray(drafts?.plans) && drafts.plans.length > 0) ||
    (Array.isArray(drafts?.planDirtyIds) && drafts.planDirtyIds.length > 0) ||
    (Array.isArray(drafts?.planDeletedIds) && drafts.planDeletedIds.length > 0) ||
    (Array.isArray(drafts?.invalidPlanDrafts) && drafts.invalidPlanDrafts.length > 0) ||
    (Array.isArray(drafts?.invalidPlanBaseSnapshot) && drafts.invalidPlanBaseSnapshot.length > 0)
  )
  if (hasPlanDiff && !scopes.includes('plans')) {
    scopes.push('plans')
  }

  const {
    broadcastDirtyIds,
    broadcastDeletedIds,
    hasBroadcastDiff
  } = calculateBroadcastDraftMeta(drafts?.broadcasts, drafts?.broadcastBaseSnapshot)
  const hasBroadcastDirtyRows = broadcastDirtyIds.length > 0 || broadcastDeletedIds.length > 0
  if (hasBroadcastDiff) {
    if (!scopes.includes('broadcasts')) scopes.push('broadcasts')
  } else if (hasBroadcastDirtyRows && !scopes.includes('broadcasts')) {
    scopes.push('broadcasts')
  }
  return scopes
}

function isEmptyDraftPayload(payload) {
  return !payload.plans.length &&
    !payload.planDirtyIds.length &&
    !payload.planDeletedIds.length &&
    !payload.planBaseSnapshot.length &&
    !payload.invalidPlanDrafts.length &&
    !payload.invalidPlanBaseSnapshot.length &&
    !payload.broadcasts.length &&
    !payload.broadcastBaseSnapshot.length &&
    !payload.dirtyScopes.length
}

export function getDefaultSchedulerData() {
  return clone(defaultData)
}

export function getDefaultSchedulerDrafts() {
  return clone(defaultDrafts)
}

export function loadSchedulerData() {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    if (!raw) return getDefaultSchedulerData()
    const parsed = JSON.parse(raw)
    return {
      ...getDefaultSchedulerData(),
      ...parsed
    }
  } catch (e) {
    console.warn('loadSchedulerData failed, fallback to default', e)
    return getDefaultSchedulerData()
  }
}

export function saveSchedulerData(data) {
  localStorage.setItem(STORAGE_KEY, JSON.stringify(data))
}

export function loadSchedulerDrafts() {
  try {
    const raw = localStorage.getItem(DRAFT_STORAGE_KEY)
    if (!raw) return getDefaultSchedulerDrafts()
    const parsed = JSON.parse(raw)
    const normalizedPlanState = normalizePlanDraftState(parsed)
    const broadcasts = normalizeBroadcastSnapshot(parsed?.broadcasts)
    const broadcastBaseSnapshot = normalizeBroadcastSnapshot(parsed?.broadcastBaseSnapshot)
    const {
      broadcastDirtyIds,
      broadcastDeletedIds
    } = calculateBroadcastDraftMeta(broadcasts, parsed?.broadcastBaseSnapshot)
    const normalized = {
      ...getDefaultSchedulerDrafts(),
      ...parsed,
      plans: normalizedPlanState.plans,
      planDirtyIds: normalizedPlanState.planDirtyIds,
      planDeletedIds: normalizedPlanState.planDeletedIds,
      planBaseSnapshot: normalizedPlanState.planBaseSnapshot,
      invalidPlanDrafts: normalizedPlanState.invalidPlanDrafts,
      invalidPlanBaseSnapshot: normalizedPlanState.invalidPlanBaseSnapshot,
      planDraftIssues: normalizedPlanState.planDraftIssues,
      broadcasts,
      broadcastDirtyIds,
      broadcastDeletedIds,
      broadcastBaseSnapshot
    }
    const dirtyScopes = inferDirtyScopes(normalized)
    return {
      ...normalized,
      dirtyScopes,
      updatedAt: dirtyScopes.length
        ? (parsed?.updatedAt ? String(parsed.updatedAt) : new Date().toISOString())
        : '',
      planSanitizeReport: normalizedPlanState.report
    }
  } catch (e) {
    console.warn('loadSchedulerDrafts failed, fallback to default', e)
    return getDefaultSchedulerDrafts()
  }
}

export function saveSchedulerDrafts(drafts) {
  const normalizedPlanState = normalizePlanDraftState(drafts)
  const broadcasts = Array.isArray(drafts?.broadcasts) ? normalizeBroadcastSnapshot(drafts.broadcasts) : []
  const broadcastBaseSnapshot = Array.isArray(drafts?.broadcastBaseSnapshot)
    ? normalizeBroadcastSnapshot(drafts.broadcastBaseSnapshot)
    : []
  const {
    broadcastDirtyIds,
    broadcastDeletedIds
  } = calculateBroadcastDraftMeta(broadcasts, drafts?.broadcastBaseSnapshot)
  const normalized = {
    ...getDefaultSchedulerDrafts(),
    ...(drafts || {}),
    plans: normalizedPlanState.plans,
    planDirtyIds: normalizedPlanState.planDirtyIds,
    planDeletedIds: normalizedPlanState.planDeletedIds,
    planBaseSnapshot: normalizedPlanState.planBaseSnapshot,
    invalidPlanDrafts: normalizedPlanState.invalidPlanDrafts,
    invalidPlanBaseSnapshot: normalizedPlanState.invalidPlanBaseSnapshot,
    planDraftIssues: normalizedPlanState.planDraftIssues,
    broadcasts,
    broadcastDirtyIds,
    broadcastDeletedIds,
    broadcastBaseSnapshot
  }
  const dirtyScopes = inferDirtyScopes(normalized)
  const payload = {
    ...normalized,
    dirtyScopes,
    updatedAt: dirtyScopes.length
      ? (drafts?.updatedAt ? String(drafts.updatedAt) : new Date().toISOString())
      : ''
  }
  const result = {
    ...payload,
    planSanitizeReport: normalizedPlanState.report
  }

  if (isEmptyDraftPayload(payload)) {
    localStorage.removeItem(DRAFT_STORAGE_KEY)
    return result
  }

  localStorage.setItem(DRAFT_STORAGE_KEY, JSON.stringify(payload))
  return result
}

export function savePlanDraft(plans, planDirtyIds, planBaseSnapshot, options = {}) {
  const current = loadSchedulerDrafts()
  const next = {
    ...current,
    plans: Array.isArray(plans) ? clone(plans) : [],
    planDirtyIds: normalizePlanIdentifiers(planDirtyIds),
    planDeletedIds: normalizePlanIdentifiers(
      options.planDeletedIds !== undefined ? options.planDeletedIds : current.planDeletedIds
    ),
    planBaseSnapshot: Array.isArray(planBaseSnapshot) ? clone(planBaseSnapshot) : [],
    invalidPlanDrafts: Array.isArray(options.invalidPlanDrafts) ? clone(options.invalidPlanDrafts) : clone(current.invalidPlanDrafts),
    invalidPlanBaseSnapshot: Array.isArray(options.invalidPlanBaseSnapshot) ? clone(options.invalidPlanBaseSnapshot) : clone(current.invalidPlanBaseSnapshot),
    dirtyScopes: normalizeDirtyScopes([...(current.dirtyScopes || []), 'plans']),
    updatedAt: new Date().toISOString()
  }
  return saveSchedulerDrafts(next)
}

export function recoverInvalidPlanDrafts() {
  const current = loadSchedulerDrafts()
  const recoveredPlans = normalizePlanDraftRows(current.invalidPlanDrafts)
  const recoveredBaseSnapshot = normalizePlanDraftRows(current.invalidPlanBaseSnapshot)
  const mergedPlans = mergePlanRowsById(current.plans, recoveredPlans.rows, {
    dirtyIds: current.planDirtyIds
  })
  const mergedBaseSnapshot = mergePlanRowsById(current.planBaseSnapshot, recoveredBaseSnapshot.rows)
  return saveSchedulerDrafts({
    ...current,
    plans: mergedPlans.rows,
    planDirtyIds: mergedPlans.dirtyIds,
    planBaseSnapshot: mergedBaseSnapshot.rows,
    invalidPlanDrafts: recoveredPlans.invalidRows,
    invalidPlanBaseSnapshot: recoveredBaseSnapshot.invalidRows,
    updatedAt: new Date().toISOString()
  })
}

export function discardInvalidPlanDrafts() {
  const current = loadSchedulerDrafts()
  return saveSchedulerDrafts({
    ...current,
    invalidPlanDrafts: [],
    invalidPlanBaseSnapshot: [],
    updatedAt: new Date().toISOString()
  })
}

export function clearPlanDraft() {
  const current = loadSchedulerDrafts()
  const nextScopes = normalizeDirtyScopes((current.dirtyScopes || []).filter((scope) => scope !== 'plans'))
  const next = {
    ...current,
    plans: [],
    planDirtyIds: [],
    planDeletedIds: [],
    planBaseSnapshot: [],
    invalidPlanDrafts: [],
    invalidPlanBaseSnapshot: [],
    planDraftIssues: [],
    dirtyScopes: nextScopes,
    updatedAt: nextScopes.length ? current.updatedAt : ''
  }
  return saveSchedulerDrafts(next)
}

export function saveBroadcastDraft(broadcasts, broadcastBaseSnapshot = null) {
  const current = loadSchedulerDrafts()
  const nextBroadcasts = normalizeBroadcastSnapshot(broadcasts)
  const nextBroadcastBaseSnapshot = Array.isArray(broadcastBaseSnapshot)
    ? normalizeBroadcastSnapshot(broadcastBaseSnapshot)
    : normalizeBroadcastSnapshot(current?.broadcastBaseSnapshot)
  const {
    hasBroadcastDiff
  } = calculateBroadcastDraftMeta(nextBroadcasts, Array.isArray(broadcastBaseSnapshot) ? nextBroadcastBaseSnapshot : current?.broadcastBaseSnapshot)
  const nextScopes = hasBroadcastDiff
    ? normalizeDirtyScopes([...(current.dirtyScopes || []), 'broadcasts'])
    : normalizeDirtyScopes((current.dirtyScopes || []).filter((scope) => scope !== 'broadcasts'))
  const next = {
    ...current,
    broadcasts: hasBroadcastDiff ? nextBroadcasts : [],
    broadcastBaseSnapshot: hasBroadcastDiff ? nextBroadcastBaseSnapshot : [],
    dirtyScopes: nextScopes,
    updatedAt: nextScopes.length ? new Date().toISOString() : ''
  }
  return saveSchedulerDrafts(next)
}

export function clearBroadcastDraft() {
  const current = loadSchedulerDrafts()
  const nextScopes = normalizeDirtyScopes((current.dirtyScopes || []).filter((scope) => scope !== 'broadcasts'))
  const next = {
    ...current,
    broadcasts: [],
    broadcastDirtyIds: [],
    broadcastDeletedIds: [],
    broadcastBaseSnapshot: [],
    dirtyScopes: nextScopes,
    updatedAt: nextScopes.length ? current.updatedAt : ''
  }
  return saveSchedulerDrafts(next)
}

export function hasSchedulerDirtyScope(scope, drafts = null) {
  const payload = drafts || loadSchedulerDrafts()
  const normalizedScope = String(scope || '').trim()
  if (normalizedScope === 'plans') {
    const dirtyIds = normalizePlanIdentifiers(payload?.planDirtyIds)
    const deletedIds = normalizePlanIdentifiers(payload?.planDeletedIds)
    const invalidPlans = Array.isArray(payload?.invalidPlanDrafts) ? payload.invalidPlanDrafts.length : 0
    const invalidBasePlans = Array.isArray(payload?.invalidPlanBaseSnapshot) ? payload.invalidPlanBaseSnapshot.length : 0
    if (dirtyIds.length || deletedIds.length || invalidPlans || invalidBasePlans) return true
  }
  if (normalizedScope === 'broadcasts') {
    const dirtyIds = normalizeBroadcastDirtyIds(payload?.broadcastDirtyIds)
    const deletedIds = normalizeBroadcastDirtyIds(payload?.broadcastDeletedIds)
    if (dirtyIds.length || deletedIds.length) return true
  }
  return normalizeDirtyScopes(payload?.dirtyScopes).includes(normalizedScope)
}
