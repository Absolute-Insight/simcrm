/**
 * The page length the next "load more" should ask for, or null when the server
 * will not return more than it already has.
 *
 * Lists and the record timeline grow one page length rather than fetching the
 * next page, and the server clamps that length (`max_page_length` on a list).
 * Asking past the clamp got the same rows back: a list's "Load More" stayed on
 * screen and re-fetched the first thousand rows on every click, saying
 * nothing. A null here is the caller's cue to say so instead.
 */
export function nextPageLength(current, step, max) {
  const length = Number(current) || 0
  const limit = Number(max) || Infinity
  if (length >= limit) return null
  return Math.min(length + (Number(step) || 0), limit)
}

/* How many times each doctype's saved list was rewritten while no list was on
   screen. ViewControls reads cached params that differ from the saved view as an
   unsaved change and keeps them, which for a rewrite is exactly wrong, for every
   list cached under that view. A new generation is a new cache key for all of
   them at once. */
const listGenerations = new Map()

/** Every list of `doctype` opened from now on starts from its saved view. */
export function markListRewritten(doctype) {
  listGenerations.set(doctype, listGeneration(doctype) + 1)
}

export function listGeneration(doctype) {
  return listGenerations.get(doctype) || 0
}
