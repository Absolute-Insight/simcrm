/**
 * The photos and voice notes on notes, for the cards that show them.
 *
 * Every card asks for its own note, and a page of cards would be a page of
 * requests. The names asked for in one tick go in one call
 * (crm.api.note_media.get_note_media), and each answer is kept for the page,
 * so a card that re-renders does not ask again.
 */
import { call } from 'frappe-ui'
import { reactive } from 'vue'

const known = reactive({})
let waiting = new Set()
let timer = null

function flush() {
  const names = [...waiting]
  waiting = new Set()
  timer = null
  if (!names.length) return
  call('crm.api.note_media.get_note_media', { notes: names })
    .then((media) => {
      for (const name of names) known[name] = media?.[name] ?? []
    })
    .catch(() => {
      // a card without its photos is still the note; nothing to report
      for (const name of names) known[name] = []
    })
}

/** The media on note `name`: `[{ name, url, kind }]`, `[]` until known. */
export function noteMedia(name) {
  if (!name) return []
  if (!(name in known)) {
    known[name] = []
    waiting.add(name)
    timer ||= setTimeout(flush, 0)
  }
  return known[name]
}

/** Forget one note's media, so the next look asks again (after an edit). */
export function forgetNoteMedia(name) {
  delete known[name]
}
