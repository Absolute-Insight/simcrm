<template>
  <div class="flex h-full flex-col gap-6 p-8 overflow-y-auto">
    <div class="flex justify-between">
      <h2 class="text-xl font-semibold text-ink-gray-8">
        {{ __('Acumatica Settings') }}
      </h2>
      <Switch
        v-if="settings.doc"
        v-model="settings.doc.enabled"
        :label="settings.doc.enabled ? __('Enabled') : __('Disabled')"
      />
    </div>

    <template v-if="settings.doc">
      <div class="grid grid-cols-2 gap-4">
        <FormControl
          v-model="settings.doc.instance_url"
          :label="__('Instance URL')"
          placeholder="https://tenant.acumatica.com"
        />
        <FormControl
          v-model="settings.doc.endpoint_name"
          :label="__('Endpoint Name')"
          placeholder="Default"
        />
        <FormControl
          v-model="settings.doc.endpoint_version"
          :label="__('Endpoint Version')"
        />
        <FormControl
          v-model="settings.doc.branch"
          :label="__('Branch')"
          :description="__('Optional; only needed on multi-branch instances')"
        />
        <FormControl
          v-model="settings.doc.client_id"
          :label="__('Client ID')"
        />
        <FormControl
          v-model="settings.doc.client_secret"
          type="password"
          :label="__('Client Secret')"
        />
        <FormControl
          v-model="settings.doc.username"
          :label="__('API Username')"
        />
        <FormControl
          v-model="settings.doc.password"
          type="password"
          :label="__('API Password')"
        />
        <FormControl
          v-model="settings.doc.quote_order_type"
          :label="__('Quote Order Type')"
        />
        <FormControl
          v-model="settings.doc.webhook_verify_token"
          :label="__('Webhook Verify Token')"
        />
        <FormControl
          v-model="settings.doc.customer_numbering"
          type="select"
          :options="customerNumberingOptions"
          :label="__('Customer Numbering')"
          :description="
            __('How the CustomerID is chosen when a customer is created')
          "
        />
        <FormControl
          v-model.number="settings.doc.request_pause"
          type="number"
          step="0.1"
          :label="__('Request Pause (seconds)')"
          :description="__('Throttles paging; API licences cap request rates')"
        />
      </div>

      <div class="flex flex-col gap-4 border-t border-outline-elevation-2 pt-4">
        <FormControl
          v-model="settings.doc.create_customer_on_status_change"
          type="checkbox"
          :label="__('Create the customer in Acumatica on deal status change')"
        />
        <Link
          v-if="settings.doc.create_customer_on_status_change"
          v-model="settings.doc.deal_status"
          doctype="CRM Deal Status"
          :label="__('Deal Status')"
          :placeholder="__('Won')"
          class="w-64"
        />
      </div>

      <div class="flex items-center gap-3">
        <Button
          :label="__('Save')"
          variant="solid"
          :loading="settings.save.loading"
          @click="settings.save.submit()"
        />
        <Button
          :label="__('Run backfill')"
          :disabled="!settings.doc.enabled || backfilling"
          @click="runBackfill"
        />
      </div>

      <div v-if="status" class="text-p-sm text-ink-gray-6">
        {{ __('Last synced') }} ({{ __('UTC') }}):
        {{ status.last_synced_at || __('never') }} ·
        {{ __('Open sync issues') }}: {{ status.open_issues }}
      </div>
    </template>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import {
  createDocumentResource,
  call,
  FormControl,
  Button,
  Switch,
  toast,
} from 'frappe-ui'
import Link from '@/components/Controls/Link.vue'

const settings = createDocumentResource({
  doctype: 'CRM Acumatica Settings',
  name: 'CRM Acumatica Settings',
  auto: true,
})

// Matches the Select options on the doctype field; sending anything else silently
// falls back to AutoNumber in outbound.create_customer_in_acumatica.
const customerNumberingOptions = ['AutoNumber', 'From Organization Name']

const status = ref(null)
const backfilling = ref(false)

async function loadStatus() {
  try {
    status.value = await call('crm.integrations.acumatica.api.get_sync_status')
  } catch (e) {
    // the panel is informational; a failed read must not blow up the page
    status.value = null
  }
}

async function runBackfill() {
  backfilling.value = true
  try {
    await call('crm.integrations.acumatica.api.start_backfill')
    toast.success(__('Backfill queued — watch Last synced below'))
    loadStatus()
  } catch (e) {
    toast.error(e.messages?.[0] || __('Could not queue the backfill'))
  } finally {
    backfilling.value = false
  }
}

onMounted(loadStatus)
</script>
