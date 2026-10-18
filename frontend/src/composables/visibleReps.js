import { createResource } from 'frappe-ui'
import { computed } from 'vue'
import { usersStore } from '@/stores/users'

/* The reps a manager may filter on: the planner's own list
   (crm.api.rep_plan.get_visible_reps), not a User link. Frappe's link search
   only offers enabled users, and MBP's reps are disabled until go-live, so
   the Dashboard's and Reports' "All reps" lists were empty of reps while
   every report had rows for them. */

export const ALL_REPS = '__all__'

let reps = null

export function useVisibleReps() {
  reps ||= createResource({
    url: 'crm.api.rep_plan.get_visible_reps',
    cache: 'crm-visible-reps',
    auto: true,
    initialData: [],
  })
  const { getUser } = usersStore()

  const repOptions = computed(() =>
    (reps.data || [])
      .map((name) => ({ label: getUser(name)?.full_name || name, value: name }))
      .sort((a, b) => a.label.localeCompare(b.label)),
  )

  /* For a Select: "All reps" first, under a sentinel because the select
     cannot hold an empty value. */
  const filterOptions = computed(() => [
    { label: __('All reps'), value: ALL_REPS },
    ...repOptions.value,
  ])

  return { reps, repOptions, filterOptions }
}
