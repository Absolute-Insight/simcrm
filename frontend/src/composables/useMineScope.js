import { createResource } from 'frappe-ui'
import { computed, ref } from 'vue'

/* The "Mine / All" switch on Customers and Contacts.

   A rep sees their own customers and every unclaimed one, which on a live ERP
   book is most of the company's, and MBP's reps asked for "only mine". The
   switch sends real list filters rather than a flag the server would have to
   know about, so the export and every other path that reads a list's filters
   agree with what is on screen.

   A user who owns no customer has nothing to narrow to: the switch is hidden
   and the list is the whole book, as before. One who does starts on "Mine";
   the choice is remembered per page on this device. */

export const MINE = 'mine'
export const ALL = 'all'

let names = null

function myCustomerNames() {
  names ||= createResource({
    url: 'crm.api.doc.my_customer_names',
    auto: true,
    initialData: null,
  })
  return names
}

function readChoice(key) {
  try {
    const value = localStorage.getItem(key)
    return value === MINE || value === ALL ? value : null
  } catch {
    return null
  }
}

function writeChoice(key, value) {
  try {
    localStorage.setItem(key, value)
  } catch {
    // private window or blocked storage: the switch still works for the visit
  }
}

/**
 * @param {string} page - which list this is, for the remembered choice
 * @param {(names: string[], user: string) => object} filtersFor - the list
 *   filters that mean "mine" on this page
 * @param {string} user - the session user
 */
export function useMineScope(page, filtersFor, user) {
  const resource = myCustomerNames()
  const key = `crm-mine-scope:${page}`
  const chosen = ref(readChoice(key))

  // ready once we know whether there is anything to narrow to; a failed lookup
  // shows the whole list rather than none
  const ready = computed(() => resource.data !== null || !!resource.error)
  const available = computed(() => (resource.data || []).length > 0)

  const scope = computed({
    get: () => (available.value ? chosen.value || MINE : ALL),
    set: (value) => {
      chosen.value = value
      writeChoice(key, value)
    },
  })

  const filters = computed(() =>
    scope.value === MINE ? filtersFor(resource.data || [], user) : {},
  )

  const options = [
    { label: __('Mine'), value: MINE },
    { label: __('All'), value: ALL },
  ]

  return { ready, available, scope, filters, options }
}
