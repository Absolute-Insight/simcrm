/**
 * Week maths and plan bookkeeping for the Planner — pure, so it can be
 * unit-tested without a browser, a server or a clock.
 *
 * Dates are handled as `YYYY-MM-DD` strings throughout and the arithmetic runs
 * in UTC. The planner's week boundaries are calendar days in the *site's*
 * timezone, which is not necessarily the browser's: doing the maths on a local
 * `Date` would shift a Sunday-evening rep into the wrong week, which is exactly
 * the off-by-a-week bug this module exists to prevent. `todayInTimeZone` is the
 * single place a wall clock is consulted, and the caller passes it the site
 * timezone the server itself uses.
 */

/* Mirrors MATCH_HORIZON_WEEKS in crm/rep_planning.py. save_plan refuses a week
   older than this, so the UI has to know the same number to disable the button
   with a reason instead of letting the save fail. */
export const MATCH_HORIZON_WEEKS = 8

const DAY_MS = 86400000
const ISO_DATE = /^(\d{4})-(\d{2})-(\d{2})/

/* The item fields a client may send. Everything else on a row — status,
   fulfilment, manual_override — belongs to the matcher, so a local edit to one
   of them is not a change worth reporting as unsaved. Kept in step with
   EDITABLE_ITEM_FIELDS in crm/api/rep_plan.py. */
export const EDITABLE_ITEM_FIELDS = [
  'activity_type',
  'planned_date',
  'note',
  'reference_doctype',
  'reference_docname',
  'organization',
  'site',
  'contact',
  'suggestion',
]

/* Every kind of activity a plan item can be, in the order the planner offers
   them, with the words MBP's reps use for them. Mirrors ACTIVITY_TYPES in
   crm/rep_planning.py; the stored value is the key, the label is display. */
export const ACTIVITY_TYPES = [
  { value: 'Visit', label: 'Visit' },
  { value: 'Unplanned Meeting', label: 'Unplanned Meeting' },
  { value: 'Delivery', label: 'Delivery' },
  { value: 'Call', label: 'Phone Call' },
  { value: 'Email', label: 'E-mail' },
  { value: 'Meeting', label: 'Meeting' },
  { value: 'Task', label: 'Task' },
  { value: 'Admin', label: 'Admin' },
  { value: 'Reports', label: 'Reports' },
]

/* An unplanned meeting is, by definition, never planned: it is logged. */
export const PLANNABLE_TYPES = ACTIVITY_TYPES.filter(
  (t) => t.value !== 'Unplanned Meeting',
)

/* LOGGABLE_TYPES in crm/api/rep_plan.py: what a rep can record after the fact. */
export const LOGGABLE_TYPES = ACTIVITY_TYPES.filter(
  (t) => !['Meeting', 'Task'].includes(t.value),
)

/* EVENT_KINDS in crm/rep_planning.py: closing one of these puts a visit on the
   calendar against the customer, so the customer is required to log one. */
export const EVENT_KINDS = ['Visit', 'Unplanned Meeting', 'Delivery']

/**
 * The display label for a stored activity type.
 * @returns {string}
 */
export function activityLabel(type) {
  return ACTIVITY_TYPES.find((t) => t.value === type)?.label || type || ''
}

/* Which page a plan item's reference opens, and under which param. A plan item
   can only ever point at one of these two — REFERENCE_DOCTYPES in
   crm/api/rep_plan.py refuses anything else on save. */
const REFERENCE_ROUTES = {
  'CRM Deal': { name: 'Deal', param: 'dealId' },
  'CRM Lead': { name: 'Lead', param: 'leadId' },
}

/**
 * Parse `YYYY-MM-DD` (or the leading date of an ISO datetime) as a UTC instant.
 * @returns {number|null} epoch ms, or null when the input is unusable.
 */
