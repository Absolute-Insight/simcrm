/**
 * Reading the field pack — the snapshot a phone keeps for sites with no
 * reception (crm/api/offline.py builds it). Pure: rows in, rows out, so the
 * rules about what a rep sees offline are tested without a browser or a pack.
 */

const DAY_MS = 86400000

/**
 * Whether a pack is too old to show.
 *
 * A phone that has not reached the server for `maxAgeDays` drops what it
 * holds: the customer may have moved to another rep since, and a lost phone
 * should not carry a customer list indefinitely. An unreadable timestamp
 * counts as expired -- the safe side.
 */
export function packExpired(syncedAt, maxAgeDays, now = Date.now()) {
  const at = Number(syncedAt)
  const days = Number(maxAgeDays)
  if (!Number.isFinite(at) || at <= 0) return true
  if (!Number.isFinite(days) || days <= 0) return true
  return now - at > days * DAY_MS
}

/** Lower-case, accents folded, punctuation to spaces: what search compares. */
export function searchKey(text) {
  return String(text ?? '')
    .normalize('NFD')
    .replace(/[̀-ͯ]/g, '')
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, ' ')
    .trim()
}

function push(map, key, row) {
  if (!key) return
  const rows = map.get(key)
  if (rows) rows.push(row)
  else map.set(key, [row])
}

/**
 * The pack's lists, keyed by customer.
 *
 * A contact names its company in free text (`company_name`), which is the
 * customer's record name on most rows and its display name on some, so a
 * customer answers to both -- the same rule the server's row scoping applies
 * (crm/permissions/customers.py).
 */
export function indexPack(pack) {
  const organizations = pack?.organizations ?? []
  const byName = new Map()
  const alias = new Map()
  for (const org of organizations) {
    byName.set(org.name, org)
    alias.set(org.name, org.name)
    if (org.organization_name && !alias.has(org.organization_name)) {
      alias.set(org.organization_name, org.name)
    }
  }

  const contacts = new Map()
  for (const contact of pack?.contacts ?? []) {
    push(contacts, alias.get(contact.company_name), contact)
  }

  const deals = new Map()
  const dealOrg = new Map()
  for (const deal of pack?.deals ?? []) {
    push(deals, deal.organization, deal)
    dealOrg.set(deal.name, deal.organization)
  }

  const history = new Map()
  for (const row of pack?.history ?? []) push(history, row.organization, row)

  const notes = new Map()
  for (const note of pack?.notes ?? []) {
    const org =
      note.reference_doctype === 'CRM Organization'
        ? note.reference_docname
        : dealOrg.get(note.reference_docname)
    push(notes, org, note)
  }

  return { byName, contacts, deals, history, notes }
}

/**
 * Customers matching what was typed, best first.
 *
 * Every word typed must appear somewhere in the name, town or territory; a
 * name that starts with the query outranks one that merely contains it, which
 * is what a rep typing "imp" for Impala expects. `limit` bounds what is
 * rendered -- a manager's pack holds every customer on the site.
 *
 * @returns {{rows: object[], total: number}}
 */
export function searchCustomers(organizations, query, limit = 60) {
  const words = searchKey(query).split(' ').filter(Boolean)
  const all = organizations ?? []
  if (!words.length) return { rows: all.slice(0, limit), total: all.length }

  const first = words.join(' ')
  const scored = []
  for (const org of all) {
    const name = searchKey(org.organization_name || org.name)
    const hay = `${name} ${searchKey(org.address?.city)} ${searchKey(org.territory)}`
    if (!words.every((word) => hay.includes(word))) continue
    const rank = name.startsWith(first) ? 0 : name.includes(first) ? 1 : 2
    scored.push({ org, rank, name })
  }
  scored.sort((a, b) => a.rank - b.rank || a.name.localeCompare(b.name))
  return {
    rows: scored.slice(0, limit).map((entry) => entry.org),
    total: scored.length,
  }
}

/** Every planned item in the pack's weeks, keyed by its `YYYY-MM-DD`. */
export function itemsByDate(plans) {
  const days = new Map()
  for (const plan of plans ?? []) {
    for (const item of plan.items ?? []) {
      push(days, String(item.planned_date ?? '').slice(0, 10), {
        ...item,
        week_start: plan.week_start,
      })
    }
  }
  return days
}

/** The Mondays the pack carries, oldest first. */
export function packWeeks(plans) {
  return (plans ?? [])
    .map((plan) => plan.week_start)
    .filter(Boolean)
    .sort()
}

/** One line of address, skipping what is blank. */
export function addressLine(address) {
  if (!address) return ''
  return [
    address.address_line1,
    address.address_line2,
    address.city,
    address.state,
    address.pincode,
    address.country,
  ]
    .map((part) => String(part ?? '').trim())
    .filter(Boolean)
    .join(', ')
}

