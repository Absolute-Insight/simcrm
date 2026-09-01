import './index.css'

import { createApp } from 'vue'
import { createPinia } from 'pinia'
import { createDialog } from './utils/dialogs'
import { cleanUpSupersededWorkers } from './utils/staleServiceWorkers'
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
// injects the lucide SVG sprite into the DOM so the IconPicker and lucide Icons
// (used for view icons) can render from it
// parked in experimental for v1 (frappe-ui migration doc)
import { spritePlugin } from 'frappe-ui/experimental'

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

setConfig('resourceFetcher', frappeRequest)
app.use(FrappeUI)
app.use(spritePlugin)
app.use(pinia)
app.use(router)
app.use(translationPlugin)
for (let key in globalComponents) {
  app.component(key, globalComponents[key])
}
app.use(telemetryPlugin, { app_name: 'crm' })

app.config.globalProperties.$dialog = createDialog

let socket
if (import.meta.env.DEV) {
  frappeRequest({ url: '/api/method/crm.www.crm.get_context_for_dev' }).then(
    (values) => {
      for (let key in values) {
        window[key] = values[key]
      }
      socket = initSocket()
      app.config.globalProperties.$socket = socket
      app.mount('#app')
    },
  )
} else {
  socket = initSocket()
  app.config.globalProperties.$socket = socket
  app.mount('#app')
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
