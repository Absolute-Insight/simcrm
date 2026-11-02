import { describe, it, expect } from 'vitest'
import {
  parseOwnerMap,
  serialiseBranchMap,
  serialiseOwnerMap,
} from '../../src/utils/salespersonOwners.js'

describe('parseOwnerMap', () => {
  it('turns the stored JSON into rows', () => {
    expect(parseOwnerMap('{"036-NEW": "isabella@example.com"}')).toEqual([
      { code: '036-NEW', user: 'isabella@example.com', branch: '' },
    ])
  })

  it("puts each salesperson's branch on their row", () => {
    expect(
      parseOwnerMap(
        '{"007": "tamryn@example.com", "019": "rob@example.com"}',
        '{"007": "RTB"}',
      ),
    ).toEqual([
      { code: '007', user: 'tamryn@example.com', branch: 'RTB' },
      { code: '019', user: 'rob@example.com', branch: '' },
    ])
  })

  it('reads the owners even when the branch map is unreadable', () => {
    expect(parseOwnerMap('{"007": "t@example.com"}', '{')).toEqual([
      { code: '007', user: 't@example.com', branch: '' },
    ])
  })

  it('starts empty on nothing', () => {
    for (const raw of [null, undefined, '']) {
      expect(parseOwnerMap(raw)).toEqual([])
    }
  })

  it('refuses bad JSON or the wrong shape instead of reading it as empty', () => {
    for (const raw of ['{', '[1]', '"x"', 'null']) {
      expect(parseOwnerMap(raw)).toBeNull()
    }
  })
})

describe('serialiseOwnerMap', () => {
  it('keeps complete rows only, trimmed', () => {
    const value = serialiseOwnerMap([
      { code: ' 007-TB ', user: 'tamryn@example.com' },
      { code: '', user: 'nobody@example.com' },
      { code: '040-KVD', user: '' },
    ])
    expect(JSON.parse(value)).toEqual({ '007-TB': 'tamryn@example.com' })
  })

  it('clears the field when no row is complete', () => {
    expect(serialiseOwnerMap([{ code: 'x', user: '' }])).toBe('')
    expect(serialiseOwnerMap([])).toBe('')
  })

  it('round-trips', () => {
    const raw = serialiseOwnerMap([{ code: 'A', user: 'a@example.com' }])
    expect(serialiseOwnerMap(parseOwnerMap(raw))).toBe(raw)
  })
})

describe('serialiseBranchMap', () => {
  it('keeps the branch of complete rows only, trimmed', () => {
    const value = serialiseBranchMap([
      { code: '007', user: 'tamryn@example.com', branch: ' RTB ' },
      { code: '019', user: 'rob@example.com', branch: '' },
      { code: '032', user: '', branch: 'KXE' },
    ])
    expect(JSON.parse(value)).toEqual({ '007': 'RTB' })
  })

  it('clears the field when no row has a branch', () => {
    expect(serialiseBranchMap([{ code: 'x', user: 'x@example.com' }])).toBe('')
  })
})
