/**
 * Pure helpers for the suggestion inbox and the per-record "Needs attention"
 * panel.
 *
 * Two numbers travel through this surface and they run in opposite directions:
 * a suggestion's `score` is *urgency* (higher = more pressing, see the Urgency
 * field description on CRM Suggestion) while a deal's health score is
 * *wellbeing* (higher = healthier, `crm.agent.predict.score_deal` starts at 100
 * and subtracts). Rendering both as a colour-coded integer made them look like
 * the same measurement read two different ways, so they are deliberately given
 * different shapes here: urgency resolves to a word, health to a meter with an
 * explicit denominator. Nothing in the UI should print a bare suggestion score.
 */

/* Explicit, not a ternary on "is it a Deal": the inbox used to send every
   non-Deal suggestion to the Lead route, so a suggestion on any third doctype
   opened an unrelated record under a confident-looking link. An unmapped
   doctype gets no link at all. */
const REFERENCE_ROUTES = {
  'CRM Deal': (docname) => ({ name: 'Deal', params: { dealId: docname } }),
  'CRM Lead': (docname) => ({ name: 'Lead', params: { leadId: docname } }),
}

/* Which field carries the human name of a record, per doctype. Mirrors the
   `_label()` calls in crm/agent/signals.py so a suggestion's title and its
   reference line name the same thing. */
const LABEL_FIELDS = {
  'CRM Deal': ['organization'],
  'CRM Lead': ['lead_name', 'organization'],
}

export const URGENCY_HIGH = 70
export const URGENCY_MEDIUM = 40

export const HEALTH_HEALTHY = 70
export const HEALTH_AT_RISK = 40

// CRM Suggestion.dismiss_reason is a Small Text and get_dismissal_stats shows
// it to an administrator verbatim; keep a bound on what we write into it.
export const DISMISS_NOTE_MAX = 400

/**
 * A score to band, or null when there is nothing to band.
 *
 * Both bands must refuse anything that is not a real number rather than coerce
 * it: an absent score and a score of zero mean completely different things
 * ("not assessed" vs "critical"), and `Number(null)` is 0.
 */
function toScore(value) {
  if (value === null || value === undefined || value === '') return null
  const number = Number(value)
  return Number.isFinite(number) ? number : null
}

export function suggestionRoute(doctype, docname) {
  const build = REFERENCE_ROUTES[doctype]
  if (!build || !docname) return null
  return build(docname)
}

export function referenceTypeLabel(doctype) {
  // Only the doctypes this app has a page for get a translated noun. Anything
  // else is named by its raw doctype rather than mislabelled as a guess.
  if (doctype === 'CRM Deal') return __('Deal')
  if (doctype === 'CRM Lead') return __('Lead')
  return doctype || ''
}

export function labelFieldsFor(doctype) {
  return LABEL_FIELDS[doctype] || []
}

export function pickReferenceLabel(doctype, row) {
  for (const fieldname of labelFieldsFor(doctype)) {
    const value = row?.[fieldname]
    if (value) return String(value)
  }
  return row?.name ? String(row.name) : ''
}

export function referenceKey(doctype, docname) {
  return `${doctype || ''}:${docname || ''}`
}

/**
 * Group the rows that still need a human name, by doctype.
 *
 * `already` is the resolved-label cache, so a scroll or a socket refresh only
 * asks the server about references it has never seen.
 */
export function pendingReferences(rows, already = {}) {
  const out = {}
  for (const row of rows || []) {
    const { reference_doctype: doctype, reference_docname: docname } = row
    if (!docname || !labelFieldsFor(doctype).length) continue
    if (already[referenceKey(doctype, docname)]) continue
    const names = (out[doctype] ||= [])
    if (!names.includes(docname)) names.push(docname)
  }
  return out
}

function parseJSONField(raw) {
  if (raw == null) return null
  if (typeof raw !== 'string') return raw
  try {
    return JSON.parse(raw)
  } catch {
    return null
  }
}

/**
 * The `factors` JSON on a suggestion, as a list of `{key, label, value}`.
 *
 * Older rows hold a bare `{key: value}` dict from before the list shape landed.
 * Those are dropped rather than rendered: turning a dict into rows would print
 * raw field keys at the reader, which is the thing the list shape exists to
 * stop. The rationale sentence still explains the suggestion in that case.
 */
export function parseFactors(raw) {
  const parsed = parseJSONField(raw)
  if (!Array.isArray(parsed)) return []
  return parsed.filter((factor) => factor && typeof factor.label === 'string')
}

export function parseActionPayload(raw) {
  const parsed = parseJSONField(raw)
  return parsed && typeof parsed === 'object' && !Array.isArray(parsed)
    ? parsed
    : {}
}

export function acceptLabel(action) {
  switch (action) {
    case 'create_task':
      return __('Create task')
    case 'schedule_call':
      return __('Schedule call')
    case 'send_reply':
      return __('Draft reply')
    case 'update_field':
      return __('Update field')
    default:
      return __('Accept')
  }
}

/**
 * Urgency as a word. Never as the raw number: 82 and 82 mean opposite things
 * depending on whether you are reading a suggestion or a deal.
 *
 * The `-9` step is deliberate, and low steps are the trap. A frappe-ui colour
 * ink ramp is a readability ladder, not a lightness one: it runs light-to-dark
 * in light mode and dark-to-light in dark mode, so a low step is a background
 * tint in *both*. `text-ink-red-3` measured 1.24:1 on the light surface -- it
 * only ever looked right because this was built dark-mode-first. Measured
 * against every surface these land on, `-9` never drops below 6.3:1 in either
 * mode, where `-8` grazes the AA floor on a tinted stat tile (4.41:1). Orange
 * rather than amber for the middle band: no amber step reaches 4.5 on a light
 * surface at all, amber-8 tops out at 3.6.
 */
