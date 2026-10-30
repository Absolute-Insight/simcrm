<template>
  <DoctypeModal
    v-if="doctypeModal.show.value"
    v-model="doctypeModal.show.value"
    :doctypeTitle="doctypeModal.title.value"
    :doctype="doctypeModal.doctype.value"
    :docname="doctypeModal.name.value"
    :defaults="doctypeModal.defaults.value"
    @afterInsert="(d) => doctypeModal.triggerCallback('afterInsert', d)"
    @afterUpdate="(d) => doctypeModal.triggerCallback('afterUpdate', d)"
  />
</template>
<script setup>
import { useDoctypeModal } from '@/composables/doctypeModal'
import { defineAsyncComponent } from 'vue'

/* Loaded on first open. App.vue mounts this on every page, and a static
   import put the modal's field layout -- every control, the rich-text editor
   (tiptap, ProseMirror, lowlight) with them -- into the boot chunks that every
   cold start fetches and evaluates, for a modal most visits never open. */
const DoctypeModal = defineAsyncComponent(
  () => import('@/components/Modals/DoctypeModal.vue'),
)

const doctypeModal = useDoctypeModal()
</script>
