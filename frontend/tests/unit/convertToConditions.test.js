import { execFileSync } from 'node:child_process'
import { describe, expect, it, vi } from 'vitest'

vi.mock('@/stores/users', () => ({ usersStore: () => ({}) }))
vi.mock('@/stores/meta', () => ({ getMeta: () => ({}) }))

const { convertToConditions } = await import('@/utils')

/**
 * Evaluate a generated condition the way the server does: frappe.safe_eval
 * runs with empty __builtins__, the SLA with `doc` = doc.as_dict() and an
 * Assignment Rule with the doc's fields as bare names. A date field is a
 * datetime.date / datetime once loaded from the database, a string on an
 * unsaved doc and None when unset.
 */
function evaluate(condition, value) {
  const script = `
import datetime, json, sys
class Doc(dict):
    __getattr__ = dict.get
value = eval(sys.argv[2], {"datetime": datetime})
try:
    result = eval(sys.argv[1], {"__builtins__": {}}, {"doc": Doc(d=value), "d": value})
    print(json.dumps(bool(result)))
except Exception as e:
    print(type(e).__name__)
`
  return execFileSync('python3', ['-I', '-c', script, condition, value], {
    encoding: 'utf8',
  }).trim()
}

describe('convertToConditions on date fields', () => {
  it.each(['>', '<', '>=', '<='])(
    'guards %s and compares the date as ISO text',
    (op) => {
      expect(
        convertToConditions({
          conditions: [['d', op, '2026-01-01']],
          fieldPrefix: 'doc',
        }),
      ).toBe(`(doc.d and f"{doc.d}"[:10] ${op} "2026-01-01")`)
    },
  )

  it('evaluates > on unset, stored and unsaved dates without raising', () => {
    const condition = convertToConditions({
      conditions: [['d', '>', '2026-01-01']],
      fieldPrefix: 'doc',
    })
    expect(evaluate(condition, 'None')).toBe('false')
    expect(evaluate(condition, 'datetime.date(2026, 3, 1)')).toBe('true')
    expect(evaluate(condition, 'datetime.date(2025, 3, 1)')).toBe('false')
    expect(evaluate(condition, '"2026-03-01"')).toBe('true')
  })

  it('compares a datetime to the precision of the value', () => {
    const condition = convertToConditions({
      conditions: [['d', '<=', '2026-01-01 09:00:00']],
    })
    expect(condition).toBe(`(d and f"{d}"[:19] <= "2026-01-01 09:00:00")`)
    expect(
      evaluate(condition, 'datetime.datetime(2026, 1, 1, 9, 0, 0, 500000)'),
    ).toBe('true')
    expect(evaluate(condition, 'datetime.datetime(2026, 1, 1, 9, 0, 1)')).toBe(
      'false',
    )
  })

  it('leaves number comparisons as they were', () => {
    expect(
      convertToConditions({
        conditions: [['annual_revenue', '>', 1000]],
        fieldPrefix: 'doc',
      }),
    ).toBe('doc.annual_revenue > 1000')
  })
})

describe('convertToConditions between', () => {
  // frappe-ui v1's DateRangePicker gives [from, to]; the old one "from,to".
  it.each([[['2026-01-01', '2026-01-31']], ['2026-01-01,2026-01-31']])(
    'expands %j into an inclusive, guarded date range',
    (range) => {
      const condition = convertToConditions({
        conditions: [['d', 'between', range]],
        fieldPrefix: 'doc',
      })
      expect(condition).toBe(
        '(doc.d and f"{doc.d}"[:10] >= "2026-01-01" and f"{doc.d}"[:10] <= "2026-01-31")',
      )
      expect(evaluate(condition, 'None')).toBe('false')
      expect(evaluate(condition, 'datetime.datetime(2026, 1, 31, 18, 0)')).toBe(
        'true',
      )
      expect(evaluate(condition, 'datetime.date(2026, 2, 1)')).toBe('false')
    },
  )
})
