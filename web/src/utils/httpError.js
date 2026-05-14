function normalizeScene(scene) {
  return String(scene || 'generic').trim() || 'generic'
}

function normalizeDetail(error) {
  const detail = error && error.response && error.response.data && error.response.data.detail
  return typeof detail === 'string' ? detail.trim() : ''
}

function normalizeUrl(error, requestPath) {
  const explicitPath = String(requestPath || '').trim()
  if (explicitPath) return explicitPath
  const url = error && error.config && error.config.url
  return typeof url === 'string' ? url.trim() : ''
}

function logRequestError(error, requestPath) {
  const status = error && error.response && error.response.status
  const detail = normalizeDetail(error)
  const url = normalizeUrl(error, requestPath)
  if (typeof console !== 'undefined' && typeof console.warn === 'function') {
    console.warn('[request-error]', { status, detail, url })
  }
}

function buildDefaultErrorMessage(error, requestPath, fallbackText) {
  const path = normalizeUrl(error, requestPath)
  const fallback = String(fallbackText || '请求失败').trim() || '请求失败'
  const status = error && error.response && error.response.status
  const detail = normalizeDetail(error)
  const baseMessage = status ? `${fallback}（HTTP ${status}）` : fallback
  const pathMessage = path ? `接口: ${path}` : ''
  if (detail) {
    return [baseMessage, pathMessage, `详情: ${detail}`].filter(Boolean).join('，')
  }
  if (pathMessage) {
    return `${baseMessage}，${pathMessage}`
  }
  if (error && error.message) {
    return `${baseMessage}，${error.message}`
  }
  return baseMessage
}

export function isAuthSessionUnauthorized(error) {
  const status = error && error.response && error.response.status
  const url = normalizeUrl(error)
  return status === 401 && typeof url === 'string' && url.indexOf('/auth/session') !== -1
}

export function mapHttpErrorToUserMessage(error, options = {}) {
  const scene = normalizeScene(options.scene)
  const fallbackText = options.fallbackText
  const requestPath = options.requestPath
  const status = error && error.response && error.response.status
  const detail = normalizeDetail(error)
  const loweredDetail = detail.toLowerCase()

  logRequestError(error, requestPath)

  if (!error || !error.response || status >= 500) {
    return String(fallbackText || '请求失败，请稍后重试。').trim() || '请求失败，请稍后重试。'
  }

  if (status === 401) {
    if (scene === 'assistant_chat') {
      return '助手暂时无法使用，请重新登录后再试。'
    }
    if (scene === 'assistant_logs' || scene === 'assistant_settings') {
      return '登录状态已失效，无法加载助手数据，请重新登录。'
    }
    if (scene === 'page_data') {
      return '登录状态已失效，请重新登录后重新加载页面。'
    }
    if (scene === 'auth_session') {
      return '登录状态已失效，正在跳转登录页。'
    }
    if (loweredDetail === 'login required.') {
      return '登录状态已失效，请重新登录后再试。'
    }
    if (loweredDetail === 'remote token is invalid or expired.') {
      return '当前登录已过期，请重新登录后再试。'
    }
    if (loweredDetail === 'remote token is missing.') {
      return '当前登录信息不完整，请重新登录后再试。'
    }
    return '当前无访问权限，请重新登录后再试。'
  }

  return buildDefaultErrorMessage(error, requestPath, fallbackText)
}
