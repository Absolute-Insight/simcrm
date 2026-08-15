import { describe, it, expect } from 'vitest'
import {
  acceptLabel,
  buildCallEventDoc,
  buildEmailArgs,
  buildTaskDoc,
  composeDismissReason,
  DISMISS_NOTE_MAX,
  dismissReasonOptions,
  displayReferenceLabel,
  shortRecordId,
  draftStatusMessage,
  fieldUpdateSpec,
  formatLocalDatetime,
  healthBand,
  healthMeterPercent,
  isDraftUsable,
  labelFieldsFor,
  nextMorning,
  parseActionPayload,
  parseFactors,
  pendingReferences,
  pickReferenceLabel,
  referenceKey,
  referenceTypeLabel,
  suggestionRoute,
  urgencyBand,
} from '@/utils/suggestions'

describe('suggestionRoute', () => {
  it('routes a deal to the Deal page', () => {
    expect(suggestionRoute('CRM Deal', 'D-1')).toEqual({
      name: 'Deal',
      params: { dealId: 'D-1' },
    })
  })

  it('routes a lead to the Lead page', () => {
    expect(suggestionRoute('CRM Lead', 'L-1')).toEqual({
      name: 'Lead',
      params: { leadId: 'L-1' },
    })
  })

  it('refuses to guess a route for an unmapped doctype', () => {
    expect(suggestionRoute('CRM Task', 'T-1')).toBeNull()
    expect(suggestionRoute('Contact', 'C-1')).toBeNull()
  })

  it('returns null without a docname', () => {
    expect(suggestionRoute('CRM Deal', '')).toBeNull()
  })
})

describe('referenceTypeLabel', () => {
  it('names the two mapped doctypes', () => {
    expect(referenceTypeLabel('CRM Deal')).toBe('Deal')
    expect(referenceTypeLabel('CRM Lead')).toBe('Lead')
  })

  it('falls back to the raw doctype rather than mislabelling it', () => {
    expect(referenceTypeLabel('CRM Task')).toBe('CRM Task')
    expect(referenceTypeLabel(undefined)).toBe('')
  })
})

describe('reference labels', () => {
  it('knows which field carries the human name', () => {
    expect(labelFieldsFor('CRM Deal')).toEqual(['organization'])
    expect(labelFieldsFor('CRM Lead')).toEqual(['lead_name', 'organization'])
    expect(labelFieldsFor('CRM Task')).toEqual([])
  })

  it('picks the first populated label field', () => {
    expect(
      pickReferenceLabel('CRM Lead', { name: 'L-1', organization: 'Acme' }),
    ).toBe('Acme')
    expect(
      pickReferenceLabel('CRM Lead', {
        name: 'L-1',
        lead_name: 'Ada',
        organization: 'Acme',
      }),
    ).toBe('Ada')
  })

  it('falls back to the primary key when no label field is set', () => {
    expect(pickReferenceLabel('CRM Deal', { name: 'D-1' })).toBe('D-1')
    expect(pickReferenceLabel('CRM Task', { name: 'T-1' })).toBe('T-1')
  })

  it('groups only the references it can label and has not resolved', () => {
    const rows = [
      { reference_doctype: 'CRM Deal', reference_docname: 'D-1' },
      { reference_doctype: 'CRM Deal', reference_docname: 'D-1' },
      { reference_doctype: 'CRM Deal', reference_docname: 'D-2' },
      { reference_doctype: 'CRM Lead', reference_docname: 'L-1' },
      { reference_doctype: 'CRM Task', reference_docname: 'T-1' },
      { reference_doctype: 'CRM Deal', reference_docname: '' },
    ]
    const already = { [referenceKey('CRM Deal', 'D-2')]: 'Acme' }
    expect(pendingReferences(rows, already)).toEqual({
      'CRM Deal': ['D-1'],
      'CRM Lead': ['L-1'],
    })
  })

  it('handles no rows', () => {
    expect(pendingReferences(undefined)).toEqual({})
    expect(pendingReferences([])).toEqual({})
  })
})

describe('shortRecordId', () => {
  it('takes the trailing serial of a frappe autoname', () => {
    expect(shortRecordId('CRM-DEAL-2026-00042')).toBe('#00042')
    expect(shortRecordId('_T-CRM Deal-00646')).toBe('#00646')
  })

  it('returns the whole docname when the tail is not numeric', () => {
    expect(shortRecordId('acme-renewal')).toBe('acme-renewal')
    expect(shortRecordId('')).toBe('')
  })
})

