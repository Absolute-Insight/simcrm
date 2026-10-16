/* How a plan item looks: the icon for its activity type and the colour and word
   for its status. Shared by the rep's week (pages/Planner.vue) and the team
   week (components/Planner/TeamWeek.vue) so a cancelled visit cannot read one
   way on one screen and another way on the other. */

// Kept as Lucide: Phosphor's calendar family only pairs with
// check/plus/minus/x/star/heart/slash markers, none of which reads as
// "carries a time" — the meaning this glyph exists to convey for a Meeting
// activity.
import LucideCalendarClock from '~icons/lucide/calendar-clock'
import LucideClipboardList from '~icons/lucide/clipboard-list'
import LucideFileText from '~icons/lucide/file-text'
import LucideMapPin from '~icons/lucide/map-pin'
import LucideMapPinPlus from '~icons/lucide/map-pin-plus'
import LucideTruck from '~icons/lucide/truck'
import { PhCheckCircle as LucideCircleCheck } from '@phosphor-icons/vue'
import { PhEnvelope as LucideMail } from '@phosphor-icons/vue'
import { PhPhone as LucidePhone } from '@phosphor-icons/vue'

const ICONS = {
  Visit: LucideMapPin,
  'Unplanned Meeting': LucideMapPinPlus,
  Delivery: LucideTruck,
  Call: LucidePhone,
  Email: LucideMail,
  Meeting: LucideCalendarClock,
  Task: LucideCircleCheck,
  Admin: LucideClipboardList,
  Reports: LucideFileText,
}

export function typeIcon(type) {
  return ICONS[type] || LucideCircleCheck
}

/* The -9 step: it is the one that stays readable on every surface in both
   themes (AGENTS.md, "Coloured text uses the -9 step"). Orange, not amber, for
   the cancelled state for the same reason. */
export function statusColor(status) {
  if (status === 'Done') return 'text-ink-green-9'
  if (status === 'Missed') return 'text-ink-red-9'
  if (status === 'Cancelled') return 'text-ink-orange-9'
  return 'text-ink-gray-5'
}

export function statusLabel(status) {
  if (status === 'Done') return __('Done')
  if (status === 'Missed') return __('Missed')
  if (status === 'Cancelled') return __('Cancelled')
  return __('Planned')
}
