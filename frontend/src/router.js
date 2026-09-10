import { createRouter, createWebHistory } from 'vue-router'
import { call } from 'frappe-ui'
import { usersStore } from '@/stores/users'
import { sessionStore } from '@/stores/session'
import { viewsStore } from '@/stores/views'
import { accessStore } from '@/stores/access'
import { reloadOnceForStaleChunk } from '@/utils/staleChunk'

let personaChecked = false
export const PERSONA_DONE_KEY = 'crm_persona_captured'

async function shouldCapturePersona() {
  // Client-side flag guards against re-prompting if the server persist failed.
  if (localStorage.getItem(PERSONA_DONE_KEY)) return false
  const captured = await call('frappe.client.get_single_value', {
    doctype: 'FCRM Settings',
    field: 'persona_captured',
  })
  if (captured) return false
  // The wizard only feeds telemetry; skip it entirely if the user opted out.
  const { enabled } =
    (await call('frappe.utils.telemetry.pulse.client.boot_config')) || {}
  return !!enabled
}

const routes = [
  {
    path: '/',
    name: 'Home',
  },
  {
    path: '/notifications',
    name: 'Notifications',
    component: () => import('@/pages/MobileNotification.vue'),
  },
  // The desktop equivalent is a slide-over off the sidebar, which has nowhere
  // to live on a phone -- so, as with Notifications, mobile gets a route.
  {
    path: '/suggestions',
    name: 'Suggestions',
    component: () => import('@/pages/MobileSuggestions.vue'),
  },
  {
    path: '/dashboard',
    name: 'Dashboard',
    component: () => import('@/pages/Dashboard.vue'),
  },
  {
    path: '/planner',
    name: 'Planner',
    component: () => import('@/pages/Planner.vue'),
  },
  {
    path: '/reports',
    name: 'Reports',
    component: () => import('@/pages/Reports.vue'),
  },
  {
    path: '/analyst',
    name: 'Analyst',
    component: () => import('@/pages/Analyst.vue'),
    // Administrators only, like the endpoint behind it. The global guard
    // has awaited the users resource by the time this runs.
    beforeEnter: () =>
      usersStore().isAdmin() ? true : { name: 'Dashboard', replace: true },
  },
  {
    alias: '/leads',
    path: '/leads/view/:viewType?',
    name: 'Leads',
    component: () => import('@/pages/Leads.vue'),
  },
  {
    path: '/leads/:leadId',
    name: 'Lead',
    component: () => import(`@/pages/${handleMobileView('Lead')}.vue`),
    props: true,
  },
  {
    alias: '/deals',
    path: '/deals/view/:viewType?',
    name: 'Deals',
    component: () => import('@/pages/Deals.vue'),
  },
  {
    path: '/deals/:dealId',
    name: 'Deal',
    component: () => import(`@/pages/${handleMobileView('Deal')}.vue`),
    props: true,
  },
  {
    alias: '/notes',
    path: '/notes/view/:viewType?',
    name: 'Notes',
    component: () => import('@/pages/Notes.vue'),
  },
  {
    alias: '/tasks',
    path: '/tasks/view/:viewType?',
    name: 'Tasks',
    component: () => import('@/pages/Tasks.vue'),
  },
  {
    alias: '/contacts',
    path: '/contacts/view/:viewType?',
    name: 'Contacts',
    component: () => import('@/pages/Contacts.vue'),
  },
  {
    path: '/contacts/:contactId',
    name: 'Contact',
    component: () => import(`@/pages/${handleMobileView('Contact')}.vue`),
    props: true,
  },
  {
    alias: '/organizations',
    path: '/organizations/view/:viewType?',
    name: 'Organizations',
    component: () => import('@/pages/Organizations.vue'),
  },
  {
    path: '/organizations/:organizationId',
    name: 'Organization',
    component: () => import(`@/pages/${handleMobileView('Organization')}.vue`),
    props: true,
  },
  {
    alias: '/call-logs',
    path: '/call-logs/view/:viewType?',
    name: 'Call Logs',
    component: () => import('@/pages/CallLogs.vue'),
  },
  {
    path: '/calendar',
    name: 'Calendar',
    component: () => import('@/pages/Calendar.vue'),
  },
  {
    path: '/data-import',
    name: 'DataImportList',
    component: () => import('@/pages/DataImport.vue'),
  },
  {
    path: '/data-import/doctype/:doctype',
    name: 'NewDataImport',
    component: () => import('@/pages/DataImport.vue'),
    props: true,
  },
  {
    path: '/data-import/:importName',
    name: 'DataImport',
    component: () => import('@/pages/DataImport.vue'),
    props: true,
  },
  {
    path: '/onboarding',
    name: 'Onboarding',
    component: () => import('@/pages/PersonaForm.vue'),
  },
  {
    path: '/:invalidpath',
    name: 'Invalid Page',
    component: () => import('@/pages/InvalidPage.vue'),
  },
  {
    path: '/not-permitted',
    name: 'Not Permitted',
    component: () => import('@/pages/NotPermitted.vue'),
  },
]

