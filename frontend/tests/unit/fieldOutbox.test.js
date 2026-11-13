import { describe, expect, it } from 'vitest'
import {
  applyOutbox,
  describeEntry,
  entryProblem,
  failureKind,
  newEntry,
  newEntryId,
  oneLine,
} from '@/utils/fieldOutbox'

const dateOf = () => '2026-11-13'
const entry = (action, payload, extra = {}) => ({
  ...newEntry(action, payload, {
    id: `id-${action}-${Math.random()}`,
    user: 'rep@example.com',
    capturedAt: 1,
  }),
  ...extra,
})

const pack = () => ({
  plans: [
    {
      week_start: '2026-11-09',
      items: [
        {
          name: 'item-1',
          activity_type: 'Visit',
          planned_date: '2026-11-13',
          organization: 'Impala',
          status: 'Planned',
        },
        { name: 'item-2', activity_type: 'Call', status: 'Planned' },
      ],
    },
    { week_start: '2026-11-16', items: [] },
  ],
  history: [{ name: 'old', organization: 'Impala', status: 'Done' }],
  notes: [{ name: 'n1', title: 'Existing' }],
  tasks: [
    { name: 7, title: 'Send quote' },
    { name: 8, title: 'Call back' },
  ],
})

describe('entry ids', () => {
  it('uses the browser’s UUID where there is one', () => {
    expect(newEntryId({ randomUUID: () => 'the-uuid' })).toBe('the-uuid')
  })

  it('still makes a long unguessable id without one, and never the same twice', () => {
    const fill = (bytes) => bytes.forEach((_, i) => (bytes[i] = (i * 37) % 256))
    const a = newEntryId({ getRandomValues: fill })
    expect(a).toMatch(/^[0-9a-f]{32}$/)
    expect(newEntryId({})).not.toBe(newEntryId({}))
  })

  it('passes the server’s shape check', () => {
    // _REQUEST_ID in crm/api/offline.py
    const shape = /^[A-Za-z0-9][A-Za-z0-9-]{15,63}$/
    expect(newEntryId()).toMatch(shape)
    expect(newEntryId({})).toMatch(shape)
  })
})

describe('entryProblem', () => {
  const rules = { event_kinds: ['Visit', 'Delivery'] }

  it('wants the account of what happened', () => {
    expect(
      entryProblem(
        'log_activity',
        { activity_type: 'Admin', note: ' ' },
        rules,
      ),
    ).toBeTruthy()
    expect(entryProblem('complete_item', { outcome: '' })).toBeTruthy()
    expect(entryProblem('cancel_item', { reason: '' })).toBeTruthy()
    expect(entryProblem('close_task', { closing_note: '' })).toBeTruthy()
    expect(entryProblem('add_note', { content: '' })).toBeTruthy()
    expect(entryProblem('create_task', { title: '' })).toBeTruthy()
  })

  it('wants a customer for a visit and not for admin', () => {
    expect(
      entryProblem(
        'log_activity',
        { activity_type: 'Visit', note: 'x' },
        rules,
      ),
    ).toBeTruthy()
    expect(
      entryProblem(
        'log_activity',
        { activity_type: 'Visit', note: 'x', organization: 'Impala' },
        rules,
      ),
    ).toBe('')
    expect(
      entryProblem(
        'log_activity',
        { activity_type: 'Admin', note: 'x' },
        rules,
      ),
    ).toBe('')
  })

  it('holds text to what the server will take', () => {
    expect(entryProblem('add_note', { content: 'x'.repeat(5001) })).toBeTruthy()
    expect(entryProblem('create_task', { title: 'x'.repeat(141) })).toBeTruthy()
    expect(entryProblem('create_task', { title: 'x'.repeat(140) })).toBe('')
  })

  it('refuses an action that is not one', () => {
    expect(entryProblem('delete_everything', {})).toBeTruthy()
  })
})

describe('failureKind', () => {
  it('a server refusal waits for the rep', () => {
    expect(failureKind({ status: 417, exc_type: 'ValidationError' })).toBe(
      'rejected',
    )
    expect(failureKind({ status: 403, exc_type: 'PermissionError' })).toBe(
      'rejected',
    )
    expect(failureKind({ status: 404, exc_type: 'DoesNotExistError' })).toBe(
      'rejected',
    )
  })

  it('anything that might pass next time is tried again', () => {
    expect(failureKind(new TypeError('Failed to fetch'))).toBe('retry')
    expect(failureKind({ status: 502 })).toBe('retry')
    expect(failureKind({ status: 429, exc_type: 'TooManyRequestsError' })).toBe(
      'retry',
    )
    expect(failureKind({ status: 400, exc_type: 'CSRFTokenError' })).toBe(
      'retry',
    )
    // the week changed under it: not the entry's fault, and fine next time
    expect(
      failureKind({ status: 409, exc_type: 'TimestampMismatchError' }),
    ).toBe('retry')
    expect(failureKind(undefined)).toBe('retry')
  })
})