/**
 * A `tel:` link for a number as people write it, or '' when there is nothing
 * to dial. Spaces, brackets and dashes go; a leading + stays.
 */
export function telHref(number) {
  const raw = String(number ?? '').trim()
  const digits = raw.replace(/[^\d]/g, '')
  if (digits.length < 3) return ''
  return `tel:${raw.startsWith('+') ? '+' : ''}${digits}`
}

/**
 * Open tasks in the order to do them: overdue and soonest first, undated last.
 * `today` is the site's calendar date, the one the server set the due date in.
 */
export function orderTasks(tasks, today) {
  const dueDay = (task) => String(task.due_date ?? '').slice(0, 10)
  return [...(tasks ?? [])]
    .map((task) => ({
      ...task,
      due_day: dueDay(task),
      overdue: Boolean(today) && !!dueDay(task) && dueDay(task) < today,
    }))
    .sort((a, b) => {
      if (!a.due_day !== !b.due_day) return a.due_day ? -1 : 1
      return (
        a.due_day.localeCompare(b.due_day) ||
        String(a.title ?? '').localeCompare(String(b.title ?? ''))
      )
    })
}

/**
 * When the pack was saved, relative to now, in the device's own clock and
 * locale -- "today", "yesterday" or a date, plus the time of day.
 * @returns {{day: 'today'|'yesterday'|'date', date: string, time: string}|null}
 */
export function savedWhen(syncedAt, now = Date.now(), locale = undefined) {
  const at = Number(syncedAt)
  if (!Number.isFinite(at) || at <= 0) return null
  const then = new Date(at)
  const startOf = (ms) => {
    const d = new Date(ms)
    return new Date(d.getFullYear(), d.getMonth(), d.getDate()).getTime()
  }
  const days = Math.round((startOf(now) - startOf(at)) / DAY_MS)
  return {
    day: days <= 0 ? 'today' : days === 1 ? 'yesterday' : 'date',
    date: new Intl.DateTimeFormat(locale ?? DATE_LOCALE, {
      day: 'numeric',
      month: 'short',
    }).format(then),
    // 24-hour: "16:05" fits the header pill where "04:05 PM" does not
    time: new Intl.DateTimeFormat(locale, {
      hour: '2-digit',
      minute: '2-digit',
      hourCycle: 'h23',
    }).format(then),
  }
}

const UTC_DAY = (date) => new Date(`${String(date).slice(0, 10)}T00:00:00Z`)

/* Day-then-month, as the Planner writes its dates ("9 Nov"), so the same week
   does not read "Nov 9" on one screen and "9 Nov" on the other. */
const DATE_LOCALE = 'en-GB'

/** "Mon", "Tue"… for a `YYYY-MM-DD`, without the device's zone shifting it. */
export function weekdayName(date, locale = DATE_LOCALE) {
  return new Intl.DateTimeFormat(locale, {
    weekday: 'short',
    timeZone: 'UTC',
  }).format(UTC_DAY(date))
}

/** "12 Nov" for a `YYYY-MM-DD`. */
export function shortDate(date, locale = DATE_LOCALE) {
  if (!date) return ''
  return new Intl.DateTimeFormat(locale, {
    day: 'numeric',
    month: 'short',
    timeZone: 'UTC',
  }).format(UTC_DAY(date))
}

/** A deal's value as money, or '' when there is none to show. */
export function moneyLabel(value, currency, locale = undefined) {
  const amount = Number(value)
  if (!Number.isFinite(amount) || amount === 0) return ''
  try {
    return new Intl.NumberFormat(locale, {
      style: 'currency',
      currency: currency || 'USD',
      maximumFractionDigits: 0,
    }).format(amount)
  } catch {
    // a currency code Intl does not know: the number still means something
    return `${currency || ''} ${Math.round(amount).toLocaleString(locale)}`.trim()
  }
}

const sameText = (a, b) => searchKey(a) === searchKey(b)

/**
 * The two lines of a plan item: what it is called, and what was written about
 * how it went.
 *
 * An activity logged after the fact stores one account twice -- whole in
 * `outcome`, its first line in `note` (log_unplanned_visit) -- so showing both
 * repeats the sentence. The note leads, as on the Planner's cards; the outcome
 * follows only when it says more than the note did.
 *
 * @param {object} item a plan item row
 * @param {string} fallback what to call it when it has no note
 * @returns {{title: string, detail: string}}
 */
export function planItemText(item, fallback) {
  const note = String(item?.note ?? '').trim()
  const outcome = String(item?.outcome ?? '').trim()
  if (!note) return { title: fallback, detail: outcome }
  if (!outcome || sameText(note, outcome)) return { title: note, detail: '' }
  // the note is the outcome cut to one line: the whole account says it better
  const stem = searchKey(note.replace(/…$/, ''))
  if (stem && searchKey(outcome).startsWith(stem)) {
    return { title: fallback, detail: outcome }
  }
  return { title: note, detail: outcome }
}
