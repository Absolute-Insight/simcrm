import { describe, it, expect, vi } from 'vitest'

// utils/index.js pulls in SFCs and stores that vitest cannot compile; stub
// them so the pure helpers under test can load.
vi.mock('@/components/Icon.vue', () => ({ default: {} }))
vi.mock('@/components/Icons/TaskStatusIcon.vue', () => ({ default: {} }))
vi.mock('@/components/Icons/TaskPriorityIcon.vue', () => ({ default: {} }))
vi.mock('@/stores/users', () => ({ usersStore: () => ({}) }))
vi.mock('@/stores/meta', () => ({ getMeta: () => ({}) }))
vi.mock('frappe-ui', () => ({
  toast: {},
  dayjsLocal: () => ({}),
  dayjs: () => ({}),
  getConfig: () => undefined,
}))

const { isEmoji, htmlToText } = await import('@/utils')

describe('isEmoji', () => {
  it('recognises a gemoji entry', () => {
    expect(isEmoji('😀')).toBe(true)
    expect(isEmoji('🎉')).toBe(true)
  })

  it('rejects text, empty and multi-emoji strings', () => {
    expect(isEmoji('hello')).toBe(false)
    expect(isEmoji('')).toBe(false)
    expect(isEmoji('😀😀')).toBe(false)
    expect(isEmoji(undefined)).toBe(false)
  })
})

describe('htmlToText', () => {
  it('returns the text content of markup', () => {
    expect(htmlToText('<p>Hello <b>world</b></p>')).toBe('Hello world')
  })

  it('handles empty and nullish input', () => {
    expect(htmlToText('')).toBe('')
    expect(htmlToText(null)).toBe('')
    expect(htmlToText(undefined)).toBe('')
  })

  it('drops tags without running them', () => {
    expect(htmlToText('<img src=x onerror="throw 1">text')).toBe('text')
  })
})
