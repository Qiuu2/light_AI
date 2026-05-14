const assistantRefreshHandlers = new Set()

export function emitAssistantRefresh(payload = {}) {
  assistantRefreshHandlers.forEach((handler) => {
    try {
      handler(payload)
    } catch (error) {
      if (typeof console !== 'undefined' && typeof console.error === 'function') {
        console.error('assistant refresh handler failed', error)
      }
    }
  })
}

export function onAssistantRefresh(handler) {
  if (typeof handler !== 'function') return
  assistantRefreshHandlers.add(handler)
}

export function offAssistantRefresh(handler) {
  if (typeof handler !== 'function') return
  assistantRefreshHandlers.delete(handler)
}

export function __resetAssistantRefreshBus() {
  assistantRefreshHandlers.clear()
}
