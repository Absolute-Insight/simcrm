import { beforeEach, describe, expect, it, vi } from 'vitest'

const calls = vi.hoisted(() => [])
const fail = vi.hoisted(() => ({ on: null }))
vi.mock('frappe-ui', () => ({
  call: vi.fn(async (url, params) => {
    calls.push([url, params])
    if (fail.on === url)
      throw Object.assign(new Error('no'), { messages: ['no'] })
    return {}
  }),
}))
const forgotten = vi.hoisted(() => [])
vi.mock('@/composables/useNoteMedia', () => ({
  forgetNoteMedia: (name) => forgotten.push(name),
}))

const { attachNoteMedia } = await import('@/utils/noteMediaUpload')

const item = (id, kind) => ({
  id,
  kind,
  blob: new Blob(['x'], { type: 'image/jpeg' }),
})

beforeEach(() => {
  calls.length = 0
  forgotten.length = 0
  fail.on = null
})

describe('attachNoteMedia', () => {
  it('uploads each file, then puts them all on the note in one call', async () => {
    await attachNoteMedia('note-1', [item('a', 'photo'), item('b', 'voice')])
    expect(calls.map(([url]) => url)).toEqual([
      'crm.api.note_media.stage_media',
      'crm.api.note_media.stage_media',
      'crm.api.note_media.attach_media',
    ])
    expect(calls[0][1]).toMatchObject({ media_id: 'a', kind: 'photo' })
    expect(typeof calls[0][1].data).toBe('string')
    expect(calls[2][1]).toEqual({ note: 'note-1', media: ['a', 'b'] })
    expect(forgotten).toEqual(['note-1'])
  })

  it('sends nothing when there is nothing to send', async () => {
    await attachNoteMedia('note-1', [])
    await attachNoteMedia('', [item('a', 'photo')])
    expect(calls).toEqual([])
  })

  it('does not name the note when an upload fails', async () => {
    fail.on = 'crm.api.note_media.stage_media'
    await expect(
      attachNoteMedia('note-1', [item('a', 'photo')]),
    ).rejects.toThrow()
    expect(calls.map(([url]) => url)).toEqual([
      'crm.api.note_media.stage_media',
    ])
    expect(forgotten).toEqual([])
  })
})
