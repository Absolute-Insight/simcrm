/**
 * The outbox, as data: what an entry is, what the screens show while it waits,
 * and what a failure means for it. Pure, so the rules are tested without a
 * device or a server. offline/outbox.js is the part that stores and sends.
 *
 * An entry is one thing a rep did -- logged a visit, closed an item, wrote a
 * note -- captured with an id of its own and the time it happened. The server
 * applies each id once however often it is sent (crm.api.offline.replay), so
 * the only question on this side is whether to send it again.
 */
import { mondayOf } from '@/utils/planner'

export const ACTIONS = [
  'log_activity',
  'complete_item',
  'cancel_item',
  'add_note',
  'create_task',
  'close_task',
  'plan_item',
]

/* NOTE_TEXT_LIMIT and TITLE_LIMIT in crm/api/offline.py. */
export const TEXT_LIMIT = 5000
export const TITLE_LIMIT = 140
/* NOTE_LIMIT in crm/api/rep_plan.py: a plan item's one-line note. */
const NOTE_LINE = 140

/**
 * A new entry.
 * `id` is what makes a retry safe, so it is made here, once, and never again.
 */
export function newEntry(action, payload, { id, user, capturedAt }) {
  return {
    id,
    user,
    action,
    payload,
    captured_at: capturedAt,
    status: 'pending',
    error: null,
    attempts: 0,
  }
}

/** A fresh id for an entry: a UUID where the browser has one. */
export function newEntryId(cryptoObject = globalThis.crypto) {
  if (typeof cryptoObject?.randomUUID === 'function') {
    return cryptoObject.randomUUID()
  }
  // Older WebViews, and any page not in a secure context. Collisions are the
  // server's to refuse; this only has to be long and unguessable enough.
  const bytes = new Uint8Array(16)
  if (typeof cryptoObject?.getRandomValues === 'function') {
    cryptoObject.getRandomValues(bytes)
  } else {
    for (let i = 0; i < bytes.length; i++) bytes[i] = Math.random() * 256
  }
  return Array.from(bytes, (b) => b.toString(16).padStart(2, '0')).join('')
}

const text = (value) => String(value ?? '').trim()

/**
 * What is wrong with an entry before it is saved, in words for the form, or ''.
 * The server checks all of this again; this is so a rep with no signal is told
 * now, not on Monday when the phone finds a network.
 * @param {object} rules the pack's `rules`
 */
export function entryProblem(action, payload, rules = {}) {
  const tooLong = (value, limit) => text(value).length > limit
  switch (action) {
    case 'log_activity': {
      if (!text(payload.note)) return __('Say what happened.')
      if (tooLong(payload.note, TEXT_LIMIT)) return __('That is too long.')
      const visitKinds = rules.event_kinds ?? [
        'Visit',
        'Unplanned Meeting',
        'Delivery',
      ]
      if (visitKinds.includes(payload.activity_type) && !payload.organization) {
        return __('Choose the customer.')
      }
      return ''
    }
    case 'complete_item':
      if (!text(payload.outcome)) return __('Say what happened.')
      return tooLong(payload.outcome, TEXT_LIMIT) ? __('That is too long.') : ''
    case 'cancel_item':
      if (!text(payload.reason)) return __('Say why it was cancelled.')
      return tooLong(payload.reason, TEXT_LIMIT) ? __('That is too long.') : ''
    case 'add_note':
      if (!text(payload.content)) return __('Write the note first.')
      if (tooLong(payload.title, TITLE_LIMIT)) {
        return __('Keep the title under {0} characters.', [TITLE_LIMIT])
      }
      return tooLong(payload.content, TEXT_LIMIT) ? __('That is too long.') : ''
    case 'create_task':
      if (!text(payload.title)) return __('Give the task a title.')
      if (tooLong(payload.title, TITLE_LIMIT)) {
        return __('Keep the title under {0} characters.', [TITLE_LIMIT])
      }
      return tooLong(payload.description, TEXT_LIMIT)
        ? __('That is too long.')
        : ''
    case 'plan_item': {
      if (!payload.planned_date) return __('Choose the day.')
      if (tooLong(payload.note, TITLE_LIMIT)) {
        return __('Keep the note under {0} characters.', [TITLE_LIMIT])
      }
      const visitKinds = rules.event_kinds ?? ['Visit', 'Delivery']
      if (visitKinds.includes(payload.activity_type) && !payload.organization) {
        return __('Choose the customer.')
      }
      return ''
    }
    case 'close_task':
      if (!text(payload.closing_note)) return __('Say how it was finished.')
      return tooLong(payload.closing_note, TEXT_LIMIT)
        ? __('That is too long.')
        : ''
    default:
      return __('That cannot be done offline.')
  }
}

