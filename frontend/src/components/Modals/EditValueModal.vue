<template>
  <Dialog v-model:open="show" :title="__('Bulk Edit')">
    <template #default>
      <div class="mb-4">
        <div class="mb-1.5 text-sm text-ink-gray-5">{{ __('Field') }}</div>
        <Combobox
          class="w-full"
          trigger="button"
          :model-value="field.fieldname"
          :options="fields.data || []"
          :placeholder="__('Source')"
          @update:selected-option="(e) => changeField(e)"
        />
      </div>
      <div>
        <div class="mb-1.5 text-sm text-ink-gray-5">{{ __('Value') }}</div>
        <component
          :is="getValueComponent(field)"
          :value="newValue"
          size="md"
          :placeholder="__('Contact Us')"
          @change="(v) => updateValue(v)"
        />
      </div>
      <!-- A Lost-type status is refused by validate_lost_reason without a
           reason, so ask for it here rather than have every record fail. -->
      <LostReasonFields
        v-if="isLostStatus"
        v-model:reason="lostReason"
        v-model:notes="lostNotes"
        class="mt-4"
      />
      <ErrorMessage v-if="error" class="mt-4" :message="error" />
    </template>
    <template #actions>
      <Button
        class="w-full"
        variant="solid"
        :loading="loading"
        :label="__('Update {0} Records', [recordCount])"
        @click="updateValues"
      />
    </template>
  </Dialog>
</template>

<script setup>
import Link from '@/components/Controls/Link.vue'
import LostReasonFields from '@/components/Controls/LostReasonFields.vue'
import { statusesStore } from '@/stores/statuses'
import { lostReasonError, bulkUpdateOutcome } from '@/utils/lostReason'
import { useTelemetry } from '@framework/ui/telemetry'
import {
  Combobox,
  FormControl,
  call,
  createResource,
  DatePicker,
  toast,
} from 'frappe-ui'
// parked in experimental for v1 (frappe-ui migration doc)
import { TextEditor } from 'frappe-ui/experimental'
import { ref, computed, onMounted, h } from 'vue'
import { reportActionError } from '@/utils/reportActionError'

const typeCheck = ['Check']
const typeLink = ['Link', 'Dynamic Link']
const typeNumber = ['Float', 'Int', 'Currency', 'Percent']
const typeSelect = ['Select']
const typeEditor = ['Text Editor']
const typeDate = ['Date', 'Datetime']

const props = defineProps({
  doctype: { type: String, required: true },
  selectedValues: { type: Set, required: true },
})

const show = defineModel({ type: Boolean })

const emit = defineEmits(['reload'])

const { capture } = useTelemetry()

const fields = createResource({
  url: 'crm.api.doc.get_fields',
  cache: ['fields', props.doctype],
  params: {
    doctype: props.doctype,
  },
  transform: (data) => {
    // `description` renders as a second line in the dropdown, which has no
    // max width, so a long one stretches the whole list.
    return data
      .filter((f) => f.hidden == 0 && f.read_only == 0)
      .map(({ description, ...f }) => ({ ...f, value: f.fieldname }))
  },
})

onMounted(() => {
  if (fields.data?.length) return
  fields.fetch()
})

const recordCount = computed(() => props.selectedValues?.size || 0)

const field = ref({
  label: '',
  fieldtype: '',
  fieldname: '',
  options: '',
})

const newValue = ref('')
const loading = ref(false)
const error = ref('')

const { getLeadStatus, getDealStatus } = statusesStore()

const lostReason = ref('')
const lostNotes = ref('')

const isLostStatus = computed(() => {
  if (field.value.fieldname !== 'status' || !newValue.value) return false
  if (props.doctype === 'CRM Lead') {
    return getLeadStatus(newValue.value)?.type === 'Lost'
  }
  if (props.doctype === 'CRM Deal') {
    return getDealStatus(newValue.value)?.type === 'Lost'
  }
  return false
})

function updateValues() {
  error.value = ''
  let fieldVal = newValue.value
  if (field.value.fieldtype == 'Check') {
    fieldVal = fieldVal == 'Yes' ? 1 : 0
  }

  const data = { [field.value.fieldname]: fieldVal || null }
  if (isLostStatus.value) {
    error.value = lostReasonError(lostReason.value, lostNotes.value)
    if (error.value) return
    data.lost_reason = lostReason.value
    data.lost_notes = lostNotes.value
  }

  loading.value = true
  call(
    'frappe.desk.doctype.bulk_update.bulk_update.submit_cancel_or_update_docs',
    {
      doctype: props.doctype,
      docnames: Array.from(props.selectedValues),
      action: 'update',
      data,
    },
  )
    .then((result) => {
      loading.value = false
      // Under 20 records frappe saves inline and returns the docnames that
      // failed validation instead of raising, so a silent "success" could
      // have changed nothing. Keep the dialog open and name them.
      const outcome = bulkUpdateOutcome(result)
      if (outcome.status === 'failed') {
        error.value = __('Failed to update {0} record(s): {1}', [
          outcome.failed.length,
          outcome.failed.join(', '),
        ])
        emit('reload')
        return
      }
      field.value = {
        label: '',
        fieldtype: '',
        fieldname: '',
        options: '',
      }
      newValue.value = ''
      lostReason.value = ''
      lostNotes.value = ''
      show.value = false
      capture('bulk_update', { doctype: props.doctype })
      emit('reload')
      if (outcome.status === 'enqueued') {
        toast.info(
          __(
            'Bulk operation is enqueued in background. Failures, if any, are recorded in Error Log.',
          ),
        )
      }
    })
    .catch((err) => {
      loading.value = false
      reportActionError(err, __('Could not update the records.'))
    })
}

function changeField(f) {
  newValue.value = ''
  lostReason.value = ''
  lostNotes.value = ''
  error.value = ''
  if (!f) return
  field.value = f
}

function updateValue(v) {
  let value = v.target ? v.target.value : v
  newValue.value = value
}

function getSelectOptions(options) {
  return options.split('\n')
}

function getValueComponent(f) {
  const { fieldtype, options } = f
  if (typeSelect.includes(fieldtype) || typeCheck.includes(fieldtype)) {
    const _options =
      fieldtype == 'Check' ? ['Yes', 'No'] : getSelectOptions(options)
    return h(FormControl, {
      type: 'select',
      options: _options.map((o) => ({
        label: o,
        value: o,
      })),
      modelValue: newValue.value,
    })
  } else if (typeLink.includes(fieldtype)) {
    if (fieldtype == 'Dynamic Link') {
      return h(FormControl, { type: 'text' })
    }
    return h(Link, { class: 'form-control', doctype: options })
  } else if (typeNumber.includes(fieldtype)) {
    return h(FormControl, { type: 'number' })
  } else if (typeDate.includes(fieldtype)) {
    return h(DatePicker)
  } else if (typeEditor.includes(fieldtype)) {
    return h(TextEditor, {
      variant: 'outline',
      editorClass:
        '!prose-sm overflow-auto min-h-[80px] max-h-80 py-1.5 px-2 rounded-[var(--v-radius-control)] border border-outline-gray-2 bg-surface-base hover:border-outline-gray-3 hover:shadow-sm focus:bg-surface-base focus:border-outline-gray-4 focus:ring-0 focus-visible:ring-2 focus-visible:ring-outline-gray-3 text-ink-gray-8 transition-colors',
      bubbleMenu: true,
      content: newValue.value,
    })
  } else {
    return h(FormControl, { type: 'text' })
  }
}
</script>
