import { describe, expect, it } from 'vitest'
import { attachmentThumbnail } from '@/utils/attachmentThumbnail'

const file = (thumbnail_url) => ({
  file_url: '/private/files/site-photo.jpg',
  thumbnail_url,
})

describe('attachmentThumbnail', () => {
  it('prefers the small copy frappe made', () => {
    expect(attachmentThumbnail(file('/files/site-photo_small.jpg'))).toBe(
      '/files/site-photo_small.jpg',
    )
    expect(
      attachmentThumbnail(file('/private/files/site-photo_small.jpg')),
    ).toBe('/private/files/site-photo_small.jpg')
  })

  it('falls back to the file when there is no thumbnail', () => {
    for (const missing of [undefined, null, '']) {
      expect(attachmentThumbnail(file(missing))).toBe(
        '/private/files/site-photo.jpg',
      )
    }
  })

  it('does not load a thumbnail from anywhere but this site', () => {
    for (const foreign of [
      'https://tracker.example/pixel.gif',
      '//tracker.example/pixel.gif',
      'javascript:alert(1)',
      'data:image/png;base64,AAAA',
      '/api/method/logout',
      '/files/',
      42,
    ]) {
      expect(attachmentThumbnail(file(foreign))).toBe(
        '/private/files/site-photo.jpg',
      )
    }
  })

  it('survives a row with nothing on it', () => {
    expect(attachmentThumbnail(undefined)).toBeUndefined()
  })
})
