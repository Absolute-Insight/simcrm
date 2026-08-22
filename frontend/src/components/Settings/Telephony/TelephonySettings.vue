<template>
  <div class="flex h-full flex-col gap-6 px-6 py-8">
    <!-- Header -->
    <div class="flex justify-between px-2 text-ink-gray-8">
      <div class="flex flex-col gap-1 w-9/12">
        <h2
          class="flex gap-2 text-2xl-semibold leading-none h-5 text-ink-gray-8"
        >
          {{ __('Telephony Settings') }}
          <ToneBadge
            v-if="isDirty"
            :label="__('Not Saved')"
            variant="subtle"
            theme="orange"
          />
        </h2>
        <p class="text-p-base text-ink-gray-6">
          {{ __('Configure telephony settings for your CRM') }}
        </p>
      </div>
      <div class="flex item-center space-x-2 w-3/12 justify-end">
        <Button
          v-if="isDirty"
          :loading="saving"
          :label="__('Update')"
          variant="solid"
          @click="update"
        />
      </div>
    </div>

    <div v-if="telephonyAgent.doc" class="flex-1 flex flex-col overflow-y-auto">
      <div class="flex items-center justify-between gap-8 py-3 pl-2 pr-1">
        <div class="flex flex-col">
          <div class="text-p-base-medium text-ink-gray-7 truncate">
            {{ __('Default Medium') }}
          </div>
          <div class="text-p-sm text-ink-gray-5">
            {{ __('Default calling medium for logged-in user') }}
          </div>
        </div>
        <div class="flex items-center gap-1">
          <FormControl
            v-model="telephonyAgent.doc.default_medium"
            type="select"
            class="w-44 p-1"
            :options="[
              { label: __(''), value: '' },
              { label: __('Twilio'), value: 'Twilio' },
              { label: __('Exotel'), value: 'Exotel' },
            ]"
            :placeholder="__('Select Medium')"
          />
          <Button
            v-if="telephonyAgent.doc.default_medium"
            icon="lucide-x"
            :tooltip="__('Clear')"
            @click="telephonyAgent.doc.default_medium = ''"
          />
        </div>
      </div>
      <div
        v-if="isEnabled('twilio')"
        class="h-px border-t mx-2 border-outline-elevation-2"
      />
      <div
        v-if="isEnabled('twilio')"
        class="flex items-center justify-between gap-8 py-3 pl-2 pr-1"
      >
        <div class="flex flex-col">
          <div class="text-p-base-medium text-ink-gray-7 truncate">
            {{ __('Twilio Number') }}
          </div>
          <div class="text-p-sm text-ink-gray-5">
            {{ __('Set the Twilio number to be used for outgoing calls.') }}
          </div>
        </div>
        <div>
          <FormControl
            v-model="telephonyAgent.doc.twilio_number"
            class="flex-1 truncate w-44 p-1"
            :placeholder="__('Enter Twilio Number')"
            :error="
              Boolean(telephonyAgent.doc.twilio_number) &&
              !validatePhone(telephonyAgent.doc.twilio_number)
                ? __('Enter a valid phone number')
                : undefined
            "
            placement="bottom-end"
          />
        </div>
      </div>
      <div
        v-if="isEnabled('exotel')"
        class="h-px border-t mx-2 border-outline-elevation-2"
      />
      <div
        v-if="isEnabled('exotel')"
        class="flex items-center justify-between gap-8 py-3 pl-2 pr-1"
      >
        <div class="flex flex-col">
          <div class="text-p-base-medium text-ink-gray-7 truncate">
            {{ __('Exotel Number') }}
          </div>
          <div class="text-p-sm text-ink-gray-5">
            {{ __('Set the Exotel number to be used for outgoing calls.') }}
          </div>
        </div>
        <div>
          <FormControl
            v-model="telephonyAgent.doc.exotel_number"
            class="flex-1 truncate w-44 p-1"
            :placeholder="__('Enter Exotel Number')"
            :error="
              Boolean(telephonyAgent.doc.exotel_number) &&
              !validatePhone(telephonyAgent.doc.exotel_number)
                ? __('Enter a valid phone number')
                : undefined
            "
            placement="bottom-end"
          />
        </div>
      </div>
      <div
        v-if="isEnabled('exotel')"
        class="flex items-center justify-between gap-8 py-3 pl-2 pr-1"
      >
        <div class="flex flex-col">
          <div class="text-p-base-medium text-ink-gray-7 truncate">
            {{ __('Personal Mobile Number') }}
          </div>
          <div class="text-p-sm text-ink-gray-5">
            {{
              __(
                'Enter your personal mobile number used by Exotel to make calls',
              )
            }}
          </div>
        </div>
        <div>
          <FormControl
            v-model="telephonyAgent.doc.mobile_no"
            class="flex-1 truncate w-44 p-1"
            :placeholder="__('Enter Personal Mobile Number')"
            :error="
              Boolean(telephonyAgent.doc.mobile_no) &&
              !validatePhone(telephonyAgent.doc.mobile_no)
                ? __('Enter a valid phone number')
                : undefined
            "
            placement="bottom-end"
          />
        </div>
      </div>

      <div
        v-if="isManager()"
        class="flex items-center justify-between text-lg-semibold text-ink-gray-8 mt-4 py-3 px-2"
      >
        {{ __('Integrations') }}
      </div>

      <div
        v-if="isManager()"
        class="flex items-center justify-between py-3 px-2"
      >
        <div class="flex flex-col gap-1">
          <span class="text-base-medium text-ink-gray-8">
            {{ __('Twilio') }}
          </span>
          <span class="text-p-sm text-ink-gray-6">
            {{
              __('Configure your Twilio telephony integration settings here')
            }}
          </span>
        </div>
        <Button
          :label="
            isEnabled('twilio') ? __('Update Configuration') : __('Configure')
          "
          @click="emit('updateStep', 'twilio-settings')"
        />
      </div>

      <div
        v-if="isManager()"
        class="h-px border-t mx-2 border-outline-elevation-2"
      />

      <div
        v-if="isManager()"
        class="flex items-center justify-between py-3 px-2"
      >
        <div class="flex flex-col gap-1">
          <span class="text-base-medium text-ink-gray-8">
            {{ __('Exotel') }}
          </span>
          <span class="text-p-sm text-ink-gray-6">
            {{
              __('Configure your Exotel telephony integration settings here')
            }}
          </span>
        </div>
        <Button
          :label="
            isEnabled('exotel') ? __('Update Configuration') : __('Configure')
          "
          @click="emit('updateStep', 'exotel-settings')"
        />
      </div>
    </div>
    <ErrorMessage :message="saveError" />
  </div>
