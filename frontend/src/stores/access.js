/**
 * What the current session may see, per Settings → Access Control.
 *
 * `canSee` is a *narrowing* gate: compose it with the role check a surface
 * already had (`canSee('nav.analyst') && isAdmin()`), never on its own. See
 * `@/utils/surfaces` for why.
 *
 * The resource is awaited in the router's global guard alongside `users`, so
 * the shell paints once with the right set instead of showing a link and then
 * retracting it. Until it resolves — and if it fails — nothing is hidden, which
 * is the correct fail-open for chrome: a link that should have been tidied away
 * is a wart, and a shell missing half its nav because one request failed is an
 * outage.
 *
 * `attempted` is distinct from the resource's own `fetched`. frappe-ui's
 * `createResource` only flips `fetched` to `true` on success, so a failed
 * fetch leaves it `false` forever -- gating the guard on `!fetched` would
 * retry, and re-throw past the guard's try/catch, on every navigation until
 * one happens to succeed. `attempted` flips as soon as a fetch is kicked off,
 * win or lose, so the guard tries exactly once per session. `reload()` -- the
 * explicit call after the settings pane saves -- is unconditional on purpose:
 * a deliberate reload must still work even after the one automatic attempt.
 */
import { computed, reactive } from 'vue'
import { createResource } from 'frappe-ui'
import { defineStore } from 'pinia'
import { canSee as canSeeSurface } from '@/utils/surfaces'

export const accessStore = defineStore('crm-access', () => {
  const state = reactive({
    role: 'Sales User',
    hidden: [],
    matrix: null,
    attempted: false,
  })

  const visibility = createResource({
    url: 'crm.api.access.get_visibility',
    cache: 'access-visibility',
    auto: false,
    onSuccess(data) {
      state.role = data?.role || 'Sales User'
      state.hidden = data?.hidden || []
      state.matrix = data?.matrix || null
    },
    onError() {
      // fail open — see the module comment
      state.hidden = []
    },
  })

  function canSee(key) {
    return canSeeSurface(key, state.hidden)
  }

  function reload() {
    state.attempted = true
    return visibility.fetch()
  }

  return {
    visibility,
    canSee,
    reload,
    role: computed(() => state.role),
    hidden: computed(() => state.hidden),
    matrix: computed(() => state.matrix),
    attempted: computed(() => state.attempted),
  }
})
