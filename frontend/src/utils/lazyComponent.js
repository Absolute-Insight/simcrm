import { defineAsyncComponent } from 'vue'
import { reloadOnceForStaleChunk } from '@/utils/staleChunk'

/* How long a load may take before anything is drawn for it. A chunk already
   in the cache resolves well inside this, so the usual open shows the real
   thing and nothing before it; only a slow line sees the stand-in. */
export const LAZY_DELAY_MS = 200

/**
 * A component whose code is fetched the first time it is rendered.
 *
 * For what a page only sometimes draws and that costs a lot to load -- the
 * rich-text editor is 284 KB gzipped, and one static import of it from a
 * modal put it on every list route. `loading` is what stands in for it while
 * it loads, and it is not drawn at all for a load that beats LAZY_DELAY_MS, so
 * it never flashes.
 *
 * A tab left open across a release asks for a chunk that no longer exists;
 * that gets the same one reload the router gives a lazy route.
 */
export function lazyComponent(loader, loading = null) {
  return defineAsyncComponent({
    loader,
    loadingComponent: loading,
    delay: LAZY_DELAY_MS,
    onError(error, retry, fail) {
      if (!reloadOnceForStaleChunk(error)) fail()
    },
  })
}
