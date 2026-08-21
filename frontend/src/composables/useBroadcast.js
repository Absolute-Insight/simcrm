import { onMounted, onUnmounted } from 'vue'

const STORAGE_KEY = 'app_broadcasts'
/* `on` registers a wrapper that unpacks `detail`, so `off` has to find that
   wrapper again — passing the caller's handler to removeEventListener removed
   nothing and every remount stacked another listener. */
const wrappers = new Map()
const bus = {
  send(event, payload) {
    window.dispatchEvent(new CustomEvent(event, { detail: payload }))

    const broadcasts = JSON.parse(localStorage.getItem(STORAGE_KEY) || '[]')
    broadcasts.push({ event, payload, timestamp: Date.now() })
    localStorage.setItem(STORAGE_KEY, JSON.stringify(broadcasts))
  },
  on(event, handler) {
    const wrapper = (e) => handler(e.detail)
    wrappers.set(handler, wrapper)
    window.addEventListener(event, wrapper)
  },
  off(event, handler) {
    const wrapper = wrappers.get(handler)
    if (!wrapper) return
    wrappers.delete(handler)
    window.removeEventListener(event, wrapper)
  },
}

export function useBroadcast() {
  const listeners = []

  function on(event, handler) {
    bus.on(event, handler)
    listeners.push({ event, handler })

    // check localStorage for missed broadcasts on init
    onMounted(() => {
      const broadcasts = JSON.parse(localStorage.getItem(STORAGE_KEY) || '[]')
      const missed = broadcasts.filter((b) => b.event === event)
      if (missed.length) {
        missed.forEach((b) => handler(b.payload))
        // clear handled broadcasts
        const remaining = broadcasts.filter((b) => b.event !== event)
        localStorage.setItem(STORAGE_KEY, JSON.stringify(remaining))
      }
    })
  }

  onUnmounted(() => {
    listeners.forEach(({ event, handler }) => bus.off(event, handler))
  })

  return { on, send: bus.send }
}

/* The bus itself, for tests and for code outside a component setup. */
export { bus as broadcastBus }
