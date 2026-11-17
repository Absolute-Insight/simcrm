import { describe, expect, it } from 'vitest'

import { clock, fitWithin, mediaKind, PHOTO_EDGE } from '@/utils/noteMedia'
import { entryProblem } from '@/utils/fieldOutbox'

describe('note media', () => {
  it('scales a camera photo down to the long edge, keeping its shape', () => {
    expect(fitWithin(4000, 3000)).toEqual({ width: PHOTO_EDGE, height: 1200 })
    expect(fitWithin(3000, 4000)).toEqual({ width: 1200, height: PHOTO_EDGE })
    expect(fitWithin(800, 600)).toEqual({ width: 800, height: 600 })
  })

  it('tells a photo from a recording by its file', () => {
    expect(mediaKind('/private/files/field-media-x.jpg')).toBe('photo')
    expect(mediaKind('/private/files/field-media-x.webm')).toBe('voice')
    expect(mediaKind('/private/files/field-media-x.m4a')).toBe('voice')
    expect(mediaKind('/files/report.pdf')).toBeNull()
  })

  it('shows a recording time as minutes and seconds', () => {
    expect(clock(65.7)).toBe('1:05')
    expect(clock(0)).toBe('0:00')
  })

  it('a note may be only a photo or a voice note', () => {
    expect(entryProblem('add_note', { content: '', media: ['m'] })).toBe('')
    expect(entryProblem('add_note', { content: '' })).not.toBe('')
  })
})
