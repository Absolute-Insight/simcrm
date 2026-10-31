export function allTimeSlots() {
  const out = []
  for (let h = 0; h < 24; h++) {
    for (const m of [0, 15, 30, 45]) {
      const hh = String(h).padStart(2, '0')
      const mm = String(m).padStart(2, '0')
      const ampm = h >= 12 ? 'pm' : 'am'
      const hour12 = h % 12 === 0 ? 12 : h % 12
      out.push({
        value: `${hh}:${mm}`,
        label: `${hour12}:${mm} ${ampm}`,
      })
    }
  }
  return out
}

export function min(notification) {
  if (notification.interval === 'minutes') return 5
  return 1
}

export function max(notification) {
  if (notification.interval === 'minutes') return 3600
  if (notification.interval === 'hours') return 3600
  if (notification.interval === 'days') return 28
  return 4
}

export function handleIntervalChange(notification) {
  if (notification.interval === 'minutes') {
    if (notification.before < 5) notification.before = 5
    if (notification.before > 3600) notification.before = 3600
    if (notification.before % 5 !== 0)
      notification.before = Math.round(notification.before / 5) * 5
  } else if (notification.interval === 'hours') {
    if (notification.before < 1) notification.before = 1
    if (notification.before > 3600) notification.before = 3600
  } else if (notification.interval === 'days') {
    if (notification.before < 1) notification.before = 1
    if (notification.before > 28) notification.before = 28
  } else if (notification.interval === 'weeks') {
    if (notification.before < 1) notification.before = 1
    if (notification.before > 4) notification.before = 4
  }
}

const MINUTES_IN = { minutes: 1, hours: 60, days: 1440, weeks: 10080 }

/**
 * Turn a timed event's reminder into an all-day one, in place, when the event
 * is switched to All Day. An all-day reminder is "N days (or weeks) before, at
 * a time of day"; minutes and hours have no meaning there, and the server
 * honours a time of day only for days and weeks.
 *
 * Rounded up to whole days and clamped as handleIntervalChange would: "10
 * minutes before" is 1 day before at 08:00, not the 10 days the bare relabel
 * that this replaces made of it.
 */
export function toAllDayNotification(notification) {
  if (
    notification.interval === 'minutes' ||
    notification.interval === 'hours'
  ) {
    const minutes =
      (notification.before || 0) * MINUTES_IN[notification.interval]
    notification.before = Math.ceil(minutes / MINUTES_IN.days)
    notification.interval = 'days'
    handleIntervalChange(notification)
  }
  if (!notification.time) notification.time = '08:00'
  return notification
}
