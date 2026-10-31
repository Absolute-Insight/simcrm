import { dayjs } from 'frappe-ui'

export type DashboardDateRange = string | [string, string] | [] | null

export function getLastXDays(range: number = 30): string | null {
  const today = new Date()
  const lastXDate = new Date(today)
  // an inclusive window of `range` days ending today: subtracting `range`
  // itself made "Last 30 Days" a 31-day span
  lastXDate.setDate(today.getDate() - (range - 1))

  return `${dayjs(lastXDate).format('YYYY-MM-DD')},${dayjs(today).format(
    'YYYY-MM-DD',
  )}`
}

export function parseDateRange(range: DashboardDateRange): [string, string] {
  if (!range) return ['', '']
  const dates = Array.isArray(range) ? range : range.split(',')
  return [dates[0] || '', dates[1] || '']
}

export function formatter(range: DashboardDateRange) {
  const [from, to] = parseDateRange(range)
  // "to" is a word, not punctuation, and it was the one part of this label
  // that stayed English however the rest of the app was translated.
  return __('{0} to {1}', [formatRange(from), formatRange(to)])
}

export function formatRange(date: string) {
  /* A `YYYY-MM-DD` is a calendar day, so it is read as local midnight.
     `new Date('2026-10-01')` is UTC midnight, which west of Greenwich is still
     30 September -- the label named the day before the figures' range. */
  const [y, m, d] = /^(\d{4})-(\d{2})-(\d{2})$/.exec(date || '')?.slice(1) || []
  const dateObj = y ? new Date(+y, +m - 1, +d) : new Date(date)
  /* The reader's locale, not the author's. Hardcoding en-US put "Aug 17" in
     front of every user on earth, including the ones whose month and day run
     the other way round. `undefined` is the same choice reportExport.js makes
     for its Intl.NumberFormat instances. */
  return dateObj.toLocaleDateString(undefined, {
    month: 'short',
    day: 'numeric',
    year:
      dateObj.getFullYear() === new Date().getFullYear()
        ? undefined
        : 'numeric',
  })
}