</template>
<script setup>
import ToneBadge from '@/components/ui/ToneBadge.vue'
import { FormControl, ErrorMessage, createResource, toast } from 'frappe-ui'
import { useTelephony } from '@/composables/telephony'
import { usersStore } from '@/stores/users'
import { validatePhone } from '@/utils'
import { computed, reactive, ref } from 'vue'

const { isEnabled } = useTelephony()

const emit = defineEmits(['updateStep'])

const { getUser, isManager } = usersStore()

const FIELDS = [
  'name',
  'default_medium',
  'twilio_number',
  'exotel_number',
  'mobile_no',
]

const telephonyAgent = reactive({ doc: null, originalDoc: null })
const isNewDoc = ref(false)

/**
 * A user who has never saved telephony settings has no `CRM Telephony Agent`,
 * and `frappe.client.get` answers 404 for that -- twice, once for the document
 * and once for its permissions. The pane already treated that as "new
 * document" and rendered correctly, but frappe-ui's resource layer rethrows
 * after running `onError`, so both 404s still surfaced as uncaught rejections
 * on every visit and would reach any error monitor wired up in production.
 *
 * `get_value` answers 200 with `{}` for the same query, so the empty case
 * arrives as data instead of as an error, and the pane makes one request
 * rather than two.
 */
createResource({
  url: 'frappe.client.get_value',
  auto: true,
  params: {
    doctype: 'CRM Telephony Agent',
    filters: { user: getUser().name },
    fieldname: FIELDS,
  },
  onSuccess: (data) => applyDoc(data),
  onError: (err) => err.messages?.forEach((msg) => toast.error(msg)),
})

// Keep the editable document to the fields this pane owns, so `isDirty`
// compares like with like and a save sends only what the form can change.
function applyDoc(data) {
  const exists = Boolean(data?.name)
  const doc = {}
  for (const field of FIELDS) doc[field] = exists ? data[field] ?? null : null
  if (!exists) delete doc.name

  isNewDoc.value = !exists
  telephonyAgent.doc = doc
  telephonyAgent.originalDoc = { ...doc }
}

const insertResource = createResource({
  url: 'frappe.client.insert',
  onSuccess: (data) => {
    applyDoc(data)
    toast.success(__('Document created successfully'))
  },
  onError: (err) => {
    err.messages?.forEach((msg) => toast.error(msg))
  },
})

const saveResource = createResource({
  url: 'frappe.client.set_value',
  onSuccess: (data) => {
    applyDoc(data)
    toast.success(__('Document updated successfully'))
  },
  onError: (err) => {
    err.messages?.forEach((msg) => toast.error(msg))
  },
})

const saving = computed(() =>
  isNewDoc.value ? insertResource.loading : saveResource.loading,
)

const saveError = computed(() =>
  isNewDoc.value ? insertResource.error : saveResource.error,
)

function update() {
  if (!isDirty.value) return

  if (isNewDoc.value) {
    insertResource.submit({
      doc: {
        doctype: 'CRM Telephony Agent',
        user: getUser().name,
        ...telephonyAgent.doc,
      },
    })
  } else {
    const { name, ...values } = telephonyAgent.doc
    saveResource.submit({
      doctype: 'CRM Telephony Agent',
      name,
      fieldname: values,
    })
  }
}

const isDirty = computed(() => {
  return (
    telephonyAgent.doc &&
    telephonyAgent.originalDoc &&
    JSON.stringify(telephonyAgent.doc) !==
      JSON.stringify(telephonyAgent.originalDoc)
  )
})
</script>
