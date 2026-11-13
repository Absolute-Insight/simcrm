import { h } from 'vue'
import Skeleton from '@/components/ui/Skeleton.vue'
import { lazyComponent } from '@/utils/lazyComponent'

/* TextEditorControl, fetched when a Text Editor field is first drawn. Field
   and Grid sit under every quick-entry form, so importing the control there
   made tiptap, ProseMirror and lowlight part of every list page for a field
   type most layouts do not have. The stand-in is the height the empty editor
   takes, so the form does not jump when it arrives. */
export default lazyComponent(
  () => import('@/components/Controls/TextEditorControl.vue'),
  {
    name: 'TextEditorLoading',
    render: () => h(Skeleton, { shape: 'block', height: '8rem' }),
  },
)
