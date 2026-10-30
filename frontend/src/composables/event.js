import { usersStore } from '@/stores/users'
import { dayjs, createListResource, call } from 'frappe-ui'
import { computed, ref, watch } from 'vue'
import { allTimeSlots } from '@/components/Calendar/utils'

export const showEventModal = ref(false)
export const activeEvent = ref(null)

// Child rows are read for every listed event at once. A page that comes back
// full may have been cut short, and a short table is not shown as the event's
// own: EventModal saves what it is given, and a truncated list saved back
// deletes the rows it is missing.
const CHILD_PAGE_LENGTH = 500

export function useEvent({
  doctype,
  docname,
  filters = null,
  participants = true,
  notifications = true,
  orderBy = 'creation desc',
}) {
  const { getUser } = usersStore()

  if (!filters) {
    if (doctype && docname) {
      filters = {
        reference_doctype: doctype,
        reference_docname: docname,
      }
    } else {
      filters = {}
    }
  }

  const eventsResource = createListResource({
    doctype: 'Event',
    cache: ['calendar-events', docname],
    fields: [
      'name',
      'status',
      'subject',
      'description',
      'starts_on',
      'ends_on',
      'all_day',
      'event_type',
      'location',
      'color',
      'attending',
      'owner',
      'reference_doctype',
      'reference_docname',
      'creation',
    ],
    filters: filters,
    auto: true,
    // `pageLength`, not `limit`: createListResource never reads `limit`, so
    // this list stopped at its default of 20.
    pageLength: 50,
    orderBy,
  })

  const eventParticipantsResource = createListResource({
    doctype: 'Event Participants',
    fields: ['*'],
    parent: 'Event',
    orderBy: 'idx asc',
    pageLength: CHILD_PAGE_LENGTH,
  })

  const eventNotificationsResource = createListResource({
    doctype: 'Event Notifications',
    fields: ['*'],
    parent: 'Event',
    orderBy: 'idx asc',
    pageLength: CHILD_PAGE_LENGTH,
  })

  // The child rows of the latest load, and the events they were loaded for.
  // Kept as returned rather than read off the resources, which a slower,
  // older response could overwrite after a newer one landed.
  const children = ref(null)
  let childLoad = 0

  async function loadChildren(names) {
    if (!names?.length || !(participants || notifications)) return
    const load = ++childLoad
    const childFilters = (parentfield) => ({
      parenttype: 'Event',
      parentfield,
      parent: ['in', names],
    })
    const rowsOf = async (enabled, resource, parentfield) => {
      if (!enabled) return null
      resource.update({ filters: childFilters(parentfield) })
      const rows = await resource.reload()
      return Array.isArray(rows) && rows.length < CHILD_PAGE_LENGTH
        ? rows
        : null
    }
    try {
      const [participantRows, notificationRows] = await Promise.all([
        rowsOf(participants, eventParticipantsResource, 'event_participants'),
        rowsOf(notifications, eventNotificationsResource, 'notifications'),
      ])
      if (load !== childLoad) return
      children.value = {
        names: new Set(names),
        participants: participantRows,
        notifications: notificationRows,
      }
    } catch (error) {
      // Left unloaded: an event without its child tables is not saved with
      // empty ones (see EventModal).
      console.error('Could not load event participants and reminders', error)
    }
  }

  // Updating a list resource's filters does not fetch it: these used to be
  // .update()d inside the `events` computed and never reloaded, so the child
  // tables were never requested at all, and an edit from a record's Events
  // tab saved them back empty. Reloaded whenever the event list is.
  watch(
    () => eventsResource.data?.map((e) => e.name),
    (names) => loadChildren(names),
    { immediate: true },
  )

  const ownerOf = (owner) =>
    typeof owner === 'string'
      ? {
          label: getUser(owner).full_name,
          image: getUser(owner).user_image,
          name: owner,
        }
      : owner

  const events = computed(() => {
    if (!eventsResource.data) return []
    const loaded = children.value

    // New objects, not the list resource's rows mutated in place. A child
    // table is attached only once it has loaded for that event, so an absent
    // one reads as "not loaded" rather than as "none".
    return eventsResource.data.map((row) => {
      const event = { ...row, owner: ownerOf(row.owner) }
      if (!loaded?.names.has(event.name)) return event

      if (participants && loaded.participants) {
        event.event_participants = loaded.participants.filter(
          (participant) => participant.parent === event.name,
        )
        event.participants = [
          event.owner,
          ...event.event_participants.map((participant) =>
            // getUser() of no email is the viewer: a visit's CRM Organization
            // row has none, and is named by its reference instead
            participant.email
              ? {
                  label:
                    getUser(participant.email).full_name || participant.email,
                  image: getUser(participant.email).user_image || '',
                  name: participant.email,
                }
              : {
                  label: participant.reference_docname,
                  image: '',
                  name: participant.reference_docname,
                },
          ),
        ]
      }

      if (notifications && loaded.notifications) {
        event.notifications = loaded.notifications.filter(
          (notification) => notification.parent === event.name,
        )
      }

      return event
    })
  })

  const startEndTime = (
    startTime,
    endTime,
    isFullDay = false,
    format = 'h:mm a',
  ) => {
    const start = dayjs(startTime)
    const end = dayjs(endTime)

    if (isFullDay) return __('All Day')

    return `${start.format(format)} - ${end.format(format)}`
  }

  const startDate = (startTime, format = 'ddd, D MMM YYYY') => {
    const start = dayjs(startTime)
    return start.format(format)
  }

  return {
    eventsResource,
    eventParticipantsResource,
    events,
    startEndTime,
    startDate,
  }
}

// A placeholder docname: Attendee's typed address that names no Contact yet.
const UNRESOLVED_DOCNAMES = new Set(['', 'new'])

