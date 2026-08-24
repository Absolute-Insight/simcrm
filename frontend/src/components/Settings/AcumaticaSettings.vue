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
          v-model="settings.doc.endpoint_version"
          :label="__('Endpoint Version')"
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
          :disabled="!settings.doc.enabled"
          @click="runBackfill"
        />
      </div>

      <div v-if="status" class="text-p-sm text-ink-gray-6">
        {{ __('Last synced') }}: {{ status.last_synced_at || __('never') }} ·
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

const settings = createDocumentResource({
  doctype: 'CRM Acumatica Settings',
  name: 'CRM Acumatica Settings',
  auto: true,
})

const status = ref(null)

async function loadStatus() {
  status.value = await call('crm.integrations.acumatica.api.get_sync_status')
}

async function runBackfill() {
  await call('crm.integrations.acumatica.api.start_backfill')
  toast.success(__('Backfill queued — watch Last synced below'))
  loadStatus()
}

onMounted(loadStatus)
</script>
