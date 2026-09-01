import { PhTextT as LucideType } from '@phosphor-icons/vue'
import { PhTextAlignLeft as LucideAlignLeft } from '@phosphor-icons/vue'
import { PhEnvelope as LucideMail } from '@phosphor-icons/vue'
import { PhPhone as LucidePhone } from '@phosphor-icons/vue'
import { PhHash as LucideHash } from '@phosphor-icons/vue'
import { PhCaretUpDown as LucideChevronsUpDown } from '@phosphor-icons/vue'
import { PhCalendarBlank as LucideCalendar } from '@phosphor-icons/vue'
// Kept as Lucide: same reasoning as Planner.vue's Meeting icon — Phosphor's
// calendar family has no marker that reads as "carries a time", so there is
// no same-family substitute for the Datetime fieldtype that keeps that
// meaning.
import LucideCalendarClock from '~icons/lucide/calendar-clock'
import { PhClock as LucideClock } from '@phosphor-icons/vue'
import { PhPercent as LucidePercent } from '@phosphor-icons/vue'
import { PhPalette as LucidePalette } from '@phosphor-icons/vue'
import { PhCheckSquare as LucideSquareCheck } from '@phosphor-icons/vue'
import { PhLink as LucideLink } from '@phosphor-icons/vue'
// map a field (fieldtype + options) to the lucide icon shown next to its label.
// shared by the field cards and the hidden-fields list so they stay identical.
export function fieldTypeIcon(field) {
  if (field?.options === 'Email') return LucideMail
  switch (field?.fieldtype) {
    case 'Select':
      return LucideChevronsUpDown
    case 'Int':
    case 'Float':
    case 'Currency':
      return LucideHash
    case 'Percent':
      return LucidePercent
    case 'Date':
      return LucideCalendar
    case 'Datetime':
      return LucideCalendarClock
    case 'Time':
      return LucideClock
    case 'Color':
      return LucidePalette
    case 'Check':
      return LucideSquareCheck
    case 'Phone':
      return LucidePhone
    case 'Small Text':
    case 'Text':
    case 'Long Text':
    case 'Text Editor':
    case 'HTML Editor':
    case 'Markdown Editor':
      return LucideAlignLeft
    case 'Link':
      return LucideLink
    default:
      return LucideType
  }
}

export function fieldTypeLabel(field) {
  return field?.options === 'Email' ? 'Email' : field?.fieldtype
}
