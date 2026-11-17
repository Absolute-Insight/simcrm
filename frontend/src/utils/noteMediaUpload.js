/**
 * Send a note's photos and voice note from the note dialog, online: each file
 * is uploaded on its own (crm.api.note_media.stage_media, safe to repeat),
 * then all of them are put on the note in one call. Field mode does the same
 * through its outbox, which is why the ids and the limits are shared.
 */
import { forgetNoteMedia } from '@/composables/useNoteMedia'
import { blobToBase64 } from '@/utils/noteMedia'
import { call } from 'frappe-ui'

/**
 * @param {string} note the note's name
 * @param {{id: string, kind: 'photo'|'voice', blob: Blob}[]} items
 */
export async function attachNoteMedia(note, items) {
  if (!note || !items?.length) return
  for (const item of items) {
    await call('crm.api.note_media.stage_media', {
      media_id: item.id,
      kind: item.kind,
      data: await blobToBase64(item.blob),
    })
  }
  await call('crm.api.note_media.attach_media', {
    note,
    media: items.map((item) => item.id),
  })
  // the cards showing this note ask again
  forgetNoteMedia(note)
}
