import { describe, expect, it } from 'vitest'

import { canSendMessage } from '@/utils/whatsappMessage'

describe('canSendMessage', () => {
  it('refuses nothing, blanks and newlines', () => {
    for (const content of ['', '   ', '\n\n', null, undefined]) {
      expect(canSendMessage(content)).toBe(false)
    }
  })

  it('accepts text', () => {
    expect(canSendMessage(' hi ')).toBe(true)
  })
})
