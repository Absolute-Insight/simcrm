import { describe, expect, it } from 'vitest'
import { mount } from './mount.js'
import Questionnaire from '@/components/Questionnaire.vue'

// The first questions of pages/PersonaForm.vue, trimmed. The real frappe-ui
// Button puts the click listener on the native <button>, which outlives its
// component while the fieldset waits out the leave transition.
const questions = [
  {
    key: 'current_solution',
    title: 'How are you managing your sales today?',
    options: [
      { label: 'Spreadsheets', value: 'spreadsheets' },
      { label: 'HubSpot', value: 'hubspot' },
    ],
  },
  {
    key: 'team_size',
    title: 'How many people will use Vectora?',
    options: [
      { label: 'Just me', value: 'just_me' },
      { label: '2–5', value: '2_5' },
    ],
  },
  {
    key: 'lead_sources',
    title: 'Where do your leads come from?',
    multiple: true,
    options: [{ label: 'Referrals', value: 'referrals' }],
  },
]

const button = (el, label) =>
  [...el.querySelectorAll('button')].find((b) => b.textContent.trim() === label)
const step = (el) =>
  [...el.querySelectorAll('div')]
    .map((d) => d.textContent.trim())
    .find((t) => /^Step \d of \d$/.test(t))

describe('Questionnaire', () => {
  it('ignores the second click of a double-click on an auto-advancing option', async () => {
    const w = mount(Questionnaire, { props: { questions } })
    await w.nextTick()

    const spreadsheets = button(w.el, 'Spreadsheets')
    spreadsheets.click()
    await w.nextTick()
    // Question 1 is fading out, its button still in the page.
    expect(spreadsheets.isConnected).toBe(true)
    spreadsheets.click()
    await new Promise((r) => setTimeout(r, 50))

    // Still on question 2, and nothing answered for it.
    expect(step(w.el)).toBe('Step 2 of 3')
    await new Promise((r) => setTimeout(r, 300))
    expect(button(w.el, 'Next').disabled).toBe(true)
  })

  it('still answers and advances on a single click', async () => {
    const w = mount(Questionnaire, { props: { questions } })
    await w.nextTick()
    button(w.el, 'Spreadsheets').click()
    await new Promise((r) => setTimeout(r, 300))
    button(w.el, 'Just me').click()
    await new Promise((r) => setTimeout(r, 300))
    expect(step(w.el)).toBe('Step 3 of 3')
  })
})
