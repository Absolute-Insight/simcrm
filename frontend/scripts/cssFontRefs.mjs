import path from 'node:path'

/**
 * Where a font named by a built stylesheet has to sit, relative to the build's
 * output directory, or null when the browser will not ask this build for it.
 *
 * A stylesheet can name its font two ways, and which one the toolchain writes
 * has changed under us:
 *
 * - relative (`./Inter.var-x.woff2`): resolved against the CSS file, which is
 *   where the browser resolves it;
 * - absolute under the build's base (`/assets/crm/frontend/assets/Inter.var-x.woff2`):
 *   the base is where the output directory is served from, so what follows it
 *   is already the path inside the output directory.
 *
 * Joining an absolute reference onto the CSS file's directory, as this once
 * did for every reference, looked for `assets/assets/crm/frontend/assets/...`
 * and failed the build over fonts that were exactly where they should be.
 *
 * @param {string} cssFileName the stylesheet's path inside the output directory
 * @param {string} ref the url() as written, without any query string
 * @param {string} base vite's `base`, e.g. `/assets/crm/frontend/`
 */
export function fontDestination(cssFileName, ref, base = '/') {
  if (/^(https?:)?\/\//.test(ref) || ref.startsWith('data:')) return null
  if (ref.startsWith('/')) {
    const root = base.endsWith('/') ? base : base + '/'
    // served from somewhere this build does not write to
    if (!ref.startsWith(root)) return null
    return path.normalize(ref.slice(root.length))
  }
  return path.normalize(path.join(path.dirname(cssFileName), ref))
}
