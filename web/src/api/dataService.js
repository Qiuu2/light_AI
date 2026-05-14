import axios from 'axios'
import { getToken } from '@/utils/auth'

const api = axios.create({
  baseURL: process.env.VUE_APP_BASE_API || '',
  timeout: 30000
})

api.interceptors.request.use((config) => {
  const token = getToken()
  if (token) {
    config.headers = config.headers || {}
    config.headers['X-Token'] = token
  }
  return config
})

export async function fetchAllAudio() {
  const { data } = await api.get('/data/all_audio')
  return data
}

export async function fetchAllLoc() {
  const { data } = await api.get('/data/all_loc')
  return data
}

export async function fetchAllTask() {
  const { data } = await api.get('/data/all_task')
  return data
}

export async function fetchBroadcastSchedules() {
  const { data } = await api.get('/data/broadcast_schedules')
  return data
}

export async function fetchBroadcastSchedulesSummary() {
  const { data } = await api.get('/data/broadcast_schedules', { params: { light: 1 }})
  return data
}

export async function fetchBroadcasts() {
  const { data } = await api.get('/data/broadcast_schedules/broadcasts')
  return data
}

export async function fetchLivecasts() {
  const { data } = await api.get('/data/broadcast_schedules/livecasts')
  return data
}

export async function fetchRuntimePlayTasks(force = false) {
  const params = force ? { force: true } : undefined
  const { data } = await api.get('/data/runtime_play_tasks', { params })
  return data
}

export async function stopRuntimePlayTasks(taskIds) {
  const normalized = Array.isArray(taskIds) ? taskIds : [taskIds]
  const payload = {
    task_ids: normalized.map((item) => String(item || '').trim()).filter(Boolean)
  }
  const { data } = await api.post('/data/runtime_play_tasks/stop', payload)
  return data
}

export async function setTaskStatus(payload) {
  const { data } = await api.post('/data/task_state', payload)
  return data
}

export async function setScheduleStatus(payload) {
  const { data } = await api.post('/data/schedule_state', payload, { timeout: 120000 })
  return data
}

export async function fetchScheduleTasks(scheduleName) {
  const { data } = await api.get(`/data/broadcast_schedules/schedules/${encodeURIComponent(scheduleName)}/tasks`)
  return data
}

export async function fetchTaskOverrides() {
  const { data } = await api.get('/data/task_overrides')
  return data
}

export async function updateOnceOverrideTask(overrideId, onceTaskId, payload) {
  const { data } = await api.put(
    `/data/task_overrides/once/${encodeURIComponent(overrideId)}/tasks/${encodeURIComponent(onceTaskId)}`,
    payload,
    { timeout: 120000 }
  )
  return data
}

export async function deleteOnceOverrideTask(overrideId, onceTaskId) {
  const { data } = await api.delete(
    `/data/task_overrides/once/${encodeURIComponent(overrideId)}/tasks/${encodeURIComponent(onceTaskId)}`,
    { timeout: 120000 }
  )
  return data
}

export async function fetchCalendarHolidays(year) {
  const { data } = await api.get('/data/calendar_holidays', { params: { year }})
  return data
}

export async function updateBroadcastSchedules(payload) {
  const { data } = await api.put('/data/broadcast_schedules', payload, { timeout: 120000 })
  return data
}

export async function createScheduleEntry(payload) {
  const { data } = await api.post('/data/broadcast_schedules/schedules', payload, { timeout: 120000 })
  return data
}

export async function updateScheduleEntry(scheduleName, payload) {
  const { data } = await api.put(
    `/data/broadcast_schedules/schedules/${encodeURIComponent(scheduleName)}`,
    payload,
    { timeout: 120000 }
  )
  return data
}

export async function deleteScheduleEntry(scheduleName) {
  const { data } = await api.delete(
    `/data/broadcast_schedules/schedules/${encodeURIComponent(scheduleName)}`,
    { timeout: 120000 }
  )
  return data
}

export async function updateAllTask(payload, scope) {
  const params = scope ? { scope } : undefined
  const { data } = await api.put('/data/all_task', payload, { params, timeout: 120000 })
  return data
}

export async function reloadAssets() {
  const { data } = await api.post('/admin/reload')
  return data
}

export async function syncBackendData() {
  const { data } = await api.post('/admin/sync_data')
  return data
}

export async function fetchTerminalInfo() {
  const { data } = await api.get('/api/light/terminals')
  return data
}

export async function fetchTerminalZones() {
  const { data } = await api.get('/api/light/terminal-groups')
  return data
}

export async function fetchTerminalsByZone(zoneId) {
  const { data } = await api.get(`/api/light/terminal-groups/${encodeURIComponent(zoneId)}/terminals`)
  return data
}

export async function fetchAllTerminalData(force = false) {
  const params = force ? { force: true } : {}
  const { data } = await api.get('/api/light/terminal-snapshot', { params })
  return data
}

function unsupportedTerminalWrite(message) {
  const error = new Error(message)
  error.response = { data: { detail: message }}
  return Promise.reject(error)
}

export async function setSystemVolume(volume) {
  const { data } = await api.post('/api/light/system-volume', { volume })
  return data
}

export async function moveTerminalZone() {
  return unsupportedTerminalWrite('当前 light 终端分组移动未开放：远端 action 映射尚未确认。')
}