describe('displayReferenceLabel', () => {
  const labels = {
    'CRM Deal:D-00001': 'Acme Corp',
    'CRM Deal:D-00002': 'Acme Corp',
    'CRM Deal:D-00003': 'Globex',
    'CRM Lead:L-00004': 'Acme Corp',
  }

  it('appends the short id when two records of a doctype share a name', () => {
    // three deals at one org must not read as one deal three times
    expect(displayReferenceLabel(labels, 'CRM Deal', 'D-00001')).toBe(
      'Acme Corp · #00001',
    )
    expect(displayReferenceLabel(labels, 'CRM Deal', 'D-00002')).toBe(
      'Acme Corp · #00002',
    )
  })

  it('leaves an unambiguous label clean', () => {
    expect(displayReferenceLabel(labels, 'CRM Deal', 'D-00003')).toBe('Globex')
  })

  it('does not treat a lead and a deal at the same org as a collision', () => {
    // the UI already prefixes the doctype ("Deal ·" / "Lead ·")
    expect(displayReferenceLabel(labels, 'CRM Lead', 'L-00004')).toBe(
      'Acme Corp',
    )
  })

  it('returns empty for an unresolved or absent label', () => {
    expect(displayReferenceLabel(labels, 'CRM Deal', 'D-99999')).toBe('')
    expect(displayReferenceLabel(null, 'CRM Deal', 'D-00001')).toBe('')
  })
})

describe('parseFactors', () => {
  it('parses the list shape the signal engine writes', () => {
    const raw = JSON.stringify([
      { key: 'idle_days', label: 'No activity for 14 days', value: 14 },
    ])
    expect(parseFactors(raw)).toEqual([
      { key: 'idle_days', label: 'No activity for 14 days', value: 14 },
    ])
  })

  it('accepts an already-parsed array', () => {
    expect(parseFactors([{ key: 'a', label: 'A' }])).toHaveLength(1)
  })

  it('drops entries with no label so raw keys never reach the reader', () => {
    expect(parseFactors([{ key: 'a' }, { key: 'b', label: 'B' }])).toEqual([
      { key: 'b', label: 'B' },
    ])
  })

  it('drops the legacy bare-dict shape rather than rendering its keys', () => {
    expect(parseFactors(JSON.stringify({ idle_days: 14 }))).toEqual([])
  })

  it('survives null and malformed JSON', () => {
    expect(parseFactors(null)).toEqual([])
    expect(parseFactors('{not json')).toEqual([])
  })
})

describe('parseActionPayload', () => {
  it('parses an object payload', () => {
    expect(parseActionPayload('{"title":"Call Acme"}')).toEqual({
      title: 'Call Acme',
    })
  })

  it('returns an empty object for anything that is not an object', () => {
    expect(parseActionPayload(null)).toEqual({})
    expect(parseActionPayload('[]')).toEqual({})
    expect(parseActionPayload('nope')).toEqual({})
  })
})

describe('acceptLabel', () => {
  it('names the verb for each declared action', () => {
    expect(acceptLabel('create_task')).toBe('Create task')
    expect(acceptLabel('schedule_call')).toBe('Schedule call')
    expect(acceptLabel('send_reply')).toBe('Draft reply')
    expect(acceptLabel('update_field')).toBe('Update field')
  })

  it('falls back for an unknown action', () => {
    expect(acceptLabel('teleport')).toBe('Accept')
    expect(acceptLabel(undefined)).toBe('Accept')
  })
})

describe('urgencyBand', () => {
  it('reads high as urgent — higher score means more pressing', () => {
    expect(urgencyBand(95).key).toBe('high')
    expect(urgencyBand(70).key).toBe('high')
    expect(urgencyBand(69.9).key).toBe('medium')
    expect(urgencyBand(40).key).toBe('medium')
    expect(urgencyBand(39).key).toBe('low')
    expect(urgencyBand(0).key).toBe('low')
  })

  it('resolves to a word, not a number', () => {
    expect(urgencyBand(95).label).toBe('Urgent')
    expect(urgencyBand(50).label).toBe('Soon')
    expect(urgencyBand(10).label).toBe('Low')
  })

  it('returns null when there is no score to band', () => {
    expect(urgencyBand(null)).toBeNull()
    expect(urgencyBand(undefined)).toBeNull()
    expect(urgencyBand('high')).toBeNull()
  })
})

describe('healthBand', () => {
  it('runs the opposite way from urgency — higher score is healthier', () => {
    expect(healthBand(90).key).toBe('healthy')
    expect(healthBand(70).key).toBe('healthy')
    expect(healthBand(69).key).toBe('at_risk')
    expect(healthBand(40).key).toBe('at_risk')
    expect(healthBand(39).key).toBe('critical')
    expect(healthBand(0).key).toBe('critical')
  })

  it('carries a severity word so hue is never the only encoding', () => {
    expect(healthBand(90).label).toBe('Healthy')
    expect(healthBand(50).label).toBe('At risk')
    expect(healthBand(10).label).toBe('Critical')
  })

  it('is null when there is no score', () => {
    expect(healthBand(null)).toBeNull()
    expect(healthBand('x')).toBeNull()
  })
})

describe('healthMeterPercent', () => {
  it('clamps to the 0-100 track', () => {
    expect(healthMeterPercent(50)).toBe(50)
    expect(healthMeterPercent(-10)).toBe(0)
    expect(healthMeterPercent(140)).toBe(100)
    expect(healthMeterPercent(62.4)).toBe(62)
  })

  it('is zero for an absent score', () => {
    expect(healthMeterPercent(undefined)).toBe(0)
  })
})

