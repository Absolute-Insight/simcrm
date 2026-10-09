<template>
  <div class="flex flex-col gap-3">
    <div>
      <div class="mb-2 text-sm text-ink-gray-5">
        {{ __('Lost Reason') }}
        <span class="text-ink-red-9">*</span>
      </div>
      <Link
        ref="linkRef"
        class="form-control flex-1 truncate"
        :value="lostReason"
        doctype="CRM Lost Reason"
        :onCreate="onCreate"
        @change="(v) => (lostReason = v)"
      />
    </div>
    <div>
      <div class="mb-2 text-sm text-ink-gray-5">
        {{ __('Lost Notes') }}
        <span v-if="lostReason == 'Other'" class="text-ink-red-9">*</span>
      </div>
      <FormControl
        class="form-control flex-1 truncate"
        type="textarea"
        :value="lostNotes"
        @change="(e) => (lostNotes = e.target.value)"
      />
    </div>
  </div>
</template>
<script setup>
// The Lost Reason / Lost Notes pair, shared by the single-record lost dialog
// and bulk edit. Validation stays with the caller: see lostReasonError() in
// utils/lostReason.
import Link from '@/components/Controls/Link.vue'
import { createDocument } from '@/composables/document'
import { ref } from 'vue'

const lostReason = defineModel('reason', { type: String, default: '' })
const lostNotes = defineModel('notes', { type: String, default: '' })

const linkRef = ref(null)

function onCreate(value, close) {
  createDocument('CRM Lost Reason', { lost_reason: value }, close, (doc) => {
    lostReason.value = doc.name
    linkRef.value?.reload('', true)
  })
}
</script>
