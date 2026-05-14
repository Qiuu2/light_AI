const flushPromises = async(count = 4) => {
  for (let index = 0; index < count; index += 1) {
    await Promise.resolve()
  }
}

const createDeferred = () => {
  let resolve
  let reject
  const promise = new Promise((res, rej) => {
    resolve = res
    reject = rej
  })
  return { promise, resolve, reject }
}

function loadPermissionModule({
  token = 'session-token',
  syncImpl,
  dispatchImpl
} = {}) {
  jest.resetModules()
  window.sessionStorage.clear()

  const beforeEach = jest.fn()
  const afterEach = jest.fn()
  const dispatch = jest.fn(dispatchImpl || ((type) => {
    if (type === 'user/getInfo' || type === 'user/resetToken') {
      return Promise.resolve({})
    }
    return Promise.resolve({})
  }))
  const getToken = jest.fn(() => token)
  const syncBackendData = jest.fn(syncImpl || (() => Promise.resolve({ status: 'ok' })))
  const emitAssistantRefresh = jest.fn()
  const start = jest.fn()
  const done = jest.fn()
  const messageError = jest.fn()

  jest.doMock('@/router', () => ({
    __esModule: true,
    default: {
      beforeEach,
      afterEach
    }
  }))
  jest.doMock('@/store', () => ({
    __esModule: true,
    default: {
      dispatch
    }
  }))
  jest.doMock('@/utils/auth', () => ({
    getToken
  }))
  jest.doMock('@/api/dataService', () => ({
    syncBackendData
  }))
  jest.doMock('@/utils/assistantRefreshBus', () => ({
    emitAssistantRefresh
  }))
  jest.doMock('element-ui', () => ({
    Message: {
      error: messageError
    }
  }))
  jest.doMock('nprogress', () => ({
    __esModule: true,
    default: {
      configure: jest.fn(),
      start,
      done
    }
  }))
  jest.doMock('nprogress/nprogress.css', () => ({}))
  jest.doMock('@/utils/get-page-title', () => ({
    __esModule: true,
    default: jest.fn(() => 'page-title')
  }))

  require('@/permission')
  const guard = beforeEach.mock.calls[0][0]

  return {
    guard,
    mocks: {
      dispatch,
      getToken,
      syncBackendData,
      emitAssistantRefresh,
      start,
      done,
      messageError
    }
  }
}

describe('permission auth backend sync', () => {
  afterEach(() => {
    jest.resetModules()
    jest.clearAllMocks()
    window.sessionStorage.clear()
  })

  it('does not block navigation while auth backend sync is pending', async() => {
    const deferred = createDeferred()
    const { guard, mocks } = loadPermissionModule({
      syncImpl: () => deferred.promise
    })
    const next = jest.fn()

    await guard({ path: '/device-status', fullPath: '/device-status', meta: {} }, {}, next)

    expect(mocks.syncBackendData).toHaveBeenCalledTimes(1)
    expect(next).toHaveBeenCalledWith()
    expect(window.sessionStorage.getItem('ai-speaker:auth-backend-sync:v1:session-token')).toBe('pending')

    deferred.resolve({ status: 'ok' })
    await flushPromises()

    expect(mocks.emitAssistantRefresh).toHaveBeenCalledWith(
      expect.objectContaining({ reason: 'auth_backend_sync' })
    )
    expect(window.sessionStorage.getItem('ai-speaker:auth-backend-sync:v1:session-token')).toBe('done')
  })

  it('does not start duplicate sync requests for the same session token', async() => {
    const deferred = createDeferred()
    const { guard, mocks } = loadPermissionModule({
      syncImpl: () => deferred.promise
    })
    const next = jest.fn()

    await guard({ path: '/device-status', fullPath: '/device-status', meta: {} }, {}, next)
    await guard({ path: '/tasks/index', fullPath: '/tasks/index', meta: {} }, {}, next)

    expect(mocks.syncBackendData).toHaveBeenCalledTimes(1)

    deferred.resolve({ status: 'ok' })
    await flushPromises()
  })

  it('clears pending sync state after a failure so later navigation can retry', async() => {
    const secondAttempt = createDeferred()
    const syncBackendData = jest.fn()
      .mockRejectedValueOnce(new Error('sync failed'))
      .mockImplementationOnce(() => secondAttempt.promise)
    const { guard } = loadPermissionModule({
      syncImpl: (...args) => syncBackendData(...args)
    })
    const next = jest.fn()

    await guard({ path: '/device-status', fullPath: '/device-status', meta: {} }, {}, next)
    await flushPromises()

    expect(window.sessionStorage.getItem('ai-speaker:auth-backend-sync:v1:session-token')).toBe(null)

    await guard({ path: '/plans/index', fullPath: '/plans/index', meta: {} }, {}, next)

    expect(syncBackendData).toHaveBeenCalledTimes(2)
    expect(window.sessionStorage.getItem('ai-speaker:auth-backend-sync:v1:session-token')).toBe('pending')

    secondAttempt.resolve({ status: 'ok' })
    await flushPromises()
  })

  it('shows a user-friendly auth session 401 message before redirecting', async() => {
    const authError = {
      response: {
        status: 401,
        data: {
          detail: 'Login required.'
        }
      },
      config: {
        url: '/auth/session'
      }
    }
    const { guard, mocks } = loadPermissionModule({
      dispatchImpl: (type) => {
        if (type === 'user/getInfo') {
          return Promise.reject(authError)
        }
        if (type === 'user/resetToken') {
          return Promise.resolve({})
        }
        return Promise.resolve({})
      }
    })
    const next = jest.fn()

    await guard({ path: '/device-status', fullPath: '/device-status', meta: {} }, {}, next)

    expect(mocks.messageError).toHaveBeenCalledWith('登录状态已失效，正在跳转登录页。')
    expect(next).toHaveBeenCalledWith('/login?redirect=%2Fdevice-status')
  })
})