function toUTC(value) {
  if (value instanceof Date) {
    if (Number.isNaN(value.getTime())) return null
    return Date.UTC(
      value.getFullYear(),
      value.getMonth(),
      value.getDate(),
      0,
      0,
      0,
      0,
    )
  }
  const match = ISO_DATE.exec(String(value ?? ''))
  if (!match) return null
  const ms = Date.UTC(Number(match[1]), Number(match[2]) - 1, Number(match[3]))
  return Number.isNaN(ms) ? null : ms
}

function toISO(ms) {
  return new Date(ms).toISOString().slice(0, 10)
}

/**
 * The date `days` away from `date`.
 * @returns {string|null} `YYYY-MM-DD`.
 */
export function addDays(date, days) {
  const ms = toUTC(date)
  if (ms === null) return null
  return toISO(ms + Math.trunc(days) * DAY_MS)
}

/**
 * The Monday of the week containing `date`, with Sunday belonging to the week
 * that just ended rather than the one about to start — which is what the
 * backend's `weekday() != 0` check assumes.
 * @returns {string|null} `YYYY-MM-DD`.
 */
export function mondayOf(date) {
  const ms = toUTC(date)
  if (ms === null) return null
  // getUTCDay(): 0 = Sunday, so Sunday walks back a full six days.
  const weekday = new Date(ms).getUTCDay()
  return toISO(ms - (weekday === 0 ? 6 : weekday - 1) * DAY_MS)
}

/**
 * Today's calendar date in `timeZone`, defaulting to the host's zone when no
 * zone is known or the one given is not a zone Intl recognises.
 * @param {string} [timeZone] - an IANA name, e.g. the site's `time_zone`.
 * @param {Date} [now] - injectable for tests.
 * @returns {string} `YYYY-MM-DD`.
 */
export function todayInTimeZone(timeZone, now = new Date()) {
  if (timeZone) {
    try {
      const parts = new Intl.DateTimeFormat('en-CA', {
        timeZone,
        year: 'numeric',
        month: '2-digit',
        day: '2-digit',
      }).formatToParts(now)
      const at = (type) => parts.find((p) => p.type === type)?.value
      const [y, m, d] = [at('year'), at('month'), at('day')]
      if (y && m && d) return `${y}-${m}-${d}`
    } catch {
      // an unknown zone throws a RangeError; fall through to the host's
    }
  }
  const pad = (n) => String(n).padStart(2, '0')
  return `${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(now.getDate())}`
}

/**
 * The seven columns of a week.
 * @param {string} weekStart - Monday, `YYYY-MM-DD`.
 * @param {string} today - `YYYY-MM-DD` in the site's timezone.
 * @returns {Array<{date: string, index: number, isToday: boolean, isWeekend: boolean, isPast: boolean}>}
 */
export function weekDayCells(weekStart, today) {
  const monday = mondayOf(weekStart)
  if (!monday) return []
  return Array.from({ length: 7 }, (_, index) => {
    const date = addDays(monday, index)
    return {
      date,
      index,
      isToday: date === today,
      isWeekend: index >= 5,
      isPast: Boolean(today) && date < today,
    }
  })
}

/**
 * Bucket plan items by the day they sit on.
 *
 * Passing `days` gives every column a key even when it is empty, so the grid
 * does not have to guard each lookup, and collects anything dated outside the
 * week — which a stale buffer or a bad reschedule can produce — into `outside`
 * rather than dropping it silently.
 *
 * @param {Array<object>} items
 * @param {Array<string>} [days] - the dates to key, in column order.
 * @returns {{byDay: Record<string, object[]>, outside: object[]}}
 */
export function groupItemsByDay(items, days = null) {
  const byDay = {}
  const outside = []
  const known = days ? new Set(days) : null
  if (days) for (const day of days) byDay[day] = []

  for (const item of items || []) {
    const date = item?.planned_date
    if (known && !known.has(date)) {
      outside.push(item)
      continue
    }
    ;(byDay[date] ||= []).push(item)
  }
  return { byDay, outside }
}

