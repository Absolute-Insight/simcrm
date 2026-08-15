/**
 * Turning a dashboard number into the list of records behind it.
 *
 * The CRM list view does not read filters from the URL: ViewControls resolves
 * them from the CRM View Settings row named by `?view=`, or — with no query —
 * from the caller's *standard* view for that doctype. So the only filter a
 * drill-down can push that the list actually honours is one written onto that
 * row, which is exactly what applying a filter inside the list itself does
 * (ViewControls.updateFilter -> create_or_update_standard_view). This module
 * does the same write and then navigates, so a tile and a hand-typed filter
 * leave the user in the same place.
 *
 * The pure half — which filter belongs to which tile, and how to carry the rest
 * of a saved view through untouched — lives in `@/utils/dashboardHome`.
 */
import { statusesStore } from '@/stores/statuses'
import { viewsStore } from '@/stores/views'
import { drilldownFor, standardViewPayload } from '@/utils/dashboardHome'
import { call, toast } from 'frappe-ui'
import { computed } from 'vue'
import { useRouter } from 'vue-router'

const STANDARD_VIEW_ENDPOINT =
  'crm.fcrm.doctype.crm_view_settings.crm_view_settings.create_or_update_standard_view'

export function useDrilldown() {
  const router = useRouter()
  const { dealStatuses } = statusesStore()
  const views = viewsStore()

  const openStatuses = computed(() =>
    (dealStatuses.data || [])
      .filter((s) => ['Open', 'Ongoing'].includes(s.type))
      .map((s) => s.name),
  )

  const wonStatuses = computed(() =>
    (dealStatuses.data || [])
      .filter((s) => s.type === 'Won')
      .map((s) => s.name),
  )

  /** Navigate to `doctype`'s list showing exactly `filters`. */
  async function openList({ doctype, routeName, filters }) {
    try {
      await call(STANDARD_VIEW_ENDPOINT, {
        view: standardViewPayload(views.getView(null, 'list', doctype), {
          doctype,
          filters,
        }),
      })
      // ViewControls reads the store, not the server, when it mounts — without
      // this the list would open on the filter set from the *previous* visit.
      await views.reload()
    } catch (error) {
      toast.error(error.messages?.[0] || error.message)
      return
    }
    router.push({ name: routeName, params: { viewType: 'list' } })
  }

  /**
   * Follow a tile through to its records.
   *
   * `name` is the dashboard widget name, or a descriptor built by a panel that
   * knows its own filter (the at-risk list, which has no queryable predicate
   * and so drills through on the deal names it is already showing).
   */
  async function drillInto(name, context = {}) {
    const target =
      typeof name === 'string'
        ? drilldownFor(name, {
            ...context,
            openStatuses: openStatuses.value,
            wonStatuses: wonStatuses.value,
          })
        : name
    if (!target) return
    if (!target.doctype) {
      router.push({ name: target.routeName, query: target.query || {} })
      return
    }
    await openList(target)
  }

  /** Whether a tile has somewhere to go, so the UI can skip the affordance. */
  function canDrillInto(name, context = {}) {
    return Boolean(
      drilldownFor(name, {
        ...context,
        openStatuses: openStatuses.value,
        wonStatuses: wonStatuses.value,
      }),
    )
  }

  return { drillInto, canDrillInto, openStatuses, wonStatuses }
}
