import { onMounted, onUnmounted } from 'vue'

const STORAGE_KEY = 'app_broadcasts'
/* `on` registers a wrapper that unpacks `detail`, so `off` has to find that
   wrapper again — passing the caller's handler to removeEventListener removed
   nothing and every remount stacked another listener. */
const wrappers = new Map()
/* Live listeners per event. A broadcast is stored for a later mount only when
   nobody heard it: storing every one meant an event already handled live --
   "Create your first lead" clicked on the Leads page -- opened the New Lead
   modal again on the next visit to Leads, even after a reload. */
const listening = new Map()

function stored() {
  try {
    return JSON.parse(localStorage.getItem(STORAGE_KEY) || '[]')
  } catch {
    return []
  }
}

function store(broadcasts) {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(broadcasts))
  } catch {
    /* storage disabled: a missed broadcast is simply missed */
  }
}

const bus = {
  send(event, payload) {
    window.dispatchEvent(new CustomEvent(event, { detail: payload }))
    if (listening.get(event)) return

    // One pending copy per event: three template saves made while no
    // selector was mounted are one reload on its next mount, not three.
    const broadcasts = stored().filter((b) => b.event !== event)
    broadcasts.push({ event, payload, timestamp: Date.now() })
    store(broadcasts)
  },
  on(event, handler) {
    const wrapper = (e) => handler(e.detail)
    wrappers.set(handler, wrapper)
    listening.set(event, (listening.get(event) || 0) + 1)
    window.addEventListener(event, wrapper)
  },
  off(event, handler) {
    const wrapper = wrappers.get(handler)
    if (!wrapper) return
    wrappers.delete(handler)
    listening.set(event, Math.max((listening.get(event) || 0) - 1, 0))
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
      const broadcasts = stored()
      const missed = broadcasts.filter((b) => b.event === event)
      if (missed.length) {
        missed.forEach((b) => handler(b.payload))
        // clear handled broadcasts
        store(broadcasts.filter((b) => b.event !== event))
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