/**
 * Count items per activity type, in the shape `get_plan` returns as `rollup`.
 *
 * Same definition as the server's (`_rollup` in crm/api/rep_plan.py): every row
 * counts as planned, and Done/Missed/Cancelled additionally count in their own
 * bucket. Kept identical so the header can show the server's rollup and a
 * local recount can be asserted against it.
 *
 * @returns {Record<string, {planned: number, done: number, missed: number, cancelled: number}>}
 */
export function rollupItems(items) {
  const rollup = {}
  for (const item of items || []) {
    const type = item?.activity_type
    const bucket = (rollup[type] ||= {
      planned: 0,
      done: 0,
      missed: 0,
      cancelled: 0,
    })
    bucket.planned += 1
    if (item.status === 'Done') bucket.done += 1
    else if (item.status === 'Missed') bucket.missed += 1
    else if (item.status === 'Cancelled') bucket.cancelled += 1
  }
  return rollup
}

/**
 * Sum a per-type rollup into one set of totals.
 * @returns {{planned: number, done: number, missed: number, cancelled: number}}
 */
export function rollupTotals(rollup) {
  const totals = { planned: 0, done: 0, missed: 0, cancelled: 0 }
  for (const bucket of Object.values(rollup || {})) {
    totals.planned += bucket?.planned || 0
    totals.done += bucket?.done || 0
    totals.missed += bucket?.missed || 0
    totals.cancelled += bucket?.cancelled || 0
  }
  return totals
}

/**
 * The team week as a grid: one row per rep, each with its items bucketed by
 * day, optionally narrowed to one activity type. Reps with nothing that week
 * stay in the grid (an empty row is information for a manager) but sort after
 * the ones with work, then by name.
 *
 * @param {Array<{user: string, full_name: string, items: object[]}>} reps
 * @param {Array<string>} days - the week's dates, Monday first.
 * @param {string} [type] - an activity type, or '' for all.
 * @returns {Array<{user: string, full_name: string, byDay: Record<string, object[]>, count: number, totals: object}>}
 */
export function teamGrid(reps, days, type = '') {
  return (reps || [])
    .map((rep) => {
      const items = (rep.items || []).filter(
        (item) => !type || item.activity_type === type,
      )
      return {
        user: rep.user,
        full_name: rep.full_name || rep.user,
        byDay: groupItemsByDay(items, days).byDay,
        count: items.length,
        totals: rollupTotals(rollupItems(items)),
      }
    })
    .sort(
      (a, b) =>
        Number(b.count > 0) - Number(a.count > 0) ||
        a.full_name.localeCompare(b.full_name),
    )
}

function fingerprint(item) {
  return [
    item?.activity_type,
    item?.reference_doctype,
    item?.reference_docname,
    item?.organization,
    item?.note,
  ].join(' ')
}

/**
 * Drop the proposals the plan already holds.
 *
 * A suggestion is the identity that matters: once a draft for it is in the
 * buffer, re-proposing must not add a second copy even if the rep moved it to
 * another day. Drafts without a suggestion have no such identity, so they fall
 * back to matching on what they are about.
 *
 * @param {Array<object>} drafts - as returned by `propose_week`.
 * @param {Array<object>} existing - the items already in the buffer.
 * @returns {Array<object>} the drafts worth adding, in order.
 */
export function dedupeProposals(drafts, existing) {
  const suggestions = new Set()
  const shapes = new Set()
  for (const item of existing || []) {
    if (item?.suggestion) suggestions.add(item.suggestion)
    else shapes.add(fingerprint(item))
  }

  const fresh = []
  for (const draft of drafts || []) {
    if (draft?.suggestion) {
      if (suggestions.has(draft.suggestion)) continue
      suggestions.add(draft.suggestion)
    } else {
      const shape = fingerprint(draft)
      if (shapes.has(shape)) continue
      shapes.add(shape)
    }
    fresh.push(draft)
  }
  return fresh
}

