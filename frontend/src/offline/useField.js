/**
 * What the Field screens read: the pack on this device with the outbox laid
 * over it, indexed by customer, and today's date in the site's timezone.
 *
 * `today` is worked out from the clock, not taken from the pack. The pack says
 * what day it was when it was saved; a rep three days into a trip with no
 * signal still needs Thursday to be Thursday.
 */
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { getConfig } from 'frappe-ui'
import { applyOutbox } from '@/utils/fieldOutbox'
import { indexPack, itemsByDate, packWeeks } from '@/utils/fieldPack'
import { todayInTimeZone } from '@/utils/planner'
import { outbox } from './outbox'
import { fieldPack, packState } from './pack'

const siteDate = (ms) =>
  todayInTimeZone(getConfig('systemTimezone'), new Date(ms))

/* What the server last said, with the rep's unsent work laid over it: a visit
   logged at the mine shows as done there and then, not when the phone next
   finds a network. */
const view = computed(() =>
  applyOutbox(fieldPack.value, outbox.entries, siteDate),
)
const index = computed(() => indexPack(view.value))
const days = computed(() => itemsByDate(view.value?.plans))
const weeks = computed(() => packWeeks(view.value?.plans))

export function useField() {
  const today = ref(todayInTimeZone(getConfig('systemTimezone')))
  // a phone left open across midnight, or brought back from the pocket
  const refreshToday = () => {
    if (document.visibilityState === 'visible') {
      today.value = todayInTimeZone(getConfig('systemTimezone'))
    }
  }
  onMounted(() => document.addEventListener('visibilitychange', refreshToday))
  onBeforeUnmount(() =>
    document.removeEventListener('visibilitychange', refreshToday),
  )

  return { pack: view, state: packState, index, days, weeks, today }
}
