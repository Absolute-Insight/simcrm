import { PhChartLineUp as AnalystIcon } from '@phosphor-icons/vue'
import CalendarIcon from '@/components/Icons/CalendarIcon.vue'
import ContactsIcon from '@/components/Icons/ContactsIcon.vue'
import DashboardIcon from '@/components/Icons/DashboardIcon.vue'
import DealsIcon from '@/components/Icons/DealsIcon.vue'
import LeadsIcon from '@/components/Icons/LeadsIcon.vue'
import NoteIcon from '@/components/Icons/NoteIcon.vue'
import OrganizationsIcon from '@/components/Icons/OrganizationsIcon.vue'
import PhoneIcon from '@/components/Icons/PhoneIcon.vue'
import PlannerIcon from '@/components/Icons/PlannerIcon.vue'
import ReportsIcon from '@/components/Icons/ReportsIcon.vue'
import SparkleIcon from '@/components/Icons/SparkleIcon.vue'
import TaskIcon from '@/components/Icons/TaskIcon.vue'
import { accessStore } from '@/stores/access'
import { usersStore } from '@/stores/users'

/**
 * The app's places, each with the condition that shows it. The sidebar renders
 * this and the command palette searches it, so a surface Access Control hides
 * disappears from both.
 */
export function useNavLinks({ mobile = () => false } = {}) {
  const { canSee } = accessStore()
  const { isAdmin } = usersStore()

  return [
    // Order is product order, not alphabetical: what a rep opens first comes
    // first. Dashboard is the landing surface, Assistant answers the question
    // that sent them there, then the planning and pipeline surfaces, then the
    // records they act on.
    //
    // Dashboard, Planner and Reports are the surfaces Vectora is *for*, and they
    // were unreachable on a phone -- routed and rendering, just absent from the
    // one menu a mobile rep has. Each was checked at 390px: the dashboard stacks
    // its tiles, the planner falls back from a week grid to a day list, and the
    // reports table scrolls inside its own container. Calendar stays hidden
    // because it genuinely does not fit -- seven day-columns and a clipped
    // toolbar.
    //
    // `tint` is the -6 step of a colour family. See the comment on the nav row in
    // AppSidebar.vue for why -6.
    {
      label: 'Dashboard',
      key: 'nav.dashboard',
      icon: DashboardIcon,
      to: 'Dashboard',
      tint: 'text-ink-blue-6',
      condition: () => canSee('nav.dashboard'),
    },
    // The one entry that is not a place. Assistant opens a slide-over, so it
    // carries `action` instead of `to` and the row renders as a toggle -- it sits
    // second because it is the surface a rep reaches for from the dashboard, not
    // because it is a route. On mobile the panel has nowhere to slide from, the
    // same condition it carried when it lived above this list.
    {
      label: 'Assistant',
      key: 'nav.assistant',
      icon: SparkleIcon,
      action: 'assistant',
      tint: 'text-ink-violet-6',
      condition: () => canSee('nav.assistant') && !mobile(),
    },
    // The Analyst is the second AI agent, admin-only: it sits with the
    // Assistant, ahead of the planning and pipeline surfaces.
    {
      label: 'Analyst',
      key: 'nav.analyst',
      icon: AnalystIcon,
      to: 'Analyst',
      tint: 'text-ink-cyan-6',
      // canSee narrows only: isAdmin() still decides, and the route guard at
      // router.js:64 and frappe.only_for in crm/agent/api.py both stand behind it.
      condition: () => canSee('nav.analyst') && isAdmin(),
    },
    {
      label: 'Planner',
      key: 'nav.planner',
      icon: PlannerIcon,
      to: 'Planner',
      tint: 'text-ink-teal-6',
      condition: () => canSee('nav.planner'),
    },
    {
      label: 'Leads',
      key: 'nav.leads',
      icon: LeadsIcon,
      to: 'Leads',
      tint: 'text-ink-orange-6',
      condition: () => canSee('nav.leads'),
    },
    {
      label: 'Deals',
      key: 'nav.deals',
      icon: DealsIcon,
      to: 'Deals',
      tint: 'text-ink-green-6',
      condition: () => canSee('nav.deals'),
    },
    {
      label: 'Reports',
      key: 'nav.reports',
      icon: ReportsIcon,
      to: 'Reports',
      tint: 'text-ink-purple-6',
      condition: () => canSee('nav.reports'),
    },
    {
      label: 'Notes',
      key: 'nav.notes',
      icon: NoteIcon,
      to: 'Notes',
      tint: 'text-ink-yellow-6',
      condition: () => canSee('nav.notes'),
    },
    {
      label: 'Tasks',
      key: 'nav.tasks',
      icon: TaskIcon,
      to: 'Tasks',
      tint: 'text-ink-pink-6',
      condition: () => canSee('nav.tasks'),
    },
    {
      label: 'Calendar',
      key: 'nav.calendar',
      icon: CalendarIcon,
      to: 'Calendar',
      tint: 'text-ink-red-6',
      condition: () => canSee('nav.calendar') && !mobile(),
    },
    {
      label: 'Organizations',
      key: 'nav.organizations',
      icon: OrganizationsIcon,
      to: 'Organizations',
      tint: 'text-ink-teal-6',
      condition: () => canSee('nav.organizations'),
    },
    {
      label: 'Contacts',
      key: 'nav.contacts',
      icon: ContactsIcon,
      to: 'Contacts',
      tint: 'text-ink-blue-6',
      condition: () => canSee('nav.contacts'),
    },
    {
      label: 'Call Logs',
      key: 'nav.call_logs',
      icon: PhoneIcon,
      to: 'Call Logs',
      tint: 'text-ink-orange-6',
      condition: () => canSee('nav.call_logs'),
    },
  ]
}
