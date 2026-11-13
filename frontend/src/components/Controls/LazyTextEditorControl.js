import { h } from 'vue'
import LazyLoadFailed from '@/components/ui/LazyLoadFailed.vue'
import Skeleton from '@/components/ui/Skeleton.vue'
import { lazyComponent } from '@/utils/lazyComponent'

/* TextEditorControl, fetched when a Text Editor field is first drawn. Field
   and Grid sit under every quick-entry form, so importing the control there
   made tiptap, ProseMirror and lowlight part of every list page for a field
   type most layouts do not have. The stand-in is the height the empty editor
   takes, so the form does not jump when it arrives; a load that fails leaves
   a retry where the field would be, not a gap in the form. */
export default lazyComponent(
  () => import('@/components/Controls/TextEditorControl.vue'),
  {
    loading: {
      name: 'TextEditorLoading',
      render: () => h(Skeleton, { shape: 'block', height: '8rem' }),
    },
    failed: {
      name: 'TextEditorFailed',
      props: { error: { type: null, default: null } },
      emits: ['retry'],
      render() {
        return h(LazyLoadFailed, {
          what: __('the text editor'),
          error: this.error,
          onRetry: () => this.$emit('retry'),
        })
      },
    },
  },
)
