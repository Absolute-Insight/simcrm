import { h } from 'vue'
import LazyLoadFailed from '@/components/ui/LazyLoadFailed.vue'
import Skeleton from '@/components/ui/Skeleton.vue'
import { lazyComponent } from '@/utils/lazyComponent'

/**
 * frappe-ui's TextEditor, fetched when one is first drawn.
 *
 * For an editor inside something the app shell mounts on every page and
 * rarely shows: a settings page, the call window's note. Imported there
 * directly, tiptap, ProseMirror and lowlight -- 284 KB gzipped -- were
 * fetched with every route, lists and dashboard included, whether or not an
 * editor was ever on screen. A page that draws an editor on first paint
 * (Notes, Tasks, a record's timeline) imports it directly and gains nothing
 * from this.
 *
 * Takes the editor's props, listeners and slots unchanged. A template ref
 * reaches what the editor exposes once it has loaded, and is empty before.
 *
 * `height` is the room the stand-in takes while a slow load is on its way --
 * give it the height the empty editor has there, so the form does not jump.
 * A load that fails leaves a retry where the editor would be, not a gap.
 */
export function lazyTextEditor({ height = '8rem' } = {}) {
  return lazyComponent(() => import('@/components/editor/TextEditor.js'), {
    loading: {
      name: 'TextEditorLoading',
      render: () => h(Skeleton, { shape: 'block', height }),
    },
    failed: {
      name: 'TextEditorFailed',
      props: {
        error: { type: null, default: null },
        retrying: { type: Boolean, default: false },
      },
      emits: ['retry'],
      render() {
        return h(LazyLoadFailed, {
          what: __('the text editor'),
          error: this.error,
          retrying: this.retrying,
          onRetry: () => this.$emit('retry'),
        })
      },
    },
  })
}

export default lazyTextEditor()
