/**
 * Pure logic behind the role-aware dashboard.
 *
 * Everything here is a transform over data the server already sent: which plan
 * items fall on today, which suggestions describe the same at-risk record, what
 * filter a tile drills into. It lives out here rather than inside the panels so
 * the arithmetic the dashboard makes claims with is testable — a number nobody
 * can assert is a number nobody should trust.
 */
import { parseFactors } from '@/utils/suggestions'

/* The signals that describe a deal in trouble, as opposed to the ones that just
   propose work (lead SLA, stale plan). Keyed on the `signal` field written by
   crm/agent/signals.py; a signal added there without being added here simply
   does not appear in the at-risk panel, which is the safe direction to fail. */
export const RISK_SIGNALS = [
  'idle_deal',
  'no_next_step',
  'close_at_risk',
  'deal_cooling',
]

function pad(n) {
  return String(n).padStart(2, '0')
}

/** A `Date` from a Date or a `YYYY-MM-DD` string, in local time. */
function toDate(value) {
  if (value instanceof Date) return new Date(value.getTime())
  if (typeof value !== 'string' || !value) return null
  const [y, m, d] = value.slice(0, 10).split('-').map(Number)
  if (!y || !m || !d) return null
  return new Date(y, m - 1, d)
}

/** `YYYY-MM-DD` for a Date, in local time (never `toISOString`, which is UTC). */
export function toISODate(value) {
  const date = toDate(value)
  if (!date || Number.isNaN(date.getTime())) return ''
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}`
}

/**
 * The Monday of the week containing `value`.
 *
 * The plan API rejects any week_start that is not a Monday
 * (crm.api.rep_plan._monday_or_throw), so the client has to agree with it on
 * where a week begins rather than using the locale's idea of it.
 */
export function mondayOf(value) {
  const date = toDate(value)
  if (!date || Number.isNaN(date.getTime())) return ''
  // getDay() is 0 for Sunday; ISO weeks put Sunday last, so shift by six.
  date.setDate(date.getDate() - ((date.getDay() + 6) % 7))
  return toISODate(date)
}

/**
 * Counts over plan items, optionally narrowed to one day.
 *
 * `open` is what is left to do, so a rep reading "3 of 7" knows the four are not
 * silently missed. Anything the matcher has not settled counts as open.
 */
export function planBreakdown(items, { on = null } = {}) {
  const rows = (items || []).filter(
    (item) => !on || String(item?.planned_date || '').slice(0, 10) === on,
  )
  const done = rows.filter((item) => item?.status === 'Done').length
  const missed = rows.filter((item) => item?.status === 'Missed').length
  return {
    planned: rows.length,
    done,
    missed,
    open: rows.length - done - missed,
    items: rows,
  }
}

/** Adherence as a whole percentage, matching crm.api.dashboard.plan_adherence. */
export function adherencePercent({ planned = 0, done = 0 } = {}) {
  if (!planned) return 0
  return Math.round((done / planned) * 100)
}

/**
 * Collapse the suggestion inbox into one row per at-risk record, carrying the
 * union of the factor labels that explain it.
 *
 * Two signals firing on the same deal are one deal in trouble for two reasons,
 * not two problems — showing them as separate rows makes a five-deal pipeline
 * look like a ten-deal crisis. The score is the highest of the contributing
 * suggestions, because the worst reason is what makes the deal urgent.
 */
export function groupRisksByRecord(
  suggestions,
  { signals = RISK_SIGNALS, limit = 0 } = {},
) {
  const allowed = new Set(signals)
  const byRecord = new Map()

  for (const suggestion of suggestions || []) {
    if (!suggestion || !allowed.has(suggestion.signal)) continue
    if (!suggestion.reference_doctype || !suggestion.reference_docname) continue

    const key = `${suggestion.reference_doctype}:${suggestion.reference_docname}`
    let entry = byRecord.get(key)
    if (!entry) {
      entry = {
        key,
        doctype: suggestion.reference_doctype,
        docname: suggestion.reference_docname,
        user: suggestion.user || '',
        score: 0,
        signals: [],
        factors: [],
      }
      byRecord.set(key, entry)
    }

    entry.score = Math.max(entry.score, Number(suggestion.score) || 0)
    if (!entry.signals.includes(suggestion.signal)) {
      entry.signals.push(suggestion.signal)
    }
    for (const factor of parseFactors(suggestion.factors)) {
      if (!factor?.label) continue
      if (entry.factors.some((seen) => seen.label === factor.label)) continue
      entry.factors.push({
        key: factor.key || factor.label,
        label: factor.label,
      })
    }
  }

  const rows = [...byRecord.values()].sort(
    (a, b) => b.score - a.score || a.docname.localeCompare(b.docname),
  )
  return limit > 0 ? rows.slice(0, limit) : rows
}

const STANDARD_VIEW_LABELS = {
  list: 'List',
  group_by: 'Group By',
  kanban: 'Kanban',
}

/**
 * The payload that re-points a user's standard list view at `filters`.
 *
 * The CRM list reads its filters from the CRM View Settings row behind
 * `?view=` — or, with no query, from the user's standard view for the doctype
 * (ViewControls.getParams). So a drill-down has to write that row, exactly as
 * applying a filter in the list itself does. Everything else on the view is
 * carried through unchanged: a click on a dashboard tile must not silently
 * reset the columns somebody arranged.
 */
export function standardViewPayload(
  currentView,
  { doctype, type = 'list', filters, orderBy } = {},
) {
  const view = currentView || {}
  return {
    doctype,
    type,
    label:
      view.label || STANDARD_VIEW_LABELS[type] || STANDARD_VIEW_LABELS.list,
    filters: filters || {},
    order_by: orderBy || view.order_by || 'modified desc',
    group_by_field: view.group_by_field || 'owner',
    column_field: view.column_field || 'status',
    title_field: view.title_field || '',
    kanban_columns: view.kanban_columns || '[]',
    kanban_fields: view.kanban_fields || '[]',
    columns: view.columns || '[]',
    rows: view.rows || '[]',
    load_default_columns: Boolean(view.load_default_columns),
    is_default: Boolean(view.is_default),
  }
}

/**
 * Where a dashboard tile drills through to, keyed by its widget name.
 *
 * `openStatuses`/`wonStatuses` come from the CRM Deal Status list, so the
 * filter names the same statuses the tile's own aggregate counted (those
 * functions select on `CRM Deal Status.type`). Returning null means the tile is
 * not drillable — an aggregate with no list behind it (an average, a ratio)
 * must not pretend otherwise by navigating somewhere nearly right.
 */
export function drilldownFor(name, context = {}) {
  const {
    user = null,
    openStatuses = [],
    wonStatuses = [],
    fromDate = '',
    toDate = '',
  } = context

  const dealOwner = user ? { deal_owner: user } : {}
  const leadOwner = user ? { lead_owner: user } : {}
  const created =
    fromDate && toDate ? { creation: ['between', [fromDate, toDate]] } : {}

  switch (name) {
    case 'total_leads':
      return {
        doctype: 'CRM Lead',
        routeName: 'Leads',
        filters: { converted: 0, ...leadOwner, ...created },
      }
    case 'ongoing_deals':
    case 'average_ongoing_deal_value':
    case 'average_time_to_close_a_deal':
      return openStatuses.length
        ? {
            doctype: 'CRM Deal',
            routeName: 'Deals',
            filters: { status: ['in', openStatuses], ...dealOwner },
          }
        : null
    case 'won_deals':
    case 'average_won_deal_value':
    case 'quota_attainment':
      return wonStatuses.length
        ? {
            doctype: 'CRM Deal',
            routeName: 'Deals',
            filters: {
              status: ['in', wonStatuses],
              ...dealOwner,
              ...(fromDate && toDate
                ? { closed_date: ['between', [fromDate, toDate]] }
                : {}),
            },
          }
        : null
    case 'plan_adherence':
      return { routeName: 'Planner', query: user ? { user } : {} }
    default:
      return null
  }
}

/**
 * Which way a period-over-period delta points, as a semantic tone.
 *
 * `negativeIsBetter` exists because "deals at risk" going up is the one tile
 * where a bigger number is worse, and the server says so on the payload.
 */
export function deltaTone(delta, negativeIsBetter = false) {
  const value = Number(delta) || 0
  if (!value) return 'neutral'
  return value > 0 === !negativeIsBetter ? 'positive' : 'negative'
}

/**
 * Apply a saved show/hide/order preference to the built-in panel list.
 *
 * "User-friendly" here is opinionated defaults with light customisation, so the
 * preference is a filter and a sort over a fixed catalogue rather than a
 * layout: a panel added in a later release appears for everyone who already
 * saved a preference instead of being invisible until they reset it.
 */
export function applyPanelPreference(panels, preference) {
  const hidden = new Set(preference?.hidden || [])
  const order = preference?.order || []
  const rank = new Map(order.map((id, index) => [id, index]))
  return (panels || [])
    .filter((panel) => !hidden.has(panel.id))
    .map((panel, index) => ({ panel, index }))
    .sort((a, b) => {
      const ra = rank.has(a.panel.id)
        ? rank.get(a.panel.id)
        : order.length + a.index
      const rb = rank.has(b.panel.id)
        ? rank.get(b.panel.id)
        : order.length + b.index
      return ra - rb || a.index - b.index
    })
    .map(({ panel }) => panel)
}

/** Move `id` one slot towards the front (-1) or back (1) of the panel order. */
export function movePanel(ids, id, direction) {
  const order = [...(ids || [])]
  const from = order.indexOf(id)
  const to = from + direction
  if (from < 0 || to < 0 || to >= order.length) return order
  order.splice(to, 0, order.splice(from, 1)[0])
  return order
}
