/**
 * The surfaces an administrator or manager may hide, per role.
 *
 * This is the registry Settings → Access Control renders and the shell
 * consults. Two rules keep it honest:
 *
 *  1. **Configuration only narrows.** Every consumer composes this with the
 *     role gate it already had — `canSee(key) && isAdmin()`, never
 *     `canSee(key)` alone. Unhiding a surface therefore cannot reveal it, and
 *     an unrecognised key can only fail to hide something.
 *  2. **There is no admin row.** Nothing is hideable from a System Manager, so
 *     an administrator can never configure themselves out of this pane.
 *
 * `floor` records the role gate the code *already* enforces, so the matrix can
 * render a cell as fixed rather than offering a toggle the first rule
 * guarantees is inert. Keep it in step with the `condition:` on the surface.
 *
 * Adding a surface: add it here, and add `canSee('<key>') &&` to its existing
 * condition in AppSidebar.vue or Settings.vue. A surface missing from this list
 * simply stays visible, which is the safe direction.
 *
 * Keys must match the server's shape check in `crm/api/access.py`:
 * `^(nav|settings)\.[a-z0-9_]{1,48}$`.
 */

export const ADMIN_ROLE = 'System Manager'
export const MANAGER_ROLE = 'Sales Manager'
export const REP_ROLE = 'Sales User'

/** The matrix's columns. Not ADMIN_ROLE — see rule 2 above. */
export const CONFIGURABLE_ROLES = [MANAGER_ROLE, REP_ROLE]

export const SURFACES = [
  // --- nav: AppSidebar.vue's `links` ---
  { key: 'nav.dashboard', group: 'nav', label: 'Dashboard' },
  { key: 'nav.assistant', group: 'nav', label: 'Assistant' },
  { key: 'nav.analyst', group: 'nav', label: 'Analyst', floor: ADMIN_ROLE },
  { key: 'nav.planner', group: 'nav', label: 'Planner' },
  { key: 'nav.leads', group: 'nav', label: 'Leads' },
  { key: 'nav.deals', group: 'nav', label: 'Deals' },
  { key: 'nav.reports', group: 'nav', label: 'Reports' },
  { key: 'nav.notes', group: 'nav', label: 'Notes' },
  { key: 'nav.tasks', group: 'nav', label: 'Tasks' },
  { key: 'nav.calendar', group: 'nav', label: 'Calendar' },
  { key: 'nav.organizations', group: 'nav', label: 'Organizations' },
  { key: 'nav.contacts', group: 'nav', label: 'Contacts' },
  { key: 'nav.call_logs', group: 'nav', label: 'Call Logs' },

  // --- settings: Settings.vue's `tabs` ---
  // `section` is the settings group the pane lives under. It exists because
  // several labels are meaningless alone in a flat matrix -- "Accounts" (of
  // what?), "Templates" -- and because "Dashboard", "Calendar" and "Assistant"
  // each name BOTH a nav link and a settings pane. The pane renders
  // `section · label`.
  {
    key: 'settings.profile',
    group: 'settings',
    section: 'User Configuration',
    label: 'Profile',
  },
  {
    key: 'settings.preferences',
    group: 'settings',
    section: 'User Configuration',
    label: 'Preferences',
  },
  {
    key: 'settings.general',
    group: 'settings',
    section: 'System Configuration',
    label: 'General',
    floor: MANAGER_ROLE,
  },
  {
    key: 'settings.dashboard',
    group: 'settings',
    section: 'System Configuration',
    label: 'Dashboard',
    floor: MANAGER_ROLE,
  },
  {
    key: 'settings.defaults',
    group: 'settings',
    section: 'System Configuration',
    label: 'Defaults',
    floor: ADMIN_ROLE,
  },
  {
    key: 'settings.brand',
    group: 'settings',
    section: 'System Configuration',
    label: 'Brand',
    floor: MANAGER_ROLE,
  },
  {
    key: 'settings.calendar',
    group: 'settings',
    section: 'System Configuration',
    label: 'Calendar',
    floor: MANAGER_ROLE,
  },
  {
    key: 'settings.users',
    group: 'settings',
    section: 'User Management',
    label: 'Users',
    floor: MANAGER_ROLE,
  },
  {
    key: 'settings.invite_user',
    group: 'settings',
    section: 'User Management',
    label: 'Invite User',
    floor: MANAGER_ROLE,
  },
  {
    key: 'settings.sales_hierarchy',
    group: 'settings',
    section: 'User Management',
    label: 'Sales Hierarchy',
    floor: MANAGER_ROLE,
  },
  {
    key: 'settings.sales_targets',
    group: 'settings',
    section: 'User Management',
    label: 'Sales Targets',
    floor: MANAGER_ROLE,
  },
  {
    key: 'settings.access_control',
    group: 'settings',
    section: 'User Management',
    label: 'Access Control',
    floor: MANAGER_ROLE,
  },
  {
    key: 'settings.email_accounts',
    group: 'settings',
    section: 'Email',
    label: 'Accounts',
    floor: ADMIN_ROLE,
  },
  {
    key: 'settings.email_templates',
    group: 'settings',
    section: 'Email',
    label: 'Templates',
    floor: MANAGER_ROLE,
  },
  {
    key: 'settings.assignment_rules',
    group: 'settings',
    section: 'Automation & Rules',
    label: 'Assignment Rules',
    floor: ADMIN_ROLE,
  },
  {
    key: 'settings.sla_policies',
    group: 'settings',
    section: 'Automation & Rules',
    label: 'SLA Policies',
    floor: MANAGER_ROLE,
  },
  {
    key: 'settings.automation_rules',
    group: 'settings',
    section: 'Automation & Rules',
    label: 'Automation Rules',
    floor: MANAGER_ROLE,
  },
  {
    key: 'settings.assistant',
    group: 'settings',
    section: 'Automation & Rules',
    label: 'Assistant',
    floor: ADMIN_ROLE,
  },
  {
    key: 'settings.knowledge',
    group: 'settings',
    section: 'Automation & Rules',
    label: 'Knowledge',
    floor: ADMIN_ROLE,
  },
  {
    key: 'settings.report_digests',
    group: 'settings',
    section: 'Automation & Rules',
    label: 'Report Digests',
    floor: MANAGER_ROLE,
  },
  {
    key: 'settings.forms',
    group: 'settings',
    section: 'Automation & Rules',
    label: 'Forms',
    floor: MANAGER_ROLE,
  },
  {
    key: 'settings.home_actions',
    group: 'settings',
    section: 'Customization',
    label: 'Home Actions',
    floor: MANAGER_ROLE,
  },
  {
    key: 'settings.telephony',
    group: 'settings',
    section: 'Integrations',
    label: 'Telephony',
  },
  {
    key: 'settings.whatsapp',
    group: 'settings',
    section: 'Integrations',
    label: 'WhatsApp',
    floor: MANAGER_ROLE,
  },
  {
    key: 'settings.simerp',
    group: 'settings',
    section: 'Integrations',
    label: 'SIMERP',
    floor: MANAGER_ROLE,
  },
  {
    key: 'settings.acumatica',
    group: 'settings',
    section: 'Integrations',
    label: 'Acumatica',
    floor: MANAGER_ROLE,
  },
  {
    key: 'settings.lead_syncing',
    group: 'settings',
    section: 'Integrations',
    label: 'Lead Syncing',
    floor: MANAGER_ROLE,
  },
]

