/**
 * Reading the state of a frappe-ui resource honestly.
 *
 * A resource that has never loaded is not a resource holding zero, but the two
 * look identical from the outside, and the difference matters wherever the UI
 * turns a number into a claim.
 *
 * The lifecycle, from frappe-ui's `createResource`:
 *
 * - `data` starts at `initialData` and is **never cleared on failure**. On a
 *   failed *reload* `handleError` even restores `previousData`, so a count that
 *   has loaded once keeps its last good value — stale, but not a lie.
 * - `fetched` starts false and is set true **only** after a successful fetch.
 * - `error` holds the last failure.
 *
 * So the dangerous case is the *cold start*: the very first fetch fails, `data`
 * is still the `initialData` the author chose — usually `0` or `[]` — and a
 * badge keyed on that count hides itself. The sidebar then reads exactly like
 * an empty inbox: the product telling a rep there is no work waiting, when in
 * truth it never managed to ask.
 */

/**
 * True when a resource has no successfully loaded value and failed trying.
 *
 * Deliberately not just `Boolean(resource.error)`: a failed *reload* keeps the
 * previous value, and showing "unavailable" over a number we do in fact have
 * would be its own small lie.
 */
export function neverLoaded(resource) {
  if (!resource) return false
  return !resource.fetched && Boolean(resource.error)
}
