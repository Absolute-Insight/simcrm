import { describe, expect, it } from 'vitest'
import { linkOptions } from '@/utils/linkOptions'

const rows = (n) =>
  Array.from({ length: n }, (_, i) => ({ value: `R${i}`, description: '' }))

describe('linkOptions', () => {
  it('lists a full page without claiming there is more', () => {
    const { options, more } = linkOptions(rows(50), 50)
    expect(options).toHaveLength(50)
    expect(more).toBe(false)
  })

  it('says there is more only when a row was left out', () => {
    const { options, more } = linkOptions(rows(51), 50)
    expect(options).toHaveLength(50)
    expect(more).toBe(true)
  })

  it('drops the record id and a repeated title from the description', () => {
    const { options } = linkOptions([
      {
        value: 'Ana Diaz Ana Diaz',
        label: 'Ana Diaz',
        description: '<b>Ana Diaz Ana Diaz</b>, ana@example.com',
      },
      { value: 'Plain', description: 'Plain, Ana Diaz' },
    ])
    expect(options[0]).toEqual({
      label: 'Ana Diaz',
      value: 'Ana Diaz Ana Diaz',
      description: 'ana@example.com',
    })
    expect(options[1].description).toBe('Ana Diaz')
  })

  it('survives an empty response', () => {
    expect(linkOptions(null)).toEqual({ options: [], more: false })
  })
})
