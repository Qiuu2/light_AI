import { shallowMount } from '@vue/test-utils'
import TaskSchedulerPage from '@/views/task-scheduler/index.vue'
import {
  activateLightSchedule,
  fetchCurrentLightScheduleTasks,
  fetchLightResources,
  fetchLightSchedules
} from '@/api/lightService'

jest.mock('@/api/lightService', () => ({
  activateLightSchedule: jest.fn(),
  createLightScheduleTask: jest.fn(),
  deleteLightTask: jest.fn(),
  fetchCurrentLightScheduleTasks: jest.fn(),
  fetchLightResources: jest.fn(),
  fetchLightSchedules: jest.fn(),
  fetchLightTaskDetails: jest.fn(),
  updateLightTask: jest.fn()
}))

const passThroughStub = {
  template: '<div><slot /><slot name="header" /></div>'
}

const inertStub = {
  template: '<div />'
}

const flushPromises = async(count = 8) => {
  for (let index = 0; index < count; index += 1) {
    await Promise.resolve()
  }
}

function lightSchedules(rows = []) {
  return {
    success: true,
    data: {
      schemes: rows
    }
  }
}

function resources(currentScheme = '1') {
  return {
    success: true,
    data: {
      media: [],
      terminal: [],
      basic: {
        rows: [{ Current_Scheme: currentScheme }]
      }
    },
    parts: {
      basic: { success: true, message: 'ok' }
    }
  }
}

function currentTasks(rows = []) {
  return {
    success: true,
    data: {
      tasks: rows
    }
  }
}

function createWrapper() {
  return shallowMount(TaskSchedulerPage, {
    stubs: {
      'el-alert': passThroughStub,
      'el-button': passThroughStub,
      'el-card': passThroughStub,
      'el-empty': passThroughStub,
      'el-table': inertStub,
      'el-table-column': inertStub,
      'el-tag': passThroughStub,
      'el-dialog': passThroughStub,
      'el-form': passThroughStub,
      'el-row': passThroughStub,
      'el-col': passThroughStub,
      'el-form-item': passThroughStub,
      'el-input': passThroughStub,
      'el-select': passThroughStub,
      'el-option': passThroughStub,
      'el-time-picker': passThroughStub,
      'el-checkbox-group': passThroughStub,
      'el-checkbox': passThroughStub
    },
    mocks: {
      $message: {
        error: jest.fn(),
        success: jest.fn(),
        warning: jest.fn()
      },
      $confirm: jest.fn()
    },
    directives: {
      loading: {}
    }
  })
}

describe('TaskSchedulerPage light schedule state', () => {
  beforeEach(() => {
    jest.clearAllMocks()
    fetchLightSchedules.mockResolvedValue(lightSchedules([]))
    fetchCurrentLightScheduleTasks.mockResolvedValue(currentTasks([]))
    fetchLightResources.mockResolvedValue(resources('1'))
    activateLightSchedule.mockResolvedValue({ success: true, message: 'ok' })
  })

  it('keeps current tasks visible when the schedule catalog fails', async() => {
    fetchLightSchedules.mockResolvedValue({ success: false, message: '目录失败' })
    fetchCurrentLightScheduleTasks.mockResolvedValue(currentTasks([{ id: 122, taskname: '333' }]))

    const wrapper = createWrapper()
    await flushPromises()
    await wrapper.vm.$nextTick()

    expect(wrapper.vm.schedulesError).toBe('目录失败')
    expect(wrapper.vm.currentTasksError).toBe('')
    expect(wrapper.vm.currentTaskRows).toEqual([{ id: 122, taskname: '333' }])
  })

  it('distinguishes current-task failures from empty current tasks', async() => {
    fetchCurrentLightScheduleTasks.mockResolvedValue({ success: false, message: '当前任务加载失败' })

    const wrapper = createWrapper()
    await flushPromises()
    await wrapper.vm.$nextTick()

    expect(wrapper.vm.currentTasksPayload).toBeNull()
    expect(wrapper.vm.currentTasksError).toBe('当前任务加载失败')
    expect(wrapper.vm.currentTaskRows).toEqual([])
  })

  it('marks scheme detail failures instead of treating them as zero tasks', async() => {
    fetchLightSchedules.mockResolvedValue(lightSchedules([
      { id: '3', name: '方案3', tasks: [], task_error: 'opensech failed', task_success: false }
    ]))

    const wrapper = createWrapper()
    await flushPromises()
    await wrapper.vm.$nextTick()

    expect(wrapper.vm.selectedSchemeTaskError).toContain('opensech failed')
    expect(wrapper.vm.schemeTaskSummary(wrapper.vm.selectedScheme)).toBe('任务详情加载失败')
  })

  it('keeps a sync notice when activate succeeded but Current_Scheme has not converged yet', async() => {
    fetchLightSchedules.mockResolvedValue(lightSchedules([
      { id: '1', name: '方案1', tasks: [] },
      { id: '2', name: '方案2', tasks: [] }
    ]))
    fetchLightResources.mockResolvedValue(resources('1'))

    const wrapper = createWrapper()
    await flushPromises()
    await wrapper.vm.$nextTick()

    await wrapper.vm.activateScheme({ id: '2', name: '方案2' })
    await flushPromises()
    await wrapper.vm.$nextTick()

    expect(activateLightSchedule).toHaveBeenCalledWith('2')
    expect(wrapper.vm.scheduleSyncMessage).toBe('切换请求已提交，远端状态同步中')
  })
})