export function urgencyBand(score) {
  const value = toScore(score)
  if (value === null) return null
  if (value >= URGENCY_HIGH) {
    return { key: 'high', label: __('Urgent'), ink: 'text-ink-red-9' }
  }
  if (value >= URGENCY_MEDIUM) {
    return { key: 'medium', label: __('Soon'), ink: 'text-ink-orange-9' }
  }
  return { key: 'low', label: __('Low'), ink: 'text-ink-gray-5' }
}

/**
 * Health as a severity word plus the classes for a meter fill.
 *
 * The word is what carries the severity: hue alone is lost to a colour-blind
 * reader and to greyscale print, and this number is the most product-defining
 * one in the record view.
 */
export function healthBand(score) {
  const value = toScore(score)
  if (value === null) return null
  if (value >= HEALTH_HEALTHY) {
    return {
      key: 'healthy',
      label: __('Healthy'),
      fill: 'bg-surface-green-3',
      ink: 'text-ink-green-9',
    }
  }
  if (value >= HEALTH_AT_RISK) {
    return {
      key: 'at_risk',
      label: __('At risk'),
      fill: 'bg-surface-amber-2',
      ink: 'text-ink-orange-9',
    }
  }
  return {
    key: 'critical',
    label: __('Critical'),
    fill: 'bg-surface-red-4',
    ink: 'text-ink-red-9',
  }
}

export function healthMeterPercent(score) {
  const value = Number(score)
  if (!Number.isFinite(value)) return 0
  return Math.max(0, Math.min(100, Math.round(value)))
}

/**
 * Dismissal reasons, as stable keys with translated labels.
 *
 * The key is what gets stored, not the label: the signal engine stretches a
 * repeat dismisser's cooldown from these rows and an administrator reads them
 * back through `crm.api.suggestions.get_dismissal_stats`, so the stored text
 * must not change with the reader's language.
 */
export function dismissReasonOptions() {
  return [
    { value: 'not_relevant', label: __('Not relevant') },
    { value: 'already_handled', label: __('Already handled') },
    { value: 'bad_timing', label: __('Bad timing') },
    { value: 'wrong_record', label: __('Wrong record') },
    { value: 'other', label: __('Something else') },
  ]
}

export function composeDismissReason(choice, note) {
  const key = String(choice || '').trim()
  const text = String(note || '')
    .trim()
    .slice(0, DISMISS_NOTE_MAX)
  if (!key && !text) return null
  if (!text) return key
  if (!key) return text
  return `${key}: ${text}`
}

/** What to tell the rep when the agent tier could not write them a draft. */
export function draftStatusMessage(status) {
  if (status === 'disabled') {
    return __(
      'The assistant is switched off, so there is no draft to start from. Write the reply yourself and send it as usual.',
    )
  }
  if (status === 'unavailable') {
    return __(
      'The assistant could not be reached, so there is no draft to start from. Write the reply yourself, or try again later.',
    )
  }
  return ''
}

export function isDraftUsable(result) {
  return result?.status === 'ok' && Boolean(result.draft)
}

function pad(value) {
  return String(value).padStart(2, '0')
}

export function formatLocalDatetime(date) {
  return (
    `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}` +
    ` ${pad(date.getHours())}:${pad(date.getMinutes())}:00`
  )
}

/** Tomorrow at `hour`, as a default for a call that has to be put somewhere. */
export function nextMorning(now = new Date(), hour = 9) {
  const when = new Date(now.getTime())
  when.setDate(when.getDate() + 1)
  when.setHours(hour, 0, 0, 0)
  return formatLocalDatetime(when)
}

function reference(suggestion) {
  return {
    reference_doctype: suggestion.reference_doctype,
    reference_docname: suggestion.reference_docname,
  }
}

export function buildTaskDoc(suggestion, data) {
  return {
    doctype: 'CRM Task',
    ...reference(suggestion),
    status: 'Todo',
    ...data,
  }
}

export function buildCallEventDoc(suggestion, data) {
  // An Event, not a CRM Call Log: a call log records a call that happened (its
  // from/to numbers are mandatory), while this action schedules one that has
  // not. The Calendar page already reads Events by reference_doctype/docname,
  // so the scheduled call shows up where the rep looks for their day.
  return {
    doctype: 'Event',
    ...reference(suggestion),
    event_category: 'Call',
    event_type: 'Private',
    status: 'Open',
    subject: data.subject,
    starts_on: data.starts_on,
    description: data.description || '',
  }
}

export function buildEmailArgs(suggestion, data, sender) {
  return {
    recipients: data.recipients,
    subject: data.subject,
    content: data.content,
    doctype: suggestion.reference_doctype,
    name: suggestion.reference_docname,
    send_email: 1,
    sender: sender || undefined,
  }
}

/**
 * The field a `update_field` suggestion wants changed, or null when its payload
 * does not name one. Null is a refusal, not a fallback — silently degrading to
 * "create a task instead" is how every typed action ended up as a task.
 */
export function fieldUpdateSpec(payload) {
  const fieldname = payload?.fieldname || payload?.field
  if (!fieldname) return null
  return {
    fieldname,
    fieldtype: payload.fieldtype || 'Data',
    label: payload.label || fieldname,
    options: payload.options || '',
    value: payload.value ?? '',
  }
}
