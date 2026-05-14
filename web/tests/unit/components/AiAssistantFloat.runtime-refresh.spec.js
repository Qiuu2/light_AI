import { shallowMount } from '@vue/test-utils'
import AiAssistantFloat from '@/components/AiAssistantFloat.vue'
import axios from 'axios'
import { emitAssistantRefresh } from '@/utils/assistantRefreshBus'

jest.mock('axios', () => {
  const mockApi = {
    get: jest.fn(),
    put: jest.fn(),
    post: jest.fn(),
    interceptors: {
      request: {
        use: jest.fn()
      }
    }
  }
  return {
    get: jest.fn(),
    create: jest.fn(() => mockApi),
    __mockApi: mockApi
  }
})

jest.mock('@/utils/assistantRefreshBus', () => ({
  emitAssistantRefresh: jest.fn(),
  onAssistantRefresh: jest.fn(),
  offAssistantRefresh: jest.fn()
}))

const elementStubs = [
  'el-button',
  'el-tooltip',
  'el-drawer',
  'el-input',
  'el-tabs',
  'el-tab-pane',
  'el-collapse',
  'el-collapse-item',
  'el-popover',
  'el-select',
  'el-option',
  'el-tag',
  'el-input-number',
  'el-date-picker',
  'el-radio-group',
  'el-radio-button'
]

function createWrapper(rootOverrides = {}) {
  return shallowMount(AiAssistantFloat, {
    stubs: elementStubs,
    mocks: {
      $message: { warning: jest.fn(), error: jest.fn(), success: jest.fn() },
      $notify: jest.fn(),
      $root: {
        $emit: jest.fn(),
        $on: jest.fn(),
        $off: jest.fn(),
        ...rootOverrides
      }
    }
  })
}

