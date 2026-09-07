import { describe, expect, it } from 'vitest'
import { csvFileName } from '@/utils/reportExport'

/**
 * `report_builder.run` returns title/period/dimension/measure and no `name`,
 * so a built report's CSV downloaded as "undefined-<from>-to-<to>.csv". A
 * period-less report also carried a date range it never applied.
 */
describe('csvFileName', () => {
  it('names a built-in report after its registry key and the range', () => {
    expect(
      csvFileName({ name: 'pipeline_by_owner' }, '2026-08-07', '2026-09-06'),
    ).toBe('pipeline_by_owner-2026-08-07-to-2026-09-06.csv')
  })

  it('names a built report after its measure and dimension when there is no name', () => {
    expect(
      csvFileName(
        { measure: 'won_value', dimension: 'deal_owner', period: true },
        '2026-08-07',
        '2026-09-06',
      ),
    ).toBe('won_value_by_deal_owner-2026-08-07-to-2026-09-06.csv')
  })

  it('omits the range from a snapshot report (period: false)', () => {
    expect(
      csvFileName(
        { name: 'pipeline_by_stage', period: false },
        '2026-08-07',
        '2026-09-06',
      ),
    ).toBe('pipeline_by_stage.csv')
  })

  it('never emits "undefined" and falls back to a generic stem', () => {
    const name = csvFileName({}, '2026-08-07', '2026-09-06')
    expect(name).not.toContain('undefined')
    expect(name).toBe('report-2026-08-07-to-2026-09-06.csv')
  })
})
