/**
 * After a release the hashed chunk a running tab lazily imports no longer
 * exists on the server: the router's dynamic `import()` rejects, navigation
 * dies with nothing on screen, and only a hard reload recovers. Detect that
 * failure shape and reload once, remembering that we did so a broken build
 * cannot loop.
 */

const CHUNK_ERROR =
  /Failed to fetch dynamically imported module|Importing a module script failed|error loading dynamically imported module|ChunkLoadError|Unable to preload CSS/i

export function isStaleChunkError(error) {
  const text = `${error?.name ?? ''} ${error?.message ?? ''}`
  return CHUNK_ERROR.test(text)
}

export const RELOAD_MARK = 'crm_stale_chunk_reload_at'
const RELOAD_COOLDOWN_MS = 60_000

function readMark(store) {
  try {
    return Number(store.getItem(RELOAD_MARK) || 0)
  } catch {
    return 0
  }
}

/**
 * @returns {boolean} true when a reload was issued
 */
export function reloadOnceForStaleChunk(
  error,
  target,
  { storage, now, reload } = {},
) {
  if (!isStaleChunkError(error)) return false
  const store = storage ?? window.sessionStorage
  const time = now ?? Date.now()
  const last = readMark(store)
  // 0 means never reloaded; only a recent reload holds us back
  if (last && time - last < RELOAD_COOLDOWN_MS) return false
  try {
    store.setItem(RELOAD_MARK, String(time))
  } catch {
    /* storage disabled: still worth one reload */
  }
  const go = reload ?? ((url) => window.location.assign(url))
  go(target || window.location.href)
  return true
}
