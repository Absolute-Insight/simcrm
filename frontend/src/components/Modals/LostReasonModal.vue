<template>
  <Dialog v-model:open="show" :title="__('Lost Reason')" @close="cancel">
    <template #default>
      <div class="-mt-3 mb-4 text-p-base text-ink-gray-7">
        {{
          __('Please provide a reason for marking this {0} as lost', [
            doctype.toLowerCase().replace('crm ', ''),
          ])
        }}
      </div>
      <LostReasonFields v-model:reason="lostReason" v-model:notes="lostNotes" />
    </template>
    <template #actions>
      <div class="flex justify-between items-center gap-2">
        <div><ErrorMessage :message="error" /></div>
        <div class="flex gap-2">
          <Button :label="__('Cancel')" @click="cancel" />
          <Button variant="solid" :label="__('Save')" @click="save" />
        </div>
      </div>
    </template>
  </Dialog>
</template>
<script setup>
import LostReasonFields from '@/components/Controls/LostReasonFields.vue'
import { lostReasonError } from '@/utils/lostReason'
import { Dialog } from 'frappe-ui'
import { ref } from 'vue'

// With a `document` the modal writes the reason onto it and saves; without
// one (the Kanban board, which only has a row name) it hands the values back
// through `save` and the caller writes them.
const props = defineProps({
  doctype: { type: String, default: 'CRM Lead' },
  document: { type: Object, default: null },
})

const emit = defineEmits(['save', 'cancel'])

const show = defineModel({ type: Boolean })

const doc = props.document?.doc
const lostReason = ref(doc?.lost_reason || '')
const lostNotes = ref(doc?.lost_notes || '')
const error = ref('')

function cancel() {
  show.value = false
  error.value = ''
  lostReason.value = ''
  lostNotes.value = ''
  if (doc) {
    doc.status = props.document.originalDoc.status
  }
  emit('cancel')
}

function save() {
  error.value = lostReasonError(lostReason.value, lostNotes.value)
  if (error.value) return

  show.value = false

  if (doc) {
    doc.lost_reason = lostReason.value
    doc.lost_notes = lostNotes.value
    props.document.save.submit()
  }
  emit('save', { lost_reason: lostReason.value, lost_notes: lostNotes.value })
}
</script>
