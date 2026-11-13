/**
 * What the Field screens read: the pack on this device, indexed by customer,
 * and today's date in the site's timezone.
 *
 * `today` is worked out from the clock, not taken from the pack. The pack says
 * what day it was when it was saved; a rep three days into a trip with no
 * signal still needs Thursday to be Thursday.
 */
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { getConfig } from 'frappe-ui'
import { indexPack, itemsByDate, packWeeks } from '@/utils/fieldPack'
import { todayInTimeZone } from '@/utils/planner'
import { fieldPack, packState } from './pack'

const index = computed(() => indexPack(fieldPack.value))
const days = computed(() => itemsByDate(fieldPack.value?.plans))
const weeks = computed(() => packWeeks(fieldPack.value?.plans))

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

  return { pack: fieldPack, state: packState, index, days, weeks, today }
}
