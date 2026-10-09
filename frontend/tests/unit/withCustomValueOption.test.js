import { withCustomValueOption } from '@/utils/fieldTransforms'

describe('withCustomValueOption', () => {
  const options = [
    { label: 'Red', value: 'red' },
    { label: 'Blue', value: 'blue' },
  ]

  function customRow(opts = options, onPick = vi.fn()) {
    const result = withCustomValueOption(opts, onPick)
    return { result, row: result[result.length - 1], onPick }
  }

  it('keeps the original options first and does not mutate them', () => {
    const { result } = customRow()
    expect(result.slice(0, 2)).toEqual(options)
    expect(result).not.toBe(options)
    expect(options).toHaveLength(2)
  })

  it('appends one custom row', () => {
    const { row } = customRow()
    expect(row.type).toBe('custom')
    expect(row.key).toBe('__custom_value')
  })

  it('stays hidden until something is typed', () => {
    const { row } = customRow()
    expect(row.condition({ query: '' })).toBe(false)
    expect(row.condition({ query: '   ' })).toBe(false)
    expect(row.condition({})).toBe(false)
  })

  it('stays hidden when the query matches an option value or label', () => {
    const { row } = customRow()
    expect(row.condition({ query: 'red' })).toBe(false)
    expect(row.condition({ query: ' Blue ' })).toBe(false)
  })

  it('shows for a query that matches nothing', () => {
    const { row } = customRow()
    expect(row.condition({ query: 'Green' })).toBe(true)
  })

  it('matches plain string options too', () => {
    const { row } = customRow(['North', 'South'])
    expect(row.condition({ query: 'North' })).toBe(false)
    expect(row.condition({ query: 'East' })).toBe(true)
  })

  it('labels the row with the trimmed query', () => {
    const { row } = customRow()
    expect(row.slots.label({ query: '  Green ' })).toBe('Use "Green"')
  })

  it('hands the trimmed query to onPick', () => {
    const { row, onPick } = customRow()
    row.onClick({ query: '  Green ' })
    expect(onPick).toHaveBeenCalledWith('Green')
  })
})
