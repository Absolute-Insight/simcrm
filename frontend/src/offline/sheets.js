/**
 * Reference sheets a rep chose to keep on this device.
 *
 * The pack lists the sheets and their pages; the page images are large and
 * most reps want three of them, so each is fetched only when asked for, and
 * stored as blobs beside the pack. Beside it on purpose: the same store, so
 * everything that empties the pack -- logout, another user, the shelf life --
 * takes the sheets with it, with nothing new to remember to clear.
 */
import { reactive } from 'vue'
import { hasIndexedDB, packStore } from './db'

const INDEX_KEY = 'sheets-index'
const sheetKey = (name) => `sheet:${name}`

/* A page image is a scan of one PDF page. This is far past that and exists so
   a mistake on the server cannot fill a phone. */
const MAX_PAGE_BYTES = 8 * 1024 * 1024
/* Only the site's own file URLs are fetched, whatever the pack says: one file
   name directly under /files or /private/files. No further path, so no `..`
   for the browser to resolve into somewhere else on the site. */
const FILE_URL = /^\/(private\/)?files\/[^/?#\\]+$/

export const savedSheets = reactive({
  loaded: false,
  /* name -> { modified, pages, bytes } for each sheet held. */
  byName: {},
  /* The sheet being downloaded now, if any. */
  saving: null,
})

let loading = null

export function loadSavedSheets() {
  loading ||= (async () => {
    try {
      const index = hasIndexedDB() ? await packStore.get(INDEX_KEY) : null
      savedSheets.byName = index && typeof index === 'object' ? index : {}
    } catch {
      savedSheets.byName = {}
    } finally {
      savedSheets.loaded = true
    }
  })()
  return loading
}

/** The store was emptied (expiry, a new user): nothing is held any more. */
export function forgetSavedSheets() {
  savedSheets.byName = {}
}

async function writeIndex() {
  await packStore.set(INDEX_KEY, JSON.parse(JSON.stringify(savedSheets.byName)))
}

/**
 * Download a sheet's pages and keep them. All or nothing: a sheet with a page
 * missing is worse than no sheet, at a site where it cannot be fetched.
 * @throws when a page cannot be fetched or stored
 */
export async function keepSheet(sheet) {
  if (!hasIndexedDB()) {
    throw new Error(__('This device cannot keep files for offline use.'))
  }
  await loadSavedSheets()
  savedSheets.saving = sheet.name
  try {
    const pages = []
    let bytes = 0
    for (const page of sheet.pages ?? []) {
      if (!FILE_URL.test(String(page.image ?? ''))) {
        throw new Error(__('A page of this sheet has no file.'))
      }
      const response = await fetch(page.image, { credentials: 'same-origin' })
      const type = response.headers.get('content-type') || ''
      if (!response.ok || !type.startsWith('image/')) {
        throw new Error(__('A page of this sheet could not be downloaded.'))
      }
      const blob = await response.blob()
      if (blob.size > MAX_PAGE_BYTES) {
        throw new Error(__('A page of this sheet is too large to keep.'))
      }
      bytes += blob.size
      pages.push({
        page: page.page,
        width: page.width,
        height: page.height,
        blob,
      })
    }
    if (!pages.length) throw new Error(__('This sheet has no pages.'))
    await packStore.set(sheetKey(sheet.name), pages)
    savedSheets.byName = {
      ...savedSheets.byName,
      [sheet.name]: { modified: sheet.modified, pages: pages.length, bytes },
    }
    await writeIndex()
  } finally {
    savedSheets.saving = null
  }
}

export async function dropSheet(name) {
  await loadSavedSheets()
  const { [name]: _gone, ...rest } = savedSheets.byName
  savedSheets.byName = rest
  if (!hasIndexedDB()) return
  await packStore.del(sheetKey(name)).catch(() => {})
  await writeIndex().catch(() => {})
}

/**
 * Remove kept sheets the pack no longer lists: withdrawn by an administrator,
 * or deleted. Called with each new pack. A sheet taken off the server must
 * not live on as a copy on a phone.
 * @param {string[]} listed the names in the current pack
 */
export async function dropUnlistedSheets(listed) {
  await loadSavedSheets()
  const keep = new Set(listed)
  for (const name of Object.keys(savedSheets.byName)) {
    if (!keep.has(name)) await dropSheet(name)
  }
}

/** The stored pages of a sheet, `[{page, width, height, blob}]`, or null. */
export async function savedPages(name) {
  if (!hasIndexedDB()) return null
  try {
    return (await packStore.get(sheetKey(name))) || null
  } catch {
    return null
  }
}
