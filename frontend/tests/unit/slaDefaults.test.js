import { describe, expect, it } from 'vitest'
import { resetSlaData, slaData } from '@/components/Settings/Sla/utils.js'

const WEEK = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday']
const workdays = () => slaData.value.working_hours.map((d) => d.workday)

describe('a new SLA draft', () => {
  // Every draft used to be handed the one module-level working_hours array,
  // rows and all, so the edits SlaHolidays and WorkDayModal make in place --
  // the Day select, Add Row, Delete -- became the defaults of the next New SLA.
  it('starts on Monday to Friday whatever the last draft did to its days', () => {
    resetSlaData()
    slaData.value.working_hours[0].workday = 'Saturday' // <select v-model="row.workday">
    slaData.value.working_hours[1].start_time = '07:00:00'
    slaData.value.working_hours.push({
      workday: 'Sunday',
      start_time: '09:00:00',
      end_time: '17:00:00',
    }) // Add Row
    slaData.value.working_hours.splice(4, 1) // Delete

    resetSlaData()

    expect(workdays()).toEqual(WEEK)
    expect(slaData.value.working_hours[1].start_time).toBe('09:00:00')
  })

  it('does not share its rows with an earlier draft', () => {
    const initial = slaData.value
    resetSlaData()

    expect(slaData.value.working_hours).not.toBe(initial.working_hours)
    expect(slaData.value.working_hours[0]).not.toBe(initial.working_hours[0])
  })
})
