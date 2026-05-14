jest.mock('axios', () => ({
  create: jest.fn(() => ({
    interceptors: {
      request: { use: jest.fn() },
      response: { use: jest.fn() }
    }
  }))
}))

jest.mock('@/store', () => ({
  __esModule: true,
  default: {
    getters: {}
  }
}))

jest.mock('@/utils/auth', () => ({
  getToken: jest.fn()
}))

jest.mock('element-ui', () => ({
  MessageBox: {
    confirm: jest.fn()
  },
  Message: jest.fn()
}))

import { mapHttpErrorToUserMessage } from '@/utils/httpError'

describe('httpError mapping', () => {
  it('maps assistant chat 401 errors to a re-login prompt', () => {
    const message = mapHttpErrorToUserMessage(
      {
        response: {
          status: 401,
          data: {
            detail: 'Login required.'
          }
        },
        config: {
          url: '/assistant/chat'
        }
      },
      {
        scene: 'assistant_chat',
        fallbackText: '助手调用失败，请检查后端接口'
      }
    )

    expect(message).toBe('助手暂时无法使用，请重新登录后再试。')
  })

  it('maps auth session 401 errors to a redirect prompt', () => {
    const message = mapHttpErrorToUserMessage(
      {
        response: {
          status: 401,
          data: {
            detail: 'Login required.'
          }
        },
        config: {
          url: '/auth/session'
        }
      },
      {
        scene: 'auth_session',
        fallbackText: '登录状态校验失败，请重新登录'
      }
    )

    expect(message).toBe('登录状态已失效，正在跳转登录页。')
  })

  it('keeps non-401 errors readable with status, path, and detail', () => {
    const message = mapHttpErrorToUserMessage(
      {
        response: {
          status: 422,
          data: {
            detail: 'Invalid payload'
          }
        },
        config: {
          url: '/data/assistant_settings'
        }
      },
      {
        scene: 'assistant_settings',
        fallbackText: '作息模板配置保存失败，请检查后端接口'
      }
    )

    expect(message).toContain('HTTP 422')
    expect(message).toContain('/data/assistant_settings')
    expect(message).toContain('Invalid payload')
  })
})
