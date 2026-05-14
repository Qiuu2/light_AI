jest.mock('element-ui', () => ({
  Message: {
    error: jest.fn()
  }
}))

jest.mock('nprogress', () => ({
  configure: jest.fn(),
  start: jest.fn(),
  done: jest.fn()
}))

jest.mock('nprogress/nprogress.css', () => ({}))

jest.mock('@/router', () => ({
  beforeEach: jest.fn(),
  afterEach: jest.fn()
}))

jest.mock('@/store', () => ({
  dispatch: jest.fn(() => Promise.resolve())
}))

jest.mock('@/utils/auth', () => ({
  getToken: jest.fn(() => '')
}))

jest.mock('@/utils/get-page-title', () => jest.fn(() => 'Test Page'))

import { inferRemoteBaseUrlFromLocation } from '@/permission'

describe('permission remote base url helper', () => {
  it('infers remote_base_url from the current host and configured port/path', () => {
    expect(inferRemoteBaseUrlFromLocation(
      { protocol: 'http:', hostname: '192.168.1.158' },
      { remoteApiPort: '99', remoteApiPath: '/api' }
    )).toBe('http://192.168.1.158:99/api')
  })

  it('returns an empty string when protocol or hostname is missing', () => {
    expect(inferRemoteBaseUrlFromLocation({ protocol: '', hostname: '192.168.1.158' })).toBe('')
    expect(inferRemoteBaseUrlFromLocation({ protocol: 'http:', hostname: '' })).toBe('')
  })
})
