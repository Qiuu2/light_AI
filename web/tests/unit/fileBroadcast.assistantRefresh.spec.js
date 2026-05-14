jest.mock('@/api/dataService', () => ({
  fetchBroadcasts: jest.fn()
}))

import { shallowMount } from '@vue/test-utils'
import FileBroadcast from '@/views/file-broadcast/index.vue'
import { fetchBroadcasts } from '@/api/dataService'
import { __resetAssistantRefreshBus, emitAssistantRefresh } from '@/utils/assistantRefreshBus'

const flushPromises = () => new Promise((resolve) => setTimeout(resolve, 0))

describe('FileBroadcast assistant refresh bus', () => {
  beforeEach(() => {
    jest.clearAllMocks()
    __resetAssistantRefreshBus()
  })

  afterEach(() => {
    __resetAssistantRefreshBus()
  })

  it('reloads silently when assistant refresh is emitted', async() => {
    fetchBroadcasts.mockResolvedValue({ broadcasts: [] })

    const wrapper = shallowMount(FileBroadcast, {
      stubs: ['el-button', 'el-table', 'el-table-column', 'el-tag'],
      mocks: {
        $message: {
          success: jest.fn(),
          error: jest.fn()
        }
      }
    })

    await flushPromises()
    const loadSpy = jest.spyOn(wrapper.vm, 'loadData')

    emitAssistantRefresh({ reason: 'auth_backend_sync' })
    await flushPromises()

    expect(loadSpy).toHaveBeenCalledWith(true)

    loadSpy.mockRestore()
    wrapper.destroy()
  })
})