const handleMobileView = (componentName) => {
  return window.innerWidth < 768 ? `Mobile${componentName}` : componentName
}

let router = createRouter({
  history: createWebHistory('/crm'),
  routes,
})

router.beforeEach(async (to, from, next) => {
  router.previousRoute = from

  const { isLoggedIn, user } = sessionStore()
  const { users, isCrmUser, isAdmin } = usersStore()
  const { attempted: accessAttempted, reload: reloadAccess } = accessStore()

  if (isLoggedIn && !users.fetched) {
    try {
      await users.promise
    } catch (error) {
      console.error('Error loading users', error)
    }
  }

  // Awaited here rather than in the sidebar so the shell paints once with the
  // right set instead of showing a link and then retracting it. Gated on
  // isCrmUser(), not just isLoggedIn: get_visibility refuses anyone with no
  // CRM role, and such a user is sent to Not Permitted below regardless, so
  // fetching for them would only guarantee a 403 on every navigation. Gated
  // on `attempted`, not the resource's own `fetched`: a failed fetch never
  // flips `fetched` (see stores/access.js), so checking that here would retry
  // -- and re-throw past this catch -- on every navigation. A failure is
  // swallowed on purpose: the store leaves nothing hidden, which is the right
  // fail-open for chrome.
  if (isLoggedIn && isCrmUser() && !accessAttempted) {
    try {
      await reloadAccess()
    } catch (error) {
      console.error('Error loading access settings', error)
    }
  }

  const isAdminUser = isLoggedIn && (isAdmin() || user === 'Administrator')

  // Only admins who haven't finished may reach the wizard, even via direct URL.
  if (isLoggedIn && to.name === 'Onboarding') {
    try {
      if (!isAdminUser || !(await shouldCapturePersona())) {
        return next({ name: 'Home' })
      }
    } catch {
      return next({ name: 'Home' })
    }
  }

  if (
    isLoggedIn &&
    isCrmUser() &&
    !personaChecked &&
    to.name !== 'Onboarding' &&
    isAdminUser
  ) {
    personaChecked = true
    try {
      if (await shouldCapturePersona()) {
        return next({ name: 'Onboarding' })
      }
    } catch {
      // fail open
    }
  }

  if (isLoggedIn && to.name !== 'Not Permitted' && !isCrmUser()) {
    next({ name: 'Not Permitted' })
  } else if (to.name === 'Home' && isLoggedIn) {
    // Eight of MBP's reps have muscle memory in an app whose home screen is
    // their week. A rep looking for "what am I doing Tuesday" must not have
    // to learn a route on day one; managers keep the views-driven default.
    const { isManager } = usersStore()
    if (!isManager()) {
      next({ name: 'Planner' })
      return
    }
    const { views, getDefaultView } = viewsStore()
    await views.promise

    let defaultView = getDefaultView()
    if (!defaultView) {
      next({ name: 'Leads' })
      return
    }

    let { route_name, type, name, is_standard } = defaultView
    route_name = route_name || 'Leads'

    if (name && !is_standard) {
      next({
        name: route_name,
        params: { viewType: type },
        query: { view: name },
      })
    } else {
      next({ name: route_name, params: { viewType: type } })
    }
  } else if (!isLoggedIn) {
    // Carry the requested route so the person comes back to it, not to the
    // front door; crm/www/crm.py does the same for a cold /crm/<path> load.
    window.location.href =
      '/login?redirect-to=' + encodeURIComponent('/crm' + to.fullPath)
    // Leaving the SPA entirely, but this guard still has to answer: vue-router
    // declares `next` in its signature, so returning without calling it logs
    // "Invalid navigation guard" and rejects the navigation with an error
    // nothing handles. next(false) aborts the in-app route cleanly while the
    // browser goes to /login.
    next(false)
  } else if (to.matched.length === 0) {
    next({ name: 'Invalid Page' })
  } else if (['Deal', 'Lead'].includes(to.name) && !to.hash) {
    let storageKey = to.name === 'Deal' ? 'lastDealTab' : 'lastLeadTab'
    const activeTab = localStorage.getItem(storageKey) || 'activity'
    const hash = '#' + activeTab
    next({ ...to, hash })
  } else if (
    [
      'Leads',
      'Deals',
      'Contacts',
      'Organizations',
      'Notes',
      'Tasks',
      'Call Logs',
    ].includes(to.name) &&
    !to.query?.view
  ) {
    const { views, standardViews, getDefaultView } = viewsStore()
    await views.promise

    const viewType = to.params?.viewType ?? ''
    const standardViewTypes = ['list', 'kanban', 'group_by']

    if (!viewType) {
      const doctypeMap = {
        Leads: 'CRM Lead',
        Deals: 'CRM Deal',
        Contacts: 'Contact',
        Organizations: 'CRM Organization',
        Notes: 'FCRM Note',
        Tasks: 'CRM Task',
        'Call Logs': 'CRM Call Log',
      }

      const doctype = doctypeMap[to.name]
      let defaultViewType = 'list'

      let globalDefault = getDefaultView()
      if (globalDefault && globalDefault.route_name === to.name) {
        defaultViewType = globalDefault.type || 'list'
        if (globalDefault.name && !globalDefault.is_standard) {
          next({
            name: to.name,
            params: { viewType: defaultViewType },
            query: { ...to.query, view: globalDefault.name },
          })
          return
        }
      }

      for (const viewType of standardViewTypes) {
        const standardView = standardViews.value?.[doctype + ' ' + viewType]
        if (standardView?.is_default) {
          defaultViewType = viewType
          break
        }
      }

      next({
        name: to.name,
        params: { viewType: defaultViewType },
        query: to.query,
      })
    } else if (!standardViewTypes.includes(viewType)) {
      const viewNameOrLabel = viewType

      let view = views.data?.find(
        (v) => v.name == viewNameOrLabel || v.label === viewNameOrLabel,
      )

      if (view) {
        next({
          name: to.name,
          params: { viewType: view.type || 'list' },
          query: { ...to.query, view: view.name },
        })
      } else {
        next({
          name: to.name,
          params: { viewType: 'list' },
          query: to.query,
        })
      }
    } else {
      next()
    }
  } else {
    next()
  }
})

/* A release replaces every hashed chunk. A tab opened before it lazily imports
   a page that no longer exists, the navigation rejects, and nothing tells the
   person -- the sidebar simply stops working until they think of reloading.
   Reload once onto the page they asked for; the cooldown keeps a build that is
   broken for real from reloading in a loop. */
router.onError((error, to) => {
  reloadOnceForStaleChunk(
    error,
    to?.fullPath ? `/crm${to.fullPath}` : undefined,
  )
})

export default router
