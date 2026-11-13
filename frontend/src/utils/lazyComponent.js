import {
  defineComponent,
  h,
  markRaw,
  nextTick,
  onBeforeUnmount,
  ref,
  shallowRef,
} from 'vue'
import LazyLoadFailed from '@/components/ui/LazyLoadFailed.vue'

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
 *  - `failed` is drawn when the load fails, with the `error`, an `onRetry`
 *    that fetches again and `retrying` while it does. A load that fails is
 *    never answered with nothing -- a field that silently is not there -- and
 *    never with a page reload: the router reloads once for a route whose
 *    chunk a release removed, but a component sits in a form somebody is
 *    filling in, and a dropped connection must not cost them what they typed.
 *  - `onFail(error)` is told of each failure, for a caller that has to do
 *    something outside the component: close the dialog it was opening, say so
 *    in a toast.
 *
 * With neither `failed` nor `onFail` the failure is still shown, as a plain
 * LazyLoadFailed. A caller that gives only `onFail` has taken the failure on
 * itself and nothing is drawn.
 *
 * Not defineAsyncComponent: that gives its error component no way to try
 * again, and a failed load stays failed for the life of the page.
 *
 * Once loaded the component is kept, so every later use renders it at once.
 * Props, listeners and slots pass straight through, and so does a template
 * ref: what the loaded component exposes is reached through the wrapper's
 * (undefined until it has loaded).
 *
 * The retry keeps the keyboard where it was. Its button stays in place while
 * the fetch runs, and when the component arrives focus moves into it; left to
 * itself the button would be removed with focus on it, and focus would fall
 * back to the top of the page.
 */
export function lazyComponent(
  loader,
  { loading = null, failed = null, onFail = null } = {},
) {
  const failure = failed ?? (onFail ? null : DefaultFailed)
  let loaded = null
  let pending = null
  const load = () =>
    (pending ||= Promise.resolve()
      .then(loader)
      .then((module) => {
        // an ES module's default export, or a component handed over as is
        const component =
          module && typeof module === 'object' && 'default' in module
            ? module.default
            : module
        // a loader that resolves nothing would otherwise render nothing,
        // for good, with no error to show for it
        if (!component) throw new Error('The lazy component loaded as nothing')
        return (loaded = markRaw(component))
      })
      .finally(() => (pending = null)))

  return defineComponent({
    name: 'LazyComponent',
    inheritAttrs: false,
    setup(_, { attrs, slots, expose }) {
      const component = shallowRef(loaded)
      const error = shallowRef(null)
      const slow = ref(false)
      const retrying = ref(false)
      const inner = shallowRef(null)
      const failedEl = shallowRef(null)
      let timer = null
      let mounted = true

      // What the loaded component exposes, through this wrapper's ref.
      expose(
        new Proxy(
          {},
          {
            get: (_target, key) => inner.value?.[key],
            has: (_target, key) => !!inner.value && key in inner.value,
          },
        ),
      )

      function attempt({ retry = false } = {}) {
        // a retry leaves the failure, and its button, where they are
        retrying.value = retry
        if (!retry) error.value = null
        slow.value = false
        clearTimeout(timer)
        timer = setTimeout(() => (slow.value = true), LAZY_DELAY_MS)
        load()
          .then(
            (value) => {
              if (!mounted) return
              const focused =
                retry && failedEl.value?.contains?.(document.activeElement)
              error.value = null
              component.value = value
              if (focused) nextTick(() => focusInto(inner.value?.$el))
            },
            (reason) => {
              console.error('A lazily loaded component failed to load', reason)
              if (!mounted) return
              error.value = reason
              onFail?.(reason)
            },
          )
          .finally(() => {
            clearTimeout(timer)
            retrying.value = false
          })
      }
      if (!loaded) attempt()
      onBeforeUnmount(() => {
        mounted = false
        clearTimeout(timer)
      })

      return () => {
        if (component.value) {
          return h(component.value, { ...attrs, ref: inner }, slots)
        }
        if (error.value) {
          return failure
            ? h(failure, {
                ref: (instance) => (failedEl.value = instance?.$el ?? null),
                error: error.value,
                retrying: retrying.value,
                onRetry: () => attempt({ retry: true }),
              })
            : null
        }
        return slow.value && loading ? h(loading) : null
      }
    },
  })
}

/** What is drawn for a failure when the caller named nothing of its own. */
const DefaultFailed = defineComponent({
  name: 'LazyFailed',
  props: {
    error: { type: null, default: null },
    retrying: { type: Boolean, default: false },
  },
  emits: ['retry'],
  render() {
    return h(LazyLoadFailed, {
      what: __('this part of the page'),
      error: this.error,
      retrying: this.retrying,
      onRetry: () => this.$emit('retry'),
    })
  },
})

const FOCUSABLE =
  '[contenteditable="true"], input:not([disabled]), textarea:not([disabled]), ' +
  'select:not([disabled]), button:not([disabled]), [tabindex]:not([tabindex="-1"])'

/** Put focus on the first thing in `root` that takes it, or on `root`. */
function focusInto(root) {
  if (!root || typeof root.querySelector !== 'function') return
  const target = root.querySelector(FOCUSABLE)
  if (target) return target.focus()
  if (!root.hasAttribute('tabindex')) root.setAttribute('tabindex', '-1')
  root.focus()
}
