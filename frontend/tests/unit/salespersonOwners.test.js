import { describe, it, expect } from 'vitest'
import {
  parseOwnerMap,
  serialiseOwnerMap,
} from '../../src/utils/salespersonOwners.js'

describe('parseOwnerMap', () => {
  it('turns the stored JSON into rows', () => {
    expect(parseOwnerMap('{"036-NEW": "isabella@example.com"}')).toEqual([
      { code: '036-NEW', user: 'isabella@example.com' },
    ])
  })

  it('starts empty on nothing, bad JSON or the wrong shape', () => {
    for (const raw of [null, '', '{', '[1]', '"x"', 'null']) {
      expect(parseOwnerMap(raw)).toEqual([])
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
