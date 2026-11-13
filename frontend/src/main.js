import './index.css'
// First, before any import below creates a cached resource that replays the
// last user's IndexedDB copy into the page.
import './offlineCacheGuard'

import { createApp } from 'vue'
import { createPinia } from 'pinia'
import { createDialog } from './utils/dialogs'
import { cleanUpSupersededWorkers } from './utils/staleServiceWorkers'
import { redirectIfSessionGone } from './utils/sessionExpiry'
import { throughGate, watchConnectivity } from './offline/connectivity'
import { saveBootSnapshot } from './offline/bootSnapshot'
import { startFieldSync } from './offline/pack'
import { startOutbox } from './offline/outbox'
import { getSessionUser } from './utils/session'
import { initSocket } from './socket'
import router from './router'
import translationPlugin from './translation'
import App from './App.vue'

import {
  FrappeUI,
  Button,
  TextInput,
  FormControl,
  ErrorMessage,
  Dialog,
  Alert,
  Badge,
  setConfig,
  frappeRequest,
} from 'frappe-ui'

import { telemetryPlugin } from '@framework/ui/telemetry'
// The lucide sprite the IconPicker and string icons draw from is injected on
// first use (utils/lucideSprite), not here: frappe-ui's spritePlugin put all
// of it in the entry chunk, and the experimental barrel it came through
// pulled the rich-text editor into the boot chunks with it.

/* Vectora ships dark-first: a visitor with no stored preference boots into
   the premium dark theme. Any stored choice — light, dark, or system — wins
   untouched; frappe-ui's useColorScheme then restores this like any other
   saved preference. */
try {
  if (!localStorage.getItem('theme')) localStorage.setItem('theme', 'dark')
} catch {
  /* storage disabled: the browser default (system) applies */
}

let globalComponents = {
  Button,
  TextInput,
  FormControl,
  ErrorMessage,
  Dialog,
  Alert,
  Badge,
}

// create a pinia instance
let pinia = createPinia()

let app = createApp(App)

// Phosphor reads these through `inject`, so one provide sets the default for
// every icon in the app. `regular` is the set's baseline weight; `fill` is
// reserved for active nav items and status dots, and `duotone` for empty
// states, both opted into per call site. A set that uses every weight looks
// like a set with no rules.
app.provide('weight', 'regular')
app.provide('color', 'currentColor')

/* Every resource in the app fetches through here. When the session has lapsed
   frappe answers 403 to everything, which the pages used to render as a
   permission problem ("ask an administrator"). Send the person back to log in,
   returning to the page they were on; a genuine 403 on a live session still
   surfaces as a permission error. `call()` bypasses this hook, so the
   'frappe-ui' compat shim wraps it with the same check. */
setConfig('resourceFetcher', (options) =>
  // the gate: offline, a resource fails at once instead of hanging, and a
  // shell that booted from the cache has its CSRF token before the first POST
  throughGate(() => frappeRequest(options)).catch((error) => {
    redirectIfSessionGone(error)
    throw error
  }),
)
app.use(FrappeUI)
app.use(pinia)
app.use(router)
app.use(translationPlugin)
for (let key in globalComponents) {
  app.component(key, globalComponents[key])
}
app.use(telemetryPlugin, { app_name: 'crm' })

app.config.globalProperties.$dialog = createDialog

/* Field mode's plumbing, started once the page has its boot.

   A page Frappe rendered leaves its boot behind for the next start that has
   no server to render one (offline/bootSnapshot.js). The cached shell is that
   next start: it has nothing new to save, and a shell with no snapshot --
   a phone that has never loaded the app with signal -- has nothing to run on,
   so it says so instead of mounting an app with no site, no timezone and no
   translations. */
function startOfflineSupport() {
  const user = getSessionUser()
  if (!window.__crm_offline_shell) {
    saveBootSnapshot(user, window, window.localStorage)
  }
  watchConnectivity()
  startFieldSync()
  startOutbox()
}

function showConnectOnceNotice() {
  const root = document.getElementById('app')
  root.innerHTML = `
    <div style="display:flex;height:100%;align-items:center;justify-content:center;padding:2rem;text-align:center;font-family:system-ui,sans-serif;color:#8b90a7">
      <div style="max-width:22rem">
        <div style="font-size:1.125rem;font-weight:600;color:inherit;margin-bottom:.5rem">You are offline</div>
        <div style="font-size:.9375rem;line-height:1.5">Vectora has nothing saved on this device yet. Open it once with a connection and sign in; after that it opens without one.</div>
        <button type="button" style="margin-top:1.25rem;padding:.5rem 1rem;border-radius:.5rem;border:1px solid currentColor;background:none;color:inherit;font:inherit" onclick="location.reload()">Try again</button>
      </div>
    </div>`
  // the moment there is a network, the real page can say who this is
  window.addEventListener('online', () => window.location.reload())
}

let socket
if (window.__crm_offline_shell && !window.__crm_offline_user) {
  showConnectOnceNotice()
} else if (import.meta.env.DEV) {
  frappeRequest({ url: '/api/method/crm.www.crm.get_context_for_dev' }).then(
    (values) => {
      for (let key in values) {
        window[key] = values[key]
      }
      socket = initSocket()
      app.config.globalProperties.$socket = socket
      app.mount('#app')
      startOfflineSupport()
    },
  )
} else {
  socket = initSocket()
  app.config.globalProperties.$socket = socket
  app.mount('#app')
  startOfflineSupport()
}

if (import.meta.env.DEV) {
  window.$dialog = createDialog
}

/* Housekeeping for the PWA scope move in vite.config.js. The worker used to be
   registered at vite's base -- /assets/crm/frontend/ -- and that registration
   outlives the change: scopes key registrations, so the one at /crm is an
   addition, not a replacement. The old one is left controlling nothing while
   holding a multi-megabyte precache, and only an explicit unregister clears it.

   Fire and forget. Nothing downstream waits on it, it resolves even when the
   browser refuses, and once no visitor has a pre-/crm worker left this call
   does nothing and can go. */
cleanUpSupersededWorkers({
  scriptPath: `${import.meta.env.BASE_URL}sw.js`,
  scope: '/crm', // must track VitePWA's `scope` in vite.config.js
})