/**
 * The participant rows to save, from what the attendee picker holds.
 *
 * Saving replaces the child table: a row sent without its `name` is deleted
 * and inserted afresh, and a row not sent is deleted. This used to keep only
 * rows with an email, and only their email and reference, so one attendee
 * added to a planner visit dropped its e-mail-less CRM Organization row (the
 * visit's customer, which plan matching and the visit reports read) and
 * reset everyone's RSVP.
 */
export function normalizeParticipants(list = []) {
  const seen = new Set()
  const out = []
  for (const a of list || []) {
    if (!a) continue
    const reference_doctype = a.reference_doctype || 'Contact'
    const reference_docname = a.reference_docname || ''
    const key = !UNRESOLVED_DOCNAMES.has(reference_docname)
      ? `${reference_doctype}\u0000${reference_docname}`
      : a.email
    if (!key || seen.has(key)) continue
    seen.add(key)
    const row = { email: a.email || '', reference_doctype, reference_docname }
    if (a.name) row.name = a.name
    if (a.attending) row.attending = a.attending
    out.push(row)
  }
  return out
}

/**
 * Give every typed attendee a Contact before the event is saved.
 *
 * Event Participants' reference is a required Dynamic Link, and Attendee
 * hands over an address that matches no Contact as `reference_docname: 'new'`
 * (or none at all, for a comma-separated paste), which the server refuses.
 * An existing Contact with that email is used; otherwise one is created.
 */
export async function ensureParticipantContacts(participants) {
  if (!Array.isArray(participants) || !participants.length) return participants
  const updated = []
  for (const part of participants) {
    const p = { ...part }
    try {
      if (
        p.reference_doctype === 'Contact' &&
        UNRESOLVED_DOCNAMES.has(p.reference_docname || '') &&
        p.email
      ) {
        const existing = await call('frappe.client.get_value', {
          doctype: 'Contact',
          filters: { email_id: p.email },
          fieldname: 'name',
        })
        if (existing?.name) {
          p.reference_docname = existing.name
        } else {
          const firstName = p.email.split('@')[0] || p.email
          const contactDoc = await call('frappe.client.insert', {
            doc: {
              doctype: 'Contact',
              first_name: firstName,
              email_ids: [{ email_id: p.email, is_primary: 1 }],
            },
          })
          if (contactDoc?.name) p.reference_docname = contactDoc.name
        }
      }
    } catch (e) {
      console.error('Failed creating contact for participant', p.email, e)
    }
    updated.push(p)
  }
  return updated
}

export function formatDuration(mins) {
  if (mins < 60) return __('{0} mins', [mins])
  let hours = mins / 60
  if (hours % 1 !== 0 && hours % 1 !== 0.5) {
    hours = hours.toFixed(2)
  }
  if (Number.isInteger(hours)) {
    return hours === 1 ? __('1 hr') : __('{0} hrs', [hours])
  }
  return `${hours} hrs`
}

export function buildEndTimeOptions(fromTime) {
  const timeSlots = allTimeSlots()
  if (!fromTime) return timeSlots
  const startIndex = timeSlots.findIndex((o) => o.value > fromTime)
  if (startIndex === -1) return []
  const [fh, fm] = fromTime.split(':').map((n) => parseInt(n))
  const fromTotal = fh * 60 + fm
  return timeSlots.slice(startIndex).map((o) => {
    const [th, tm] = o.value.split(':').map((n) => parseInt(n))
    const toTotal = th * 60 + tm
    const duration = toTotal - fromTotal
    return { ...o, label: `${o.label} (${formatDuration(duration)})` }
  })
}

export function computeAutoToTime(fromTime) {
  if (!fromTime) return ''
  const [hour, minute] = fromTime.split(':').map((n) => parseInt(n))
  let nh = hour + 1
  let nm = minute
  if (nh >= 24) {
    nh = 23
    nm = 59
  }
  return `${String(nh).padStart(2, '0')}:${String(nm).padStart(2, '0')}`
}

export function validateTimeRange({ fromDate, fromTime, toTime, isFullDay }) {
  if (isFullDay) return { valid: true, error: null }
  if (!fromTime || !toTime) {
    return { valid: false, error: __('Start & End Time Are Required') }
  }
  const start = dayjs(fromDate + ' ' + fromTime)
  const end = dayjs(fromDate + ' ' + toTime)
  if (!start.isValid() || !end.isValid()) {
    return { valid: false, error: __('Invalid Start Or End Time') }
  }
  if (end.diff(start, 'minute') <= 0) {
    return { valid: false, error: __('End Time Should Be After Start Time') }
  }
  return { valid: true, error: null }
}

export function parseEventDoc(doc) {
  if (!doc) return {}
  const { getUser } = usersStore()

  return {
    id: doc.name,
    title: doc.subject,
    description: doc.description,
    status: doc.status,
    fromDate: dayjs(doc.starts_on).format('YYYY-MM-DD'),
    toDate: dayjs(doc.ends_on).format('YYYY-MM-DD'),
    fromTime: dayjs(doc.starts_on).format('HH:mm'),
    toTime: dayjs(doc.ends_on).format('HH:mm'),
    isFullDay: doc.all_day,
    eventType: doc.event_type,
    location: doc.location || '',
    color: doc.color,
    attending: doc.attending,
    referenceDoctype: doc.reference_doctype,
    referenceDocname: doc.reference_docname,
    event_participants: doc.event_participants || [],
    notifications: doc.notifications || [],
    owner: doc.owner
      ? {
          label: getUser(doc.owner).full_name,
          image: getUser(doc.owner).user_image,
          value: doc.owner,
        }
      : null,
  }
}
