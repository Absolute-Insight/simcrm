import {
  defineComponent,
  h,
  markRaw,
  onBeforeUnmount,
  ref,
  shallowRef,
} from 'vue'

/* How long a load may take before anything is drawn for it. A chunk already
   in the cache resolves well inside this, so the usual open shows the real
   thing and nothing before it; only a slow line sees the stand-in. */
export const LAZY_DELAY_MS = 200

/**
 * A component whose code is fetched the first time it is rendered.
 *
 * For what a page only sometimes draws and that costs a lot to load -- the
 * rich-text editor is 284 KB gzipped, and one static import of it from a
 * modal put it on every list route.
 *
 *  - `loading` stands in for it while it loads. It is not drawn at all for a
 *    load that beats LAZY_DELAY_MS, so it never flashes.
 *  - `failed` is drawn when the load fails, with the `error` and an
 *    `onRetry` that fetches again. A load that fails is never answered with
 *    nothing -- a field that silently is not there -- and never with a page
 *    reload: the router reloads once for a route whose chunk a release
 *    removed, but a component sits in a form somebody is filling in, and a
 *    dropped connection must not cost them what they typed.
 *  - `onFail(error)` is told of each failure, for a caller that has to do
 *    something outside the component: close the dialog it was opening, say so
 *    in a toast.
 *
 * Not defineAsyncComponent: that gives its error component no way to try
 * again, and a failed load stays failed for the life of the page.
 *
 * Once loaded the component is kept, so every later use renders it at once.
 * Props, listeners and slots pass straight through.
 */
export function lazyComponent(
  loader,
  { loading = null, failed = null, onFail = null } = {},
) {
  let loaded = null
  let pending = null
  const load = () =>
    (pending ||= Promise.resolve()
      .then(loader)
      .then((module) => (loaded = markRaw(module?.default ?? module)))
      .finally(() => (pending = null)))

  return defineComponent({
    name: 'LazyComponent',
    inheritAttrs: false,
    setup(_, { attrs, slots }) {
      const component = shallowRef(loaded)
      const error = shallowRef(null)
      const slow = ref(false)
      let timer = null
      let mounted = true

      function attempt() {
        error.value = null
        slow.value = false
        clearTimeout(timer)
        timer = setTimeout(() => (slow.value = true), LAZY_DELAY_MS)
        load()
          .then(
            (value) => {
              if (mounted) component.value = value
            },
            (reason) => {
              console.error('A lazily loaded component failed to load', reason)
              if (!mounted) return
              error.value = reason
              onFail?.(reason)
            },
          )
          .finally(() => clearTimeout(timer))
      }
      if (!loaded) attempt()
      onBeforeUnmount(() => {
        mounted = false
        clearTimeout(timer)
      })

      return () => {
        if (component.value) return h(component.value, attrs, slots)
        if (error.value) {
          return failed
            ? h(failed, { error: error.value, onRetry: attempt })
            : null
        }
        return slow.value && loading ? h(loading) : null
      }
    },
  })
}
