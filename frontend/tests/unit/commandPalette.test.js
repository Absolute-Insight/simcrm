import { describe, expect, it } from 'vitest'
import {
  addRecent,
  fuzzyScore,
  groupCommands,
  isDueItemVisible,
  isRecordVisible,
  recentNamesByDoctype,
  recordSubtitle,
  scoreCommand,
  sortByRecency,
  RECENT_LIMIT,
} from '@/utils/commandPalette'

describe('fuzzyScore', () => {
  it('ranks prefix, word, substring and subsequence matches in that order', () => {
    const prefix = fuzzyScore('Change status', 'change')
    const word = fuzzyScore('Set deal status', 'deal')
    const substring = fuzzyScore('Organization', 'gan')
    const subsequence = fuzzyScore('Organizations', 'orgs')
    expect(prefix).toBeGreaterThan(word)
    expect(word).toBeGreaterThan(substring)
    expect(substring).toBeGreaterThan(subsequence)
  })

  it('returns -1 when the query does not match', () => {
    expect(fuzzyScore('Deals', 'contact')).toBe(-1)
  })

  it('ignores case and surrounding whitespace', () => {
    expect(fuzzyScore('  New Lead  ', 'NEW')).toBeGreaterThan(0)
  })

  it('treats regex characters in a query as text', () => {
    expect(fuzzyScore('Rand (Pty) Ltd', '(pty')).toBeGreaterThan(0)
  })

  it('does not throw on a missing value', () => {
    expect(fuzzyScore(undefined, 'deal')).toBe(-1)
  })
})

describe('scoreCommand', () => {
  it('scores a keyword hit below a title hit', () => {
    const title = scoreCommand({ title: 'Create lead' }, 'create')
    const keyword = scoreCommand(
      { title: 'New lead', keywords: 'create add' },
      'create',
    )
    expect(title).toBeGreaterThan(keyword)
  })

  it('finds a deal by a quote number only its keywords carry', () => {
    const score = scoreCommand(
      { title: 'Palette Valves', keywords: 'CRM-DEAL-1 QT103406' },
      'QT103406',
    )
    expect(score).toBeGreaterThan(0)
  })

  it('honours a fixed rank whatever the query', () => {
    expect(scoreCommand({ title: 'Anything', rank: 2000 }, 'missing')).toBe(
      2000,
    )
  })

  it('applies a weight', () => {
    const normal = scoreCommand({ title: 'Change status' }, 'status')
    const weighted = scoreCommand(
      { title: 'Change status', weight: 0.5 },
      'status',
    )
    expect(weighted).toBeLessThan(normal)
  })
})

describe('groupCommands', () => {
  const commands = [
    { id: 'leads', title: 'Leads', group: 'Go to' },
    { id: 'deals', title: 'Deals', group: 'Go to' },
    { id: 'new-deal', title: 'Create Deal', group: 'Create' },
  ]

  it('keeps the input order when nothing is typed', () => {
    const groups = groupCommands(commands)
    expect(groups.map((group) => group.title)).toEqual(['Go to', 'Create'])
    expect(groups[0].items.map((item) => item.id)).toEqual(['leads', 'deals'])
  })

  it('drops what does not match', () => {
    const groups = groupCommands(commands, 'deal')
    const ids = groups.flatMap((group) => group.items.map((item) => item.id))
    expect(ids.sort()).toEqual(['deals', 'new-deal'])
  })

  it('returns nothing when nothing matches', () => {
    expect(groupCommands(commands, 'zzz')).toEqual([])
  })
})

describe('recent records', () => {
  const deal = { doctype: 'CRM Deal', name: 'D-1' }
  const lead = { doctype: 'CRM Lead', name: 'L-1' }

  it('puts the newest first and does not repeat a record', () => {
    expect(addRecent([deal, lead], lead)).toEqual([lead, deal])
  })

  it('keeps two records that share a name across doctypes', () => {
    const contact = { doctype: 'Contact', name: 'D-1' }
    expect(addRecent([deal], contact)).toEqual([contact, deal])
  })

  it('is capped', () => {
    const many = Array.from({ length: RECENT_LIMIT + 3 }, (_, index) => ({
      doctype: 'CRM Lead',
      name: `L-${index}`,
    }))
    const recent = many.reduce(addRecent, [])
    expect(recent).toHaveLength(RECENT_LIMIT)
    expect(recent[0].name).toBe(`L-${RECENT_LIMIT + 2}`)
  })

  it('groups names by doctype for the server', () => {
    expect(
      recentNamesByDoctype([deal, lead, { doctype: 'CRM Lead', name: 'L-2' }]),
    ).toEqual({ 'CRM Deal': ['D-1'], 'CRM Lead': ['L-1', 'L-2'] })
  })

  it('restores the recency order the grouping lost', () => {
    const recent = [lead, deal]
    const fromServer = [
      { ...deal, title: 'Deal' },
      { ...lead, title: 'Lead' },
    ]
    expect(sortByRecency(fromServer, recent).map((r) => r.name)).toEqual([
      'L-1',
      'D-1',
    ])
  })
})

describe('recordSubtitle', () => {
  it('names the type and tells apart deals that share a customer', () => {
    expect(recordSubtitle({ doctype: 'CRM Deal', detail: 'QT103406' })).toBe(
      'Deal · QT103406',
    )
  })

  it('leaves the detail out when there is none', () => {
    expect(recordSubtitle({ doctype: 'CRM Organization' })).toBe('Organization')
    expect(recordSubtitle({ doctype: 'Contact', detail: '' })).toBe('Contact')
  })
})

describe('what Access Control hides', () => {
  const surfaces = new Set(['Deals', 'Tasks', 'Planner'])
  const task = (route, route_name = null) => ({
    kind: 'task',
    route,
    route_name,
  })

  it('hides a record whose list is hidden', () => {
    expect(isRecordVisible({ route: 'Deal' }, surfaces)).toBe(true)
    expect(isRecordVisible({ route: 'Lead' }, surfaces)).toBe(false)
  })

  it('keeps a task on a record the role can see', () => {
    expect(isDueItemVisible(task('Deal', 'D-1'), surfaces)).toBe(true)
  })

  it('hides a task whose record list is hidden', () => {
    expect(isDueItemVisible(task('Lead', 'L-1'), surfaces)).toBe(false)
  })

  it('hides every task when the Tasks surface is hidden', () => {
    const noTasks = new Set(['Deals'])
    expect(isDueItemVisible(task('Deal', 'D-1'), noTasks)).toBe(false)
    expect(isDueItemVisible(task('Tasks'), noTasks)).toBe(false)
  })

  it('hides planned activity when the Planner is hidden', () => {
    const plan = { kind: 'plan', route: 'Planner', route_name: null }
    expect(isDueItemVisible(plan, surfaces)).toBe(true)
    expect(isDueItemVisible(plan, new Set(['Deals']))).toBe(false)
  })
})