/** How much each role can reach, for comparing against a surface's floor. */
const RANK = { [REP_ROLE]: 0, [MANAGER_ROLE]: 1, [ADMIN_ROLE]: 2 }

export function surfacesByGroup(group) {
  return SURFACES.filter((surface) => surface.group === group)
}

/**
 * Whether `key` should be shown, given the hidden set from the server.
 *
 * Compose this with the surface's existing role gate — never use it alone.
 *
 * `hidden` must be an array to consult; anything else (missing, `null`, or a
 * truthy non-array — `{} || []` short-circuits to `{}`, which has no
 * `.includes`) fails open. Not reachable from the server today, but a
 * loading/error transient upstream is exactly the shape that could produce
 * one, and a throw here would blank the whole shell's nav.
 */
export function canSee(key, hidden) {
  if (!Array.isArray(hidden)) return true
  return !hidden.includes(key)
}

/** Whether `callerRole` may change `targetRole`'s row. Mirrors `set_visibility`. */
export function editableBy(callerRole, targetRole) {
  if (!CONFIGURABLE_ROLES.includes(targetRole)) return false
  if (callerRole === ADMIN_ROLE) return true
  if (callerRole === MANAGER_ROLE) return targetRole === REP_ROLE
  return false
}

/**
 * Whether `role` already cannot reach `surface`, so hiding it would do nothing.
 *
 * The matrix renders these cells as fixed. Offering a toggle whose effect the
 * narrowing rule guarantees is nil teaches the operator the wrong model of what
 * this pane does.
 *
 * A role absent from `RANK` reads as at-floor too. `RANK[role]` is `undefined`
 * there, and `undefined < N` is always `false` -- so the naive comparison
 * called an unrankable role "not at floor", i.e. a live toggle. Fixed is the
 * safer misreading of a role nobody vetted.
 */
export function isAtFloor(surface, role) {
  if (!surface.floor) return false
  if (!(role in RANK)) return true
  return RANK[role] < RANK[surface.floor]
}