/**
 * What the local buffer would do to the stored plan if saved now.
 *
 * Rows are matched by child `name`, the same way `_stage_items` matches them:
 * a row that keeps its name is an edit, and a row that lost it is a delete plus
 * an insert — which is why a reschedule must never drop the name.
 *
 * @returns {{added: number, removed: number, changed: number, total: number}}
 */
export function planDiff(local, server) {
  const stored = new Map(
    (server || []).filter((i) => i?.name).map((i) => [String(i.name), i]),
  )
  let added = 0
  let changed = 0
  const seen = new Set()

  for (const item of local || []) {
    const name = item?.name ? String(item.name) : ''
    const before = name && stored.get(name)
    if (!before) {
      added += 1
      continue
    }
    seen.add(name)
    if (
      EDITABLE_ITEM_FIELDS.some(
        (f) => (item[f] ?? null) !== (before[f] ?? null),
      )
    )
      changed += 1
  }

  const removed = [...stored.keys()].filter((name) => !seen.has(name)).length
  return { added, removed, changed, total: added + removed + changed }
}

/**
 * Move one item to another day without disturbing anything else about it.
 *
 * Returns a new array with a new object in place of `item`; the child `name`,
 * `suggestion` and matcher fields ride along, because a reschedule that drops
 * the name loses both the row's fulfilment state and its link back to the
 * suggestion it came from.
 *
 * @returns {Array<object>} the items, unchanged if the move is a no-op.
 */
export function moveItemToDate(items, item, date) {
  if (!date || !item || item.planned_date === date) return items || []
  let moved = false
  const next = (items || []).map((candidate) => {
    if (candidate !== item || moved) return candidate
    moved = true
    return { ...candidate, planned_date: date }
  })
  return moved ? next : items || []
}

/**
 * Whether `weekStart` is too old for the matcher, and therefore refused by
 * `save_plan`. Checked here so the Save button can be disabled with a reason
 * rather than throwing on submit.
 */
export function isBeforeHorizon(weekStart, today, weeks = MATCH_HORIZON_WEEKS) {
  const monday = mondayOf(weekStart)
  const horizon = addDays(today, -7 * weeks)
  if (!monday || !horizon) return false
  return monday < horizon
}

/**
 * The route a plan item's reference opens, or null when it references nothing
 * this app can show. Derived from the item's own doctype — treating everything
 * that is not a Deal as a Lead mislabels the row the moment a third reference
 * type exists.
 * @returns {{name: string, params: object}|null}
 */
export function referenceRoute(item) {
  const target = REFERENCE_ROUTES[item?.reference_doctype]
  if (!target || !item?.reference_docname) return null
  return {
    name: target.name,
    params: { [target.param]: item.reference_docname },
  }
}

/**
 * Split the plan's references into one list of names per doctype, for the
 * batched title lookup the grid does after a plan loads.
 * @returns {{deals: string[], leads: string[]}} distinct names, sorted.
 */
export function referenceNames(items) {
  const buckets = { 'CRM Deal': new Set(), 'CRM Lead': new Set() }
  for (const item of items || []) {
    const bucket = buckets[item?.reference_doctype]
    if (bucket && item.reference_docname) bucket.add(item.reference_docname)
  }
  return {
    deals: [...buckets['CRM Deal']].sort(),
    leads: [...buckets['CRM Lead']].sort(),
  }
}

/**
 * Only the fields the server accepts, so a save never posts matcher-owned
 * state back. `name` is kept deliberately: it is what tells `_stage_items` this
 * is the same row rescheduled rather than a replacement.
 */
export function toSavePayload(items) {
  return (items || []).map((item) => {
    const row = {}
    if (item.name) row.name = item.name
    for (const field of EDITABLE_ITEM_FIELDS) row[field] = item[field] ?? null
    return row
  })
}
