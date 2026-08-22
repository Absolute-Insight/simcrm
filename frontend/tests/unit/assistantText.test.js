import { describe, expect, it } from 'vitest'
import { plainTextAnswer } from '@/utils/assistantText'

describe('plainTextAnswer', () => {
  it('strips bold, italic, code and heading markers but keeps the words', () => {
    expect(
      plainTextAnswer('## Title\n- **Idle**: days since *last* `activity`'),
    ).toBe('Title\n- Idle: days since last activity')
  })

  it('keeps bullets and a lone asterisk used as a word', () => {
    expect(plainTextAnswer('- one\n- two * three')).toBe('- one\n- two * three')
  })

  it('collapses runaway blank lines and trims', () => {
    expect(plainTextAnswer('\n\na\n\n\n\nb\n')).toBe('a\n\nb')
  })

  it('tolerates empty input', () => {
    expect(plainTextAnswer('')).toBe('')
    expect(plainTextAnswer(undefined)).toBe('')
  })
})