describe('dismissal reasons', () => {
  it('offers stable keys with translated labels', () => {
    const options = dismissReasonOptions()
    expect(options.map((o) => o.value)).toEqual([
      'not_relevant',
      'already_handled',
      'bad_timing',
      'wrong_record',
      'other',
    ])
    expect(options.every((o) => o.label)).toBe(true)
  })

  it('stores the key alone when there is no note', () => {
    expect(composeDismissReason('not_relevant', '')).toBe('not_relevant')
    expect(composeDismissReason('not_relevant', '   ')).toBe('not_relevant')
  })

  it('appends a note to the key', () => {
    expect(composeDismissReason('other', 'they already signed')).toBe(
      'other: they already signed',
    )
  })

  it('is null when the rep chose nothing at all', () => {
    expect(composeDismissReason(null, null)).toBeNull()
    expect(composeDismissReason('', '')).toBeNull()
  })

  it('keeps a free-text-only reason', () => {
    expect(composeDismissReason('', 'wrong deal')).toBe('wrong deal')
  })

  it('bounds the note so a Small Text field cannot be overrun', () => {
    const reason = composeDismissReason('other', 'x'.repeat(1000))
    expect(reason.length).toBe('other: '.length + DISMISS_NOTE_MAX)
  })
})

describe('agent degrade statuses', () => {
  it('explains a switched-off assistant', () => {
    expect(draftStatusMessage('disabled')).toMatch(/switched off/)
  })

  it('explains an unreachable assistant', () => {
    expect(draftStatusMessage('unavailable')).toMatch(/could not be reached/)
  })

  it('says nothing when there is nothing to explain', () => {
    expect(draftStatusMessage('ok')).toBe('')
    expect(draftStatusMessage(undefined)).toBe('')
  })

  it('only treats an ok status with a draft as usable', () => {
    expect(isDraftUsable({ status: 'ok', draft: { body: 'hi' } })).toBe(true)
    expect(isDraftUsable({ status: 'ok' })).toBe(false)
    expect(isDraftUsable({ status: 'disabled' })).toBe(false)
    expect(isDraftUsable(null)).toBe(false)
  })
})

describe('datetime defaults', () => {
  it('formats to the frappe datetime string', () => {
    expect(formatLocalDatetime(new Date(2026, 7, 14, 9, 5, 0))).toBe(
      '2026-08-14 09:05:00',
    )
  })

  it('defaults a call to tomorrow morning', () => {
    expect(nextMorning(new Date(2026, 7, 14, 23, 40, 0))).toBe(
      '2026-08-15 09:00:00',
    )
  })

  it('rolls over a month boundary', () => {
    expect(nextMorning(new Date(2026, 7, 31, 12, 0, 0))).toBe(
      '2026-09-01 09:00:00',
    )
  })
})

describe('action document builders', () => {
  const suggestion = {
    name: '1',
    reference_doctype: 'CRM Deal',
    reference_docname: 'D-1',
  }

  it('builds a task against the referenced record', () => {
    expect(buildTaskDoc(suggestion, { title: 'Re-engage Acme' })).toEqual({
      doctype: 'CRM Task',
      reference_doctype: 'CRM Deal',
      reference_docname: 'D-1',
      status: 'Todo',
      title: 'Re-engage Acme',
    })
  })

  it('builds a scheduled call as a calendar Event, not a call log', () => {
    const doc = buildCallEventDoc(suggestion, {
      subject: 'Confirm close plan',
      starts_on: '2026-08-15 09:00:00',
    })
    expect(doc.doctype).toBe('Event')
    expect(doc.event_category).toBe('Call')
    expect(doc.event_type).toBe('Private')
    expect(doc.status).toBe('Open')
    expect(doc.reference_docname).toBe('D-1')
    expect(doc.description).toBe('')
  })

  it('builds email args bound to the referenced record', () => {
    const args = buildEmailArgs(
      suggestion,
      { recipients: 'a@b.c', subject: 'Hi', content: '<p>Hi</p>' },
      'me@co.za',
    )
    expect(args).toEqual({
      recipients: 'a@b.c',
      subject: 'Hi',
      content: '<p>Hi</p>',
      doctype: 'CRM Deal',
      name: 'D-1',
      send_email: 1,
      sender: 'me@co.za',
    })
  })

  it('leaves the sender to the server when none is known', () => {
    const args = buildEmailArgs(suggestion, {}, null)
    expect(args.sender).toBeUndefined()
  })
})

describe('fieldUpdateSpec', () => {
  it('reads the target field out of the payload', () => {
    expect(
      fieldUpdateSpec({
        fieldname: 'next_step',
        value: 'Send pricing',
        label: 'Next step',
      }),
    ).toEqual({
      fieldname: 'next_step',
      fieldtype: 'Data',
      label: 'Next step',
      options: '',
      value: 'Send pricing',
    })
  })

  it('accepts the shorter `field` key and defaults the label', () => {
    expect(fieldUpdateSpec({ field: 'status' }).label).toBe('status')
    expect(fieldUpdateSpec({ field: 'status' }).value).toBe('')
  })

  it('refuses rather than degrading when no field is named', () => {
    expect(fieldUpdateSpec({})).toBeNull()
    expect(fieldUpdateSpec(null)).toBeNull()
  })
})
