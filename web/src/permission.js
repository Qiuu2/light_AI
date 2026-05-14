import { Message } from 'element-ui'
import NProgress from 'nprogress'
import 'nprogress/nprogress.css'

import router from './router'
import store from './store'
import { getToken } from '@/utils/auth'
import { syncBackendData } from '@/api/dataService'
import { emitAssistantRefresh } from '@/utils/assistantRefreshBus'
import { isAuthSessionUnauthorized, mapHttpErrorToUserMessage } from '@/utils/httpError'
import getPageTitle from '@/utils/get-page-title'

NProgress.configure({ showSpinner: false })

const whiteList = ['/login', '/404']
const AUTH_BACKEND_SYNC_SESSION_KEY_PREFIX = 'ai-speaker:auth-backend-sync:v1:'

function loginRedirect(fullPath) {
  return `/login?redirect=${encodeURIComponent(fullPath || '/')}`
}

function getAuthBackendSyncSessionKey(token) {
  const normalizedToken = String(token || '').trim()
  if (!normalizedToken) return ''
  return `${AUTH_BACKEND_SYNC_SESSION_KEY_PREFIX}${normalizedToken}`
}

export function inferRemoteBaseUrlFromLocation(locationLike = window.location, settings = {}) {
  const protocol = String(locationLike?.protocol || '').trim()
  const hostname = String(locationLike?.hostname || '').trim()
  const port = String(settings?.remoteApiPort || '').trim()
  const path = String(settings?.remoteApiPath || '').trim()
  if (!protocol || !hostname) return ''
  const normalizedPath = path ? (path.startsWith('/') ? path : `/${path}`) : ''
  return `${protocol}//${hostname}${port ? `:${port}` : ''}${normalizedPath}`
}

function startAuthBackendSync(token) {
  if (typeof window === 'undefined' || !window.sessionStorage) return
  const sessionKey = getAuthBackendSyncSessionKey(token)
  if (!sessionKey) return
  const status = window.sessionStorage.getItem(sessionKey)
  if (status === 'done' || status === 'pending') return
  window.sessionStorage.setItem(sessionKey, 'pending')
  syncBackendData()
    .then(() => {
      window.sessionStorage.setItem(sessionKey, 'done')
      emitAssistantRefresh({
        reason: 'auth_backend_sync'
      })
    })
    .catch((error) => {
      window.sessionStorage.removeItem(sessionKey)
      if (typeof console !== 'undefined' && typeof console.warn === 'function') {
        console.warn('Auth backend sync failed', error)
      }
    })
}

router.beforeEach(async(to, from, next) => {
  NProgress.start()
  document.title = getPageTitle(to.meta.title)

  const hasToken = Boolean(getToken())
  if (!hasToken) {
    if (whiteList.indexOf(to.path) !== -1) {
      next()
    } else {
      next(loginRedirect(to.fullPath))
      NProgress.done()
    }
    return
  }

  try {
    await store.dispatch('user/getInfo')
    startAuthBackendSync(getToken())

    if (to.path === '/login') {
      const redirect = (to.query && to.query.redirect) ? decodeURIComponent(to.query.redirect) : '/'
      next(redirect || '/')
      NProgress.done()
      return
    }

    next()
  } catch (error) {
    await store.dispatch('user/resetToken')
    const message = mapHttpErrorToUserMessage(error, {
      scene: isAuthSessionUnauthorized(error) ? 'auth_session' : 'generic',
      fallbackText: '登录状态校验失败，请重新登录'
    })
    Message.error(message)
    if (to.path === '/login') {
      next()
    } else {
      next(loginRedirect(to.fullPath))
      NProgress.done()
    }
  }
})

router.afterEach(() => {
  NProgress.done()
})
