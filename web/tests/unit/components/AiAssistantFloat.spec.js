import { shallowMount } from '@vue/test-utils'
import AiAssistantFloat from '@/components/AiAssistantFloat.vue'
import axios from 'axios'

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

function createWrapper() {
  return shallowMount(AiAssistantFloat, {
    stubs: elementStubs,
    mocks: {
      $message: { warning: jest.fn(), error: jest.fn(), success: jest.fn() },
      $notify: jest.fn(),
      $root: { $emit: jest.fn(), $on: jest.fn(), $off: jest.fn() }
    }
  })
}

const flushPromises = () => new Promise((resolve) => setTimeout(resolve, 0))

describe('AiAssistantFloat diagnostics', () => {
  const originalDiagEnv = process.env.VUE_APP_AI_DIAGNOSTICS
  const originalNodeEnv = process.env.NODE_ENV

  afterEach(() => {
    process.env.VUE_APP_AI_DIAGNOSTICS = originalDiagEnv
    process.env.NODE_ENV = originalNodeEnv
    axios.get.mockReset()
    axios.__mockApi.get.mockReset()
    axios.__mockApi.put.mockReset()
    axios.__mockApi.post.mockReset()
  })

  it('renders inline diagnostics when diagnostics mode is enabled', async () => {
    process.env.VUE_APP_AI_DIAGNOSTICS = '1'
    const wrapper = createWrapper()

    wrapper.vm.pushMessage('ai', '一次性操作未完整生效', {
      diagnostics: [
        {
          diagnostic_id: 'diag-1',
          phase: 'disable',
          path: '/task/enabletask',
          status_code: 200,
          elapsed_ms: 12.5,
          ok: true,
          timeout: false,
          response_body: { message: 'disable-ok' }
        },
        {
          diagnostic_id: 'diag-1',
          phase: 'restore',
          path: '/task/enabletask',
          status_code: 504,
          elapsed_ms: 15000,
          ok: false,
          timeout: true,
          request_payload: { taskid: '1,2' },
          response_body: { message: 'restore-timeout' },
          error_detail: 'Remote request timed out after 15.0s: POST /task/enabletask'
        }
      ]
    })
    await wrapper.vm.$nextTick()

    expect(wrapper.text()).toContain('查看远端诊断')
    expect(wrapper.text()).toContain('restore')
    expect(wrapper.text()).toContain('/task/enabletask')
    expect(wrapper.text()).toContain('失败 timeout')
    expect(wrapper.text()).toContain('"taskid": "1,2"')
    expect(wrapper.text()).toContain('restore-timeout')
    expect(wrapper.text()).not.toContain('disable-ok')
  })

  it('hides diagnostics when diagnostics mode is disabled', async () => {
    process.env.VUE_APP_AI_DIAGNOSTICS = '0'
    const wrapper = createWrapper()

    wrapper.vm.pushMessage('ai', '测试回复', {
      diagnostics: [
        {
          diagnostic_id: 'diag-2',
          phase: 'restore',
          path: '/task/enabletask',
          status_code: 504,
          elapsed_ms: 15000,
          ok: false,
          timeout: true,
          request_payload: { taskid: '1,2' },
          response_body: { message: 'restore-timeout' },
          error_detail: 'Remote request timed out after 15.0s: POST /task/enabletask'
        }
      ]
    })
    await wrapper.vm.$nextTick()

    expect(wrapper.vm.conversation).toHaveLength(1)
    expect(wrapper.vm.conversation[0].text).toBe('测试回复')
    expect(wrapper.text()).not.toContain('查看远端诊断')
  })

  it('does not render diagnostics block when the message has no diagnostics', async () => {
    process.env.VUE_APP_AI_DIAGNOSTICS = '1'
    const wrapper = createWrapper()

    wrapper.vm.pushMessage('ai', '普通回复', { intent: 'cancel_schedule' })
    await wrapper.vm.$nextTick()

    expect(wrapper.vm.conversation).toHaveLength(1)
    expect(wrapper.vm.conversation[0].text).toBe('普通回复')
    expect(wrapper.text()).not.toContain('查看远端诊断')
  })

  it('does not create an extra detail bubble for query action logs', async () => {
    const wrapper = createWrapper()
    const fetchLogsSpy = jest.spyOn(wrapper.vm, 'fetchAssistantLogs').mockImplementation(() => Promise.resolve())

    axios.__mockApi.post.mockResolvedValue({
      data: {
        reply: '已查询终端状态:共 1 个,在线 0 个,离线 1 个,未知 0 个。',
        output_speech: '已查询终端状态:共 1 个,在线 0 个,离线 1 个,未知 0 个。',
        intent: 'query_terminal',
        confidence: 1,
        missing_slots: [],
        diagnostics: [],
        action_log: [
          {
            action: 'query_terminal',
            mode: 'query',
            schedule_name: '',
            task_ids: [],
            details: { count: 1 }
          }
        ]
      }
    })

    await wrapper.vm.submitAssistantText('帮我看看右二终端的状态')
    await wrapper.vm.$nextTick()

    expect(axios.__mockApi.post).toHaveBeenCalledWith('/assistant/chat', { text: '帮我看看右二终端的状态' })
    expect(fetchLogsSpy).toHaveBeenCalled()
    expect(wrapper.vm.conversation).toHaveLength(2)
    expect(wrapper.vm.conversation[1].text).toBe('已查询终端状态:共 1 个,在线 0 个,离线 1 个,未知 0 个。')
    expect(wrapper.vm.conversation.map((item) => item.text).join('\n')).not.toContain('排程:')

    fetchLogsSpy.mockRestore()
  })

  it('does not create an extra detail bubble for non-query action logs', async () => {
    const wrapper = createWrapper()
    const fetchLogsSpy = jest.spyOn(wrapper.vm, 'fetchAssistantLogs').mockImplementation(() => Promise.resolve())

    axios.__mockApi.post.mockResolvedValue({
      data: {
        reply: '已创建作息。',
        output_speech: '已创建作息。',
        intent: 'create_schedule',
        confidence: 1,
        missing_slots: [],
        diagnostics: [],
        action_log: [
          {
            action: 'set_task',
            mode: 'runtime',
            schedule_name: '夏季作息',
            task_ids: ['101'],
            time_range: {
              start: '08:00',
              end: '08:30'
            },
            details: {
              status: '已创建'
            }
          }
        ]
      }
    })

    await wrapper.vm.submitAssistantText('创建夏季作息')
    await wrapper.vm.$nextTick()

    expect(fetchLogsSpy).toHaveBeenCalled()
    expect(wrapper.vm.conversation).toHaveLength(2)
    expect(wrapper.vm.conversation[1].text).toBe('已创建作息。')
    expect(wrapper.vm.conversation.map((item) => item.text).join('\n')).not.toContain('排程:')
    expect(wrapper.vm.conversation.map((item) => item.text).join('\n')).not.toContain('任务ID:')
    expect(wrapper.vm.conversation.map((item) => item.text).join('\n')).not.toContain('时间:')

    fetchLogsSpy.mockRestore()
  })

  it('fills playback media duration template with seconds and volume text', () => {
    const wrapper = createWrapper()
    const playbackModule = wrapper.vm.manualModules.find((module) => module.id === 'playback')
    const item = playbackModule.items.find((entry) => entry.id === 'playback-media')

    wrapper.vm.setManualVariant(item, 'duration')
    wrapper.vm.setSlotValue(item, '区域', '高一楼')
    wrapper.vm.setSlotValue(item, '媒体', '眼保健操')
    wrapper.vm.setSlotValue(item, '秒数', '30')
    wrapper.vm.setSlotValue(item, '数值', '40')
    wrapper.vm.fillFromTemplate(item)

    expect(wrapper.vm.command).toBe('给高一楼播放眼保健操，播放30秒，音量40')
  })

  it('fills playback media loop template with count and volume text', () => {
    const wrapper = createWrapper()
    const playbackModule = wrapper.vm.manualModules.find((module) => module.id === 'playback')
    const item = playbackModule.items.find((entry) => entry.id === 'playback-media')

    wrapper.vm.setManualVariant(item, 'loop')
    wrapper.vm.setSlotValue(item, '区域', '高一楼')
    wrapper.vm.setSlotValue(item, '媒体', '上课铃')
    wrapper.vm.setSlotValue(item, '次数', '3')
    wrapper.vm.setSlotValue(item, '数值', '40')
    wrapper.vm.fillFromTemplate(item)

    expect(wrapper.vm.command).toBe('给高一楼播放上课铃，播放3次，音量40')
  })

  it('maps 5xx request errors to the provided fallback text', () => {
    const wrapper = createWrapper()

    const message = wrapper.vm.formatRequestErrorMessage(
      {
        response: {
          status: 502,
          data: {
            detail: 'Bad Gateway'
          }
        }
      },
      '/prod-api/data/assistant_command_logs',
      '成功日志加载失败，请检查后端接口'
    )

    expect(message).toBe('成功日志加载失败，请检查后端接口')
    expect(message).not.toContain('HTTP 502')
    expect(message).not.toContain('/prod-api/data/assistant_command_logs')
    expect(message).not.toContain('Bad Gateway')
  })

  it('applies kind and season options returned by assistant settings API', async() => {
    axios.__mockApi.get.mockResolvedValue({
      data: {
        default_schedule_kind: '大学',
        default_schedule_season: '冬季',
        allowed_schedule_kinds: ['小学', '中学', '高中', '大学'],
        allowed_schedule_seasons: ['夏季', '冬季']
      }
    })

    const wrapper = createWrapper()
    await flushPromises()

    expect(wrapper.vm.defaultScheduleKind).toBe('大学')
    expect(wrapper.vm.defaultScheduleSeason).toBe('冬季')
    expect(wrapper.vm.allowedScheduleKinds).toEqual(['小学', '中学', '高中', '大学'])
    expect(wrapper.vm.allowedScheduleSeasons).toEqual(['夏季', '冬季'])
    expect(wrapper.vm.hasScheduleTemplateSelection).toBe(true)
    expect(wrapper.vm.scheduleTemplateSelectionLabel).toBe('大学 / 冬季')
  })

  it('saves kind and season together when season changes', async() => {
    axios.__mockApi.get.mockResolvedValue({ data: {} })
    axios.__mockApi.put.mockResolvedValue({
      data: {
        default_schedule_kind: '大学',
        default_schedule_season: '冬季',
        allowed_schedule_kinds: ['小学', '中学', '高中', '大学'],
        allowed_schedule_seasons: ['夏季', '冬季']
      }
    })

    const wrapper = createWrapper()
    await flushPromises()
    await wrapper.setData({
      defaultScheduleKind: '大学',
      defaultScheduleSeason: '夏季'
    })

    await wrapper.vm.handleScheduleSeasonChange('冬季')

    expect(axios.__mockApi.put).toHaveBeenCalledWith('/data/assistant_settings', {
      default_schedule_kind: '大学',
      default_schedule_season: '冬季'
    })
    expect(wrapper.vm.defaultScheduleKind).toBe('大学')
    expect(wrapper.vm.defaultScheduleSeason).toBe('冬季')
    expect(wrapper.vm.scheduleTemplateSelectionLabel).toBe('大学 / 冬季')
  })

  it('maps assistant 502 failures to a friendly retry message', async () => {
    const wrapper = createWrapper()

    axios.__mockApi.post.mockRejectedValue({
      response: {
        status: 502,
        data: {
          detail: 'Bad Gateway'
        }
      }
    })

    await wrapper.vm.submitAssistantText('查看今天下午的任务')
    await wrapper.vm.$nextTick()

    expect(wrapper.vm.conversation).toHaveLength(2)
    expect(wrapper.vm.conversation[1].text).toBe('当前网络不稳定，请重新发送。')
    expect(wrapper.vm.conversation[1].text).not.toContain('HTTP 502')
    expect(wrapper.vm.conversation[1].text).not.toContain('Bad Gateway')
  })

  it('maps assistant 401 failures to a friendly re-login message', async () => {
    const wrapper = createWrapper()

    axios.__mockApi.post.mockRejectedValue({
      response: {
        status: 401,
        data: {
          detail: 'Login required.'
        }
      },
      config: {
        url: '/assistant/chat'
      }
    })

    await wrapper.vm.submitAssistantText('查看今天下午的任务')
    await wrapper.vm.$nextTick()

    expect(wrapper.vm.conversation).toHaveLength(2)
    expect(wrapper.vm.conversation[1].text).toBe('助手暂时无法使用，请重新登录后再试。')
    expect(wrapper.vm.conversation[1].text).not.toContain('HTTP 401')
    expect(wrapper.vm.conversation[1].text).not.toContain('Login required.')
  })

  it('invalidates manual slot caches after schedule and zone changes', () => {
    const wrapper = createWrapper()
    axios.get.mockClear()

    wrapper.setData({
      slotOptions: {
        terminal: [{ label: 'terminal-a', value: 'terminal-a' }],
        zone: [{ label: 'zone-a', value: 'zone-a' }],
        schedule: [{ label: 'schedule-a', value: 'schedule-a' }],
        media: [{ label: 'media-a', value: 'media-a' }],
        target: [{ label: 'zone-a', value: 'zone-a' }]
      }
    })

    wrapper.vm.handleAssistantRefresh({
      intent: 'create_zone',
      action_log: [{ action: 'create_schedule' }]
    })

    expect(wrapper.vm.slotOptions.schedule).toEqual([])
    expect(wrapper.vm.slotOptions.zone).toEqual([])
    expect(wrapper.vm.slotOptions.target).toEqual([])
    expect(wrapper.vm.slotOptions.terminal).toEqual([{ label: 'terminal-a', value: 'terminal-a' }])
    expect(wrapper.vm.slotOptions.media).toEqual([{ label: 'media-a', value: 'media-a' }])
    expect(axios.get).not.toHaveBeenCalled()
  })

  it('forces slot option refresh whenever the manual drawer opens', () => {
    const wrapper = createWrapper()
    const ensureSpy = jest.spyOn(wrapper.vm, 'ensureSlotOptions').mockImplementation(() => {})
    const tipSpy = jest.spyOn(wrapper.vm, 'startTipTimer').mockImplementation(() => {})

    wrapper.vm.handleManualOpen()

    expect(ensureSpy).toHaveBeenCalledWith('terminal', { force: true })
    expect(ensureSpy).toHaveBeenCalledWith('zone', { force: true })
    expect(ensureSpy).toHaveBeenCalledWith('schedule', { force: true })
    expect(ensureSpy).toHaveBeenCalledWith('media', { force: true })

    ensureSpy.mockRestore()
    tipSpy.mockRestore()
  })

  it('keeps pending choice descriptions when normalizing pending actions', () => {
    const wrapper = createWrapper()

    const normalized = wrapper.vm.normalizePendingAction({
      choices: [
        {
          label: '升旗仪式',
          value: '11',
          description: '08:30 / 夏季作息 / id=11'
        }
      ]
    })

    expect(normalized).not.toBeNull()
    expect(normalized.choices).toHaveLength(1)
    expect(normalized.choices[0].label).toBe('升旗仪式')
    expect(normalized.choices[0].value).toBe('11')
    expect(normalized.choices[0].description).toBe('08:30 / 夏季作息 / id=11')
  })

  it('renders pending choice labels together with descriptions', async () => {
    const wrapper = createWrapper()

    wrapper.vm.pushMessage('ai', '请选择具体任务', {
      pending_action: {
        choices: [
          {
            label: '升旗仪式',
            value: '11',
            description: '08:30 / 夏季作息 / id=11'
          },
          {
            label: '升旗仪式',
            value: '12',
            description: '09:30 / 夏季作息 / id=12'
          }
        ]
      }
    })
    await wrapper.vm.$nextTick()

    expect(wrapper.vm.conversation).toHaveLength(1)
    const choices = wrapper.vm.getPendingChoices(wrapper.vm.conversation[0].meta)
    expect(choices).toHaveLength(2)
    expect(choices[0].label).toBe('升旗仪式')
    expect(choices[0].description).toBe('08:30 / 夏季作息 / id=11')
    expect(choices[1].description).toBe('09:30 / 夏季作息 / id=12')
  })
})