/** A note cut to the one line a plan item's title holds, as the server cuts it. */
export function oneLine(value) {
  const line = text(value).split(/\s+/).join(' ')
  return line.length <= NOTE_LINE
    ? line
    : `${line.slice(0, NOTE_LINE - 1).trimEnd()}…`
}

/* RECEIPT_DAYS in crm/fcrm/doctype/crm_offline_receipt: how long the server
   remembers that it applied an entry. One older than that could be applied a
   second time, so neither side sends or takes it without a person's say. A
   unit test reads the Python and fails when the two drift. */
export const OUTBOX_MAX_AGE_DAYS = 90

/** Captured too long ago for the server to still know whether it applied it. */
export function entryExpired(entry, now = Date.now()) {
  const at = Number(entry?.captured_at)
  if (!Number.isFinite(at)) return false
  return now - at > OUTBOX_MAX_AGE_DAYS * 24 * 60 * 60 * 1000
}

const REFUSAL_STATUS = [403, 404, 409, 417]
const REFUSAL_EXC = /Validation|Permission|DoesNotExist|Mandatory|Duplicate/
/* A 5xx Frappe wrote for these is the database being busy, not this entry. */
const PASSING_EXC = /Deadlock|Timeout|Timed|Operational|Interface|TooMany/

/**
 * Why a send failed. One of:
 *
 * - `refused`: Frappe read the entry and said no. Only an answer Frappe wrote
 *   -- one that names its exception -- counts. A bare 403 or 404 is a captive
 *   portal at a site gate, a firewall page, a proxy mid-deploy: it says
 *   nothing about the entry, exactly as a bare 403 says nothing about the
 *   session to the handshake (offline/connectivity.js).
 * - `between`: that bare 403 / 404 / 409 / 417. Something answered, and it was
 *   not the server.
 * - `token`: the page's CSRF token is not this session's any more.
 * - `network`: it never left, or no answer came.
 * - `fault`: the server itself fell over on this entry (a 5xx carrying
 *   Frappe's exception). Once is a bad moment; every time is the entry.
 * - `busy`: anything else that may pass next time -- a gateway's 502, a rate
 *   limit, a record that changed under the entry.
 */
export function failureCause(error) {
  const status = Number(error?.status ?? error?.httpStatus)
  const exc = String(error?.exc_type ?? '')
  if (exc === 'CSRFTokenError') return 'token'
  // The record changed while this entry was being applied -- a week edited on
  // the desktop in the same instant. Nothing is wrong with the entry; the
  // next attempt is a new request and sees the record as it now is.
  if (exc === 'TooManyRequestsError' || exc === 'TimestampMismatchError') {
    return 'busy'
  }
  if (status === 429) return 'busy'
  if (status >= 500) return exc && !PASSING_EXC.test(exc) ? 'fault' : 'busy'
  if (REFUSAL_STATUS.includes(status)) return exc ? 'refused' : 'between'
  if (REFUSAL_EXC.test(exc)) return 'refused'
  if (!Number.isFinite(status) || status === 0) return 'network'
  return 'busy'
}

/**
 * What a failed send means for the entry.
 *
 * - `rejected`: the server read it and said no -- the item is gone, the
 *   customer is someone else's now, the note was empty. Sending it again will
 *   get the same answer, so it waits for the rep.
 * - `retry`: it never arrived, or arrived at a server that could not deal with
 *   anything just then. It stays pending and the queue stops; order matters,
 *   and the next entry would meet the same wall.
 *
 * Frappe answers a refusal with 403 / 404 / 409 / 417 and names the exception;
 * a lapsed session is also a 403, which the caller tells apart first.
 */
export function failureKind(error) {
  return failureCause(error) === 'refused' ? 'rejected' : 'retry'
}

/**
 * The pack as the screens should show it: what the server last said, with the
 * rep's own unsent work laid over it.
 *
 * Only entries still on their way count (`pending`, and `sent` until the next
 * sync confirms them). A rejected entry is not shown as done anywhere but the
 * outbox -- the server said it did not happen.
 *
 * @param {object|null} pack
 * @param {object[]} entries
 * @param {(ms: number) => string} dateOf the site's calendar date for an instant
 */