describe('AiAssistantFloat runtime refresh', () => {
  afterEach(() => {
    emitAssistantRefresh.mockClear()
    axios.get.mockReset()
    axios.__mockApi.get.mockReset()
    axios.__mockApi.put.mockReset()
    axios.__mockApi.post.mockReset()
  })

  it('invalidates only playMedia options after play_media refresh', () => {
    const wrapper = createWrapper()

    wrapper.setData({
      slotOptions: {
        terminal: [],
        zone: [],
        schedule: [],
        media: [{ label: 'media-a', value: 'media-a' }],
        playMedia: [{ label: 'play-a', value: 'play-a' }],
        broadcastTask: [],
        target: []
      }
    })

    wrapper.vm.handleAssistantRefresh({
      runtime_scope: 'temp_task',
      action_log: [{ action: 'play_media', details: { runtime_scope: 'temp_task' }}]
    })

    expect(wrapper.vm.slotOptions.media).toEqual([{ label: 'media-a', value: 'media-a' }])
    expect(wrapper.vm.slotOptions.playMedia).toEqual([])
  })

  it('invalidates all assistant slot caches and refetches when auth sync completes with manual drawer open', () => {
    const wrapper = createWrapper()
    const refreshSpy = jest.spyOn(wrapper.vm, 'refreshManualSlotOptions').mockImplementation(() => {})

    wrapper.setData({
      manualDrawer: true,
      slotOptions: {
        terminal: [{ label: 'T1', value: 'T1' }],
        zone: [{ label: 'Z1', value: 'Z1' }],
        schedule: [{ label: 'S1', value: 'S1' }],
        media: [{ label: 'M1', value: 'M1' }],
        playMedia: [{ label: 'PM1', value: 'PM1' }],
        broadcastTask: [{ label: 'B1', value: 'B1' }],
        target: [{ label: 'Target1', value: 'Target1' }]
      },
      taskOptionsBySchedule: {
        S1: [{ label: 'Task1', value: 'Task1' }]
      },
      taskLoadingBySchedule: {
        S1: true
      }
    })

    wrapper.vm.handleAssistantRefresh({ reason: 'auth_backend_sync' })

    expect(wrapper.vm.slotOptions).toEqual({
      terminal: [],
      zone: [],
      schedule: [],
      media: [],
      playMedia: [],
      broadcastTask: [],
      target: []
    })
    expect(wrapper.vm.taskOptionsBySchedule).toEqual({})
    expect(wrapper.vm.taskLoadingBySchedule).toEqual({})
    expect(refreshSpy).toHaveBeenCalledWith({ force: true })

    refreshSpy.mockRestore()
  })

  it('invalidates assistant slot caches without refetch when auth sync completes with manual drawer closed', () => {
    const wrapper = createWrapper()
    const refreshSpy = jest.spyOn(wrapper.vm, 'refreshManualSlotOptions').mockImplementation(() => {})

    wrapper.setData({
      manualDrawer: false,
      slotOptions: {
        terminal: [{ label: 'T1', value: 'T1' }],
        zone: [{ label: 'Z1', value: 'Z1' }],
        schedule: [{ label: 'S1', value: 'S1' }],
        media: [{ label: 'M1', value: 'M1' }],
        playMedia: [{ label: 'PM1', value: 'PM1' }],
        broadcastTask: [{ label: 'B1', value: 'B1' }],
        target: [{ label: 'Target1', value: 'Target1' }]
      },
      taskOptionsBySchedule: {
        S1: [{ label: 'Task1', value: 'Task1' }]
      },
      taskLoadingBySchedule: {
        S1: true
      }
    })

    wrapper.vm.handleAssistantRefresh({ reason: 'auth_backend_sync' })

    expect(wrapper.vm.slotOptions).toEqual({
      terminal: [],
      zone: [],
      schedule: [],
      media: [],
      playMedia: [],
      broadcastTask: [],
      target: []
    })
    expect(wrapper.vm.taskOptionsBySchedule).toEqual({})
    expect(wrapper.vm.taskLoadingBySchedule).toEqual({})
    expect(refreshSpy).not.toHaveBeenCalled()

    refreshSpy.mockRestore()
  })

  it('emits runtime_scope for play_media assistant refresh payloads', async() => {
    const wrapper = createWrapper()
    const fetchLogsSpy = jest.spyOn(wrapper.vm, 'fetchAssistantLogs').mockImplementation(() => Promise.resolve())

    axios.__mockApi.post.mockResolvedValue({
      data: {
        reply: 'started',
        output_speech: 'started',
        intent: 'play_media',
        confidence: 1,
        slots: { media_name: 'bell' },
        missing_slots: [],
        diagnostics: [],
        action_log: [
          {
            action: 'play_media',
            mode: 'runtime',
            task_ids: ['998'],
            details: {
              runtime_scope: 'temp_task',
              media_name: 'bell'
            }
          }
        ]
      }
    })
    axios.__mockApi.get.mockResolvedValue({ data: { schedules: [] }})

    await wrapper.vm.submitAssistantText('play bell')
    await wrapper.vm.$nextTick()

    expect(emitAssistantRefresh).toHaveBeenCalledWith(
      expect.objectContaining({
        intent: 'play_media',
        runtime_scope: 'temp_task'
      })
    )

    fetchLogsSpy.mockRestore()
  })

  it('emits assistant refresh for enable_terminal even when action_log is empty', async() => {
    const wrapper = createWrapper()

    axios.__mockApi.post.mockResolvedValue({
      data: {
        reply: '已成功启用右二终端。',
        output_speech: '已成功启用右二终端。',
        intent: 'enable_terminal',
        confidence: 1,
        slots: { terminal_name: '右二终端' },
        missing_slots: [],
        dialog_state_detail: 'complete',
        diagnostics: [],
        action_log: []
      }
    })
    axios.__mockApi.get.mockResolvedValue({ data: { schedules: [] }})

    await wrapper.vm.submitAssistantText('启用右二终端')
    await wrapper.vm.$nextTick()

    expect(emitAssistantRefresh).toHaveBeenCalledWith(expect.objectContaining({
      intent: 'enable_terminal',
      action_log: []
    }))
  })

  it('emits assistant refresh for disable_terminal when dialog is complete', async() => {
    const wrapper = createWrapper()

    axios.__mockApi.post.mockResolvedValue({
      data: {
        reply: '已成功停用右二终端。',
        output_speech: '已成功停用右二终端。',
        intent: 'disable_terminal',
        confidence: 1,
        slots: { terminal_name: '右二终端' },
        missing_slots: [],
        dialog_state_detail: 'complete',
        diagnostics: [],
        action_log: []
      }
    })
    axios.__mockApi.get.mockResolvedValue({ data: { schedules: [] }})

    await wrapper.vm.submitAssistantText('停用右二终端')
    await wrapper.vm.$nextTick()

    expect(emitAssistantRefresh).toHaveBeenCalledWith(expect.objectContaining({
      intent: 'disable_terminal',
      action_log: []
    }))
  })
})
