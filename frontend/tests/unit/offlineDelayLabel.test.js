import { describe, expect, it } from 'vitest'
import { offlineDelayLabel } from '@/utils/plannerDisplay'

describe('offlineDelayLabel', () => {
  it('says only that it was logged offline when the delay is not known', () => {
    // flagged before the delay was recorded, or sent within the minute
    expect(offlineDelayLabel(undefined)).toBe('Logged offline')
    expect(offlineDelayLabel(0)).toBe('Logged offline')
    expect(offlineDelayLabel('rubbish')).toBe('Logged offline')
  })

  it('counts minutes, then hours, then days', () => {
    expect(offlineDelayLabel(20)).toBe('Logged offline, sent 20 min later')
    expect(offlineDelayLabel(60)).toBe('Logged offline, sent 1 hour later')
    expect(offlineDelayLabel(310)).toBe('Logged offline, sent 5 hours later')
    expect(offlineDelayLabel(1440)).toBe('Logged offline, sent 1 day later')
    expect(offlineDelayLabel(3 * 1440 + 100)).toBe(
      'Logged offline, sent 3 days later',
    )
  })
})