describe('applyOutbox', () => {
  it('hands the pack back untouched when nothing is waiting', () => {
    const p = pack()
    expect(applyOutbox(p, [], dateOf)).toBe(p)
    expect(
      applyOutbox(null, [entry('create_task', { title: 'x' })], dateOf),
    ).toBe(null)
  })

  it('shows a logged visit as done, on its day, and in the customer’s history', () => {
    const out = applyOutbox(
      pack(),
      [
        entry('log_activity', {
          activity_type: 'Visit',
          organization: 'Impala',
          note: 'Replaced the knife gate',
        }),
      ],
      dateOf,
    )
    const added = out.plans[0].items.at(-1)
    expect(added).toMatchObject({
      status: 'Done',
      planned_date: '2026-11-13',
      organization: 'Impala',
      pending: true,
    })
    expect(out.plans[1].items).toEqual([])
    expect(out.history[0].name).toBe(added.name)
    expect(out.history).toHaveLength(2)
  })

  it('closes a planned item with its outcome, without touching the others', () => {
    const p = pack()
    const out = applyOutbox(
      p,
      [entry('complete_item', { item: 'item-1', outcome: 'All fine' })],
      dateOf,
    )
    expect(out.plans[0].items[0]).toMatchObject({
      status: 'Done',
      outcome: 'All fine',
      pending: true,
    })
    expect(out.plans[0].items[1]).toBe(p.plans[0].items[1])
    expect(out.plans[1]).toBe(p.plans[1])
    expect(p.plans[0].items[0].status).toBe('Planned')
  })

  it('cancels with the reason', () => {
    const out = applyOutbox(
      pack(),
      [entry('cancel_item', { item: 'item-1', reason: 'Plant shut' })],
      dateOf,
    )
    expect(out.plans[0].items[0]).toMatchObject({
      status: 'Cancelled',
      outcome: 'Plant shut',
    })
  })

  it('adds a note and a task, and takes a closed task off the list', () => {
    const out = applyOutbox(
      pack(),
      [
        entry('add_note', {
          reference_doctype: 'CRM Organization',
          reference_docname: 'Impala',
          content: 'Ask for Thabo\nGate 3',
        }),
        entry('create_task', {
          title: 'Order gaskets',
          due_date: '2026-11-20',
        }),
        entry('close_task', { task: 7, closing_note: 'Sent' }),
      ],
      dateOf,
    )
    expect(out.notes[0]).toMatchObject({
      title: 'Ask for Thabo',
      pending: true,
    })
    expect(out.tasks.map((t) => t.title)).toEqual([
      'Call back',
      'Order gaskets',
    ])
  })

  it('keeps showing what was sent until a sync confirms it', () => {
    const out = applyOutbox(
      pack(),
      [
        entry(
          'complete_item',
          { item: 'item-1', outcome: 'x' },
          { status: 'sent' },
        ),
      ],
      dateOf,
    )
    expect(out.plans[0].items[0].status).toBe('Done')
  })

  it('never shows a refused entry as done', () => {
    const p = pack()
    expect(
      applyOutbox(
        p,
        [
          entry(
            'complete_item',
            { item: 'item-1', outcome: 'x' },
            { status: 'rejected' },
          ),
        ],
        dateOf,
      ),
    ).toBe(p)
  })
})

describe('words', () => {
  it('cuts a note to the line a plan item holds', () => {
    expect(oneLine('  Saw   the\nbuyer ')).toBe('Saw the buyer')
    const long = oneLine('x'.repeat(300))
    expect(long).toHaveLength(140)
    expect(long.endsWith('…')).toBe(true)
  })

  it('describes each entry in the rep’s terms', () => {
    const names = {
      customerName: (n) => `${n} Platinum`,
      taskTitle: () => 'Send quote',
      activityLabel: (t) => t,
    }
    expect(
      describeEntry(
        entry('log_activity', {
          activity_type: 'Visit',
          organization: 'Impala',
          note: 'Fine',
        }),
        names,
      ),
    ).toEqual({ title: 'Visit · Impala Platinum', detail: 'Fine' })
    expect(
      describeEntry(
        entry('close_task', { task: 7, closing_note: 'Sent' }),
        names,
      ).detail,
    ).toBe('Send quote — Sent')
    expect(describeEntry(entry('nonsense', {}), names).title).toBe('nonsense')
  })
})

describe('planning offline', () => {
  const rules = { event_kinds: ['Visit', 'Delivery'] }

  it('wants a day, and a customer for a visit', () => {
    expect(
      entryProblem('plan_item', { activity_type: 'Admin' }, rules),
    ).toBeTruthy()
    expect(
      entryProblem(
        'plan_item',
        { activity_type: 'Visit', planned_date: '2026-11-17' },
        rules,
      ),
    ).toBeTruthy()
    expect(
      entryProblem(
        'plan_item',
        { activity_type: 'Admin', planned_date: '2026-11-17' },
        rules,
      ),
    ).toBe('')
    expect(
      entryProblem(
        'plan_item',
        {
          activity_type: 'Admin',
          planned_date: '2026-11-17',
          note: 'x'.repeat(141),
        },
        rules,
      ),
    ).toBeTruthy()
  })

  it('shows what was planned on its own day, still to do', () => {
    const out = applyOutbox(
      pack(),
      [
        entry('plan_item', {
          activity_type: 'Visit',
          planned_date: '2026-11-17',
          organization: 'Impala',
          note: 'Quote',
        }),
      ],
      dateOf,
    )
    // the day it is planned for, not the day it was captured
    expect(out.plans[0].items).toHaveLength(2)
    expect(out.plans[1].items[0]).toMatchObject({
      status: 'Planned',
      planned_date: '2026-11-17',
      organization: 'Impala',
      pending: true,
    })
    // planned is not done: nothing joins the customer's history
    expect(out.history).toHaveLength(1)
  })

  it('describes a planned entry by what and when', () => {
    const names = {
      customerName: (n) => n,
      taskTitle: () => '',
      activityLabel: (t) => t,
    }
    expect(
      describeEntry(
        entry('plan_item', {
          activity_type: 'Visit',
          planned_date: '2026-11-17',
          organization: 'Impala',
        }),
        names,
      ),
    ).toEqual({ title: 'Planned · Visit · Impala', detail: '2026-11-17' })
  })
})
