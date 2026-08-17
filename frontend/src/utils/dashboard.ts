import { dayjs } from 'frappe-ui'

export type DashboardDateRange = string | [string, string] | [] | null

export function getLastXDays(range: number = 30): string | null {
  const today = new Date()
  const lastXDate = new Date(today)
  lastXDate.setDate(today.getDate() - range)

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
  const dateObj = new Date(date)
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