export function applyOutbox(pack, entries, dateOf) {
  const live = (entries ?? []).filter(
    (entry) => entry.status === 'pending' || entry.status === 'sent',
  )
  if (!pack || !live.length) return pack

  const closed = new Map()
  const planned = []
  const logged = []
  const notes = []
  const newTasks = []
  const closedTasks = new Set()

  for (const entry of live) {
    const { payload } = entry
    const date = dateOf(entry.captured_at)
    if (entry.action === 'log_activity') {
      logged.push({
        name: `outbox:${entry.id}`,
        activity_type: payload.activity_type,
        planned_date: date,
        note: oneLine(payload.note),
        organization: payload.organization || null,
        reference_doctype: payload.reference_doctype || null,
        reference_docname: payload.reference_docname || null,
        outcome: text(payload.note),
        status: 'Done',
        manual_override: 1,
        pending: true,
      })
    } else if (entry.action === 'plan_item') {
      planned.push({
        name: `outbox:${entry.id}`,
        activity_type: payload.activity_type,
        planned_date: payload.planned_date,
        note: text(payload.note),
        organization: payload.organization || null,
        status: 'Planned',
        pending: true,
      })
    } else if (entry.action === 'complete_item') {
      closed.set(payload.item, {
        status: 'Done',
        outcome: text(payload.outcome),
      })
    } else if (entry.action === 'cancel_item') {
      closed.set(payload.item, {
        status: 'Cancelled',
        outcome: text(payload.reason),
      })
    } else if (entry.action === 'add_note') {
      notes.push({
        name: `outbox:${entry.id}`,
        title:
          text(payload.title) || oneLine(text(payload.content).split('\n')[0]),
        content: text(payload.content),
        reference_doctype: payload.reference_doctype,
        reference_docname: payload.reference_docname,
        modified: date,
        pending: true,
      })
    } else if (entry.action === 'create_task') {
      newTasks.push({
        name: `outbox:${entry.id}`,
        title: text(payload.title),
        status: 'Todo',
        priority: null,
        due_date: payload.due_date || null,
        description: text(payload.description),
        pending: true,
      })
    } else if (entry.action === 'close_task') {
      closedTasks.add(String(payload.task))
    }
  }

  const justClosed = []
  const plans = (pack.plans ?? []).map((plan) => {
    const items = (plan.items ?? []).map((item) => {
      const change = closed.get(item.name)
      if (!change) return item
      const next = { ...item, ...change, manual_override: 1, pending: true }
      justClosed.push(next)
      return next
    })
    const added = [...logged, ...planned].filter(
      (item) => mondayOf(item.planned_date) === plan.week_start,
    )
    return added.length || items.some((item, i) => item !== plan.items[i])
      ? { ...plan, items: [...items, ...added] }
      : plan
  })

  const history = [
    ...[...logged, ...justClosed].filter((item) => item.organization),
    ...(pack.history ?? []).filter((row) => !closed.has(row.name)),
  ]

  return {
    ...pack,
    plans,
    history,
    notes: [...notes, ...(pack.notes ?? [])],
    tasks: [
      ...(pack.tasks ?? []).filter(
        (task) => !closedTasks.has(String(task.name)),
      ),
      ...newTasks,
    ],
  }
}

/** A line for the outbox list: what this entry is, in the rep's terms. */
export function describeEntry(
  entry,
  { customerName, taskTitle, activityLabel },
) {
  const { action, payload } = entry
  const at = (name) => (name ? customerName(name) : '')
  switch (action) {
    case 'log_activity': {
      const kind = activityLabel(payload.activity_type)
      return {
        title: payload.organization
          ? `${kind} · ${at(payload.organization)}`
          : kind,
        detail: text(payload.note),
      }
    }
    case 'complete_item':
      return { title: __('Outcome logged'), detail: text(payload.outcome) }
    case 'cancel_item':
      return { title: __('Activity cancelled'), detail: text(payload.reason) }
    case 'add_note':
      return {
        title:
          payload.reference_doctype === 'CRM Organization'
            ? __('Note · {0}', [at(payload.reference_docname)])
            : __('Note · {0}', [payload.reference_docname]),
        detail: text(payload.content),
      }
    case 'plan_item': {
      const kind = activityLabel(payload.activity_type)
      return {
        title: __('Planned · {0}', [
          payload.organization ? `${kind} · ${at(payload.organization)}` : kind,
        ]),
        detail: [payload.planned_date, text(payload.note)]
          .filter(Boolean)
          .join(' — '),
      }
    }
    case 'create_task':
      return { title: __('New task'), detail: text(payload.title) }
    case 'close_task':
      return {
        title: __('Task done'),
        detail: [taskTitle(payload.task), text(payload.closing_note)]
          .filter(Boolean)
          .join(' — '),
      }
    default:
      return { title: action, detail: '' }
  }
}
