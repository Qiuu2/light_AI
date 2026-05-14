jest.mock('@/api/user', () => ({
  getInfo: jest.fn(),
  login: jest.fn(() => Promise.resolve({
    data: {
      token: 'local-session-token',
      name: 'Local User',
      avatar: ''
    }
  })),
  logout: jest.fn()
}))

jest.mock('@/utils/auth', () => ({
  getToken: jest.fn(() => ''),
  setToken: jest.fn(),
  removeToken: jest.fn()
}))

jest.mock('@/router', () => ({
  resetRouter: jest.fn()
}))

import userModule from '@/store/modules/user'
import { login as loginApi } from '@/api/user'

describe('user store login', () => {
  it('forwards remote_base_url to /auth/login', async() => {
    const commit = jest.fn()

    await userModule.actions.login({ commit }, {
      username: 'admin',
      password: '123456',
      remoteBaseUrl: 'http://192.168.1.158:99/api'
    })

    expect(loginApi).toHaveBeenCalledWith({
      username: 'admin',
      password: '123456',
      remote_base_url: 'http://192.168.1.158:99/api'
    })
  })
})
