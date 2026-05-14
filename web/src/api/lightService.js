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

export async function fetchLightResources() {
  const { data } = await api.get('/api/light/resources')
  return data
}

export async function fetchLightSchedules() {
  const { data } = await api.get('/api/light/schedules')
  return data
}

export async function fetchCurrentLightScheduleTasks() {
  const { data } = await api.get('/api/light/current-schedule-tasks')
  return data
}

export async function createLightScheduleTask(programId, payload) {
  const { data } = await api.post(`/api/light/schedules/${encodeURIComponent(programId)}/tasks`, payload)
  return data
}

export async function activateLightSchedule(programId) {
  const { data } = await api.post(`/api/light/schedules/${encodeURIComponent(programId)}/activate`)
  return data
}

export async function updateLightTask(taskId, payload) {
  const { data } = await api.put(`/api/light/tasks/${encodeURIComponent(taskId)}`, payload)
  return data
}

export async function fetchLightTaskDetails(taskId) {
  const { data } = await api.get(`/api/light/tasks/${encodeURIComponent(taskId)}/details`)
  return data
}

export async function deleteLightTask(taskId) {
  const { data } = await api.delete(`/api/light/tasks/${encodeURIComponent(taskId)}`)
  return data
}

export async function fetchLightTasks() {
  const { data } = await api.get('/api/light/tasks')
  return data
}

export async function executeLightTask(taskId) {
  const { data } = await api.post(`/api/light/tasks/${encodeURIComponent(taskId)}/execute`)
  return data
}

export async function stopLightTask(taskId) {
  const { data } = await api.post(`/api/light/tasks/${encodeURIComponent(taskId)}/stop`)
  return data
}

export async function startInstantPlay(payload) {
  const { data } = await api.post('/api/light/instant-play', payload)
  return data
}

export async function stopInstantPlay() {
  const { data } = await api.post('/api/light/instant-play/stop')
  return data
}
