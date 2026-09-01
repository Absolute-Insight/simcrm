import { describe, expect, it } from 'vitest'
import { formatTable, monthLabel } from '@/utils/analystTables'

const TABLE = {
  key: 'won_revenue_by_month',
  title: 'Revenue from won deals by month',
  source: 'CRM',
  columns: [
    { key: 'month', label: 'Month', type: 'month' },
    { key: 'value', label: 'Won value', type: 'currency' },
    { key: 'change_pct', label: 'Change', type: 'percent' },
    { key: 'deals', label: 'Deals', type: 'int' },
  ],
  rows: [
    { month: '2026-07', value: 1200, change_pct: null, deals: 3 },
    { month: '2026-08', value: 1800.5, change_pct: 50, deals: 4 },
  ],
  note: 'Closed-won value.',
  error: null,
}

describe('monthLabel', () => {
  it('renders YYYY-MM as a short month and year', () => {
    expect(monthLabel('2026-08')).toBe('Aug 2026')
    expect(monthLabel('2027-01')).toBe('Jan 2027')
  })

  it('leaves anything else alone', () => {
    expect(monthLabel('total')).toBe('total')
    expect(monthLabel('2026-13')).toBe('2026-13')
    expect(monthLabel(null)).toBe('')
  })
})

describe('formatTable', () => {
  it('formats cells by column type and right-aligns measures', () => {
    const out = formatTable(TABLE, 'USD')
    expect(out.columns.map((c) => c.align)).toEqual([
      'left',
      'right',
      'right',
      'right',
    ])
    expect(out.rows[0][0]).toBe('Jul 2026')
    expect(out.rows[0][1]).toMatch(/1,200/)
    expect(out.rows[0][2]).toBe('—')
    expect(out.rows[1][2]).toBe('50%')
    expect(out.rows[1][3]).toBe('4')
    expect(out.title).toBe(TABLE.title)
    expect(out.note).toBe('Closed-won value.')
    expect(out.error).toBeNull()
  })

  it('exports raw values to CSV with the currency in the header', () => {
    const csv = formatTable(TABLE, 'ZAR').csv()
    const lines = csv.replace(/^﻿/, '').split('\r\n')
    expect(lines[0]).toBe('Month,Won value (ZAR),Change,Deals')
    expect(lines[1]).toBe('2026-07,1200,,3')
    expect(lines[2]).toBe('2026-08,1800.5,50,4')
  })

  it('carries an error table through with no rows', () => {
    const out = formatTable({ ...TABLE, rows: [], error: 'unreachable' })
    expect(out.rows).toEqual([])
    expect(out.error).toBe('unreachable')
  })

  it('tolerates a missing table', () => {
    const out = formatTable(undefined)
    expect(out.columns).toEqual([])
    expect(out.rows).toEqual([])
    expect(out.csv()).toContain('')
  })
})
