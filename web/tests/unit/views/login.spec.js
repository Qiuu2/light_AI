import { shallowMount } from '@vue/test-utils'
import LoginView from '@/views/login/index.vue'

const REMOTE_BASE_URL_STORAGE_KEY = 'AI_SPEAKER_REMOTE_BASE_URL'

const passThroughStub = {
  template: '<div><slot /></div>'
}

const formStub = {
  template: '<form><slot /></form>'
}

const buttonStub = {
  template: '<button><slot /></button>'
}

const flushPromises = async(count = 4) => {
  for (let index = 0; index < count; index += 1) {
    await Promise.resolve()
  }
}

function createWrapper({
  routeQuery,
  dispatch = jest.fn(() => Promise.resolve())
} = {}) {
  const routerReplace = jest.fn()
  const wrapper = shallowMount(LoginView, {
    stubs: {
      'el-alert': passThroughStub,
      'el-form': formStub,
      'el-input': passThroughStub,
      'el-button': buttonStub
    },
    mocks: {
      $route: {
        query: routeQuery || {}
      },
      $router: {
        replace: routerReplace
      },
      $store: {
        dispatch
      }
    }
  })

  return { wrapper, dispatch, routerReplace }
}

describe('LoginView', () => {
  beforeEach(() => {
    jest.clearAllMocks()
    localStorage.clear()
    window.history.replaceState({}, '', 'http://localhost/login')
  })

  it('shows the explicit remote base url field and leaves it empty by default', async() => {
    const { wrapper } = createWrapper()

    await flushPromises()
    await wrapper.vm.$nextTick()

    expect(wrapper.find('label[for="login-remote-base-url"]').exists()).toBe(true)
    expect(wrapper.vm.form.remoteBaseUrl).toBe('')
    expect(wrapper.vm.remoteBaseUrlLocked).toBe(false)
  })

  it('prefills remote_base_url from the URL when provided explicitly', async() => {
    const { wrapper } = createWrapper({
      routeQuery: {
        remote_base_url: 'http://192.168.3.199'
      }
    })

    await flushPromises()
    await wrapper.vm.$nextTick()

    expect(wrapper.vm.form.remoteBaseUrl).toBe('http://192.168.3.199')
    expect(wrapper.vm.remoteBaseUrlLocked).toBe(false)
  })

  it('prefills and locks the saved remote base url when no explicit URL is provided', async() => {
    localStorage.setItem(REMOTE_BASE_URL_STORAGE_KEY, 'http://192.168.3.199')
    const { wrapper } = createWrapper()

    await flushPromises()
    await wrapper.vm.$nextTick()

    expect(wrapper.vm.form.remoteBaseUrl).toBe('http://192.168.3.199')
    expect(wrapper.vm.remoteBaseUrlLocked).toBe(true)
  })

  it('ignores token parameters when initializing the remote base url', async() => {
    const { wrapper } = createWrapper({
      routeQuery: {
        token: 'legacy-token'
      }
    })

    await flushPromises()
    await wrapper.vm.$nextTick()

    expect(wrapper.vm.form.remoteBaseUrl).toBe('')
  })

  it('lets the user unlock and cancel editing the saved remote base url', async() => {
    localStorage.setItem(REMOTE_BASE_URL_STORAGE_KEY, 'http://192.168.3.199')
    const { wrapper } = createWrapper()

    await flushPromises()
    await wrapper.vm.$nextTick()

    wrapper.vm.toggleRemoteBaseUrlEdit()
    expect(wrapper.vm.remoteBaseUrlLocked).toBe(false)

    wrapper.vm.form.remoteBaseUrl = 'http://192.168.3.200'
    wrapper.vm.toggleRemoteBaseUrlEdit()

    expect(wrapper.vm.form.remoteBaseUrl).toBe('http://192.168.3.199')
    expect(wrapper.vm.remoteBaseUrlLocked).toBe(true)
  })

  it('submits username, password and remote_base_url through the login action', async() => {
    const dispatch = jest.fn(() => Promise.resolve())
    const { wrapper, routerReplace } = createWrapper({
      routeQuery: {
        redirect: '/scheduler',
        remote_base_url: 'http://192.168.3.199'
      },
      dispatch
    })

    await flushPromises()
    await wrapper.vm.$nextTick()

    wrapper.vm.form.username = 'useradmin'
    wrapper.vm.form.password = '123456'

    await wrapper.vm.handleLogin()

    expect(dispatch).toHaveBeenCalledWith('user/login', expect.objectContaining({
      username: 'useradmin',
      password: '123456',
      remoteBaseUrl: 'http://192.168.3.199'
    }))
    expect(localStorage.getItem(REMOTE_BASE_URL_STORAGE_KEY)).toBe('http://192.168.3.199')
    expect(routerReplace).toHaveBeenCalledWith('/scheduler')
  })

  it('rejects missing remote base url before dispatching login', async() => {
    const dispatch = jest.fn()
    const { wrapper } = createWrapper({ dispatch })

    await flushPromises()
    await wrapper.vm.$nextTick()

    wrapper.vm.form.username = 'useradmin'
    wrapper.vm.form.password = '123456'

    await wrapper.vm.handleLogin()

    expect(dispatch).not.toHaveBeenCalled()
    expect(wrapper.vm.errorMessage).toBe('请输入远端地址')
  })
})
