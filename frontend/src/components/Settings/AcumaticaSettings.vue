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
        <div class="flex items-end gap-2">
          <FormControl
            v-model="settings.doc.webhook_verify_token"
            type="password"
            :label="__('Webhook Verify Token')"
            :description="tokenHint"
            class="flex-1"
          />
          <Button :label="__('Generate')" @click="generateToken" />
        </div>
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
          @click="save"
        />
        <Button
          :label="__('Test connection')"
          :loading="testing"
          :disabled="testing"
          @click="testConnection"
        />
        <Button
          :label="__('Run backfill')"
          :disabled="!settings.doc.enabled || backfilling || status?.running"
          @click="runBackfill"
        />
      </div>

      <div v-if="status" class="flex flex-col gap-2 text-p-sm text-ink-gray-6">
        <div>
          {{ __('Last synced') }} ({{ __('UTC') }}):
          {{ status.last_synced_at || __('never') }} · {{ __('Sync') }}:
          {{ status.running ? __('running') : __('idle') }} ·
          {{ __('Open sync issues') }}: {{ status.open_issues }}
        </div>
        <div v-if="status.last_sync_error" class="text-ink-red-9">
          {{ status.last_sync_error }}
        </div>
        <div v-if="status.pending_retries > 0">
          {{ __('Pending retries') }}: {{ status.pending_retries }}
        </div>

        <div class="flex flex-col gap-1">
          <div v-if="!issues.length" class="text-ink-gray-5">
            {{ __('No open sync issues') }}
          </div>
          <div
            v-for="issue in issues"
            :key="issue.name"
            class="group flex items-center gap-3 border-b border-outline-gray-1 py-2 last:border-b-0"
          >
            <div class="min-w-0 flex-1 truncate text-ink-gray-8">
              {{ issue.entity }} · {{ issue.remote_id }} · {{ issue.kind }} ·
              {{ issue.detail }} · {{ issue.detected_on }}
            </div>
            <Button
              variant="ghost"
              :label="__('Dismiss')"
              @click="dismissIssue(issue)"
            />
          </div>
        </div>
      </div>
    </template>
  </div>
</template>

<script setup>
import { ref, onMounted, onUnmounted } from 'vue'
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

const tokenHint = __(
  "Paste into Acumatica's push notification as header X-Vectora-Key. Stored encrypted; generate a new one if lost.",
)

const status = ref(null)
const issues = ref([])
const backfilling = ref(false)
const testing = ref(false)
let pollTimer = null

function save() {
  return settings.save.submit(null, {
    onSuccess: () => toast.success(__('Settings saved')),
    onError: (e) =>
      toast.error(e.messages?.[0] || __('Could not save the settings')),
  })
}

function generateToken() {
  const bytes = crypto.getRandomValues(new Uint8Array(32))
  const chars =
    'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_'
  const token = Array.from(bytes, (b) => chars[b % chars.length]).join('')
  settings.doc.webhook_verify_token = token
  toast.success(
    __('Token generated — copy it into Acumatica before you save: {0}', [
      token,
    ]),
  )
}

async function testConnection() {
  testing.value = true
  try {
    await settings.save.submit()
    const result = await call('crm.integrations.acumatica.api.test_connection')
    if (result.ok) {
      toast.success(
        __('Connected — first customer: {0}', [result.sample || '—']),
      )
    } else {
      toast.error(result.error || __('Could not connect'))
    }
  } catch (e) {
    toast.error(e.messages?.[0] || __('Could not connect'))
  } finally {
    testing.value = false
  }
}

async function loadStatus() {
  try {
    status.value = await call('crm.integrations.acumatica.api.get_sync_status')
    issues.value = await call(
      'crm.integrations.acumatica.api.get_open_sync_issues',
    )
  } catch {
    // the panel is informational; a failed read must not blow up the page
    status.value = null
    issues.value = []
  }
}

async function dismissIssue(issue) {
  try {
    await call('crm.integrations.acumatica.api.dismiss_sync_issue', {
      issue_name: issue.name,
    })
    loadStatus()
  } catch (e) {
    toast.error(e.messages?.[0] || __('Could not dismiss the issue'))
  }
}

function pollWhileRunning() {
  clearInterval(pollTimer)
  pollTimer = setInterval(async () => {
    await loadStatus()
    if (!status.value?.running) {
      clearInterval(pollTimer)
      pollTimer = null
    }
  }, 5000)
}

async function runBackfill() {
  backfilling.value = true
  try {
    await call('crm.integrations.acumatica.api.start_backfill')
    toast.success(__('Backfill queued — watch Last synced below'))
    await loadStatus()
    pollWhileRunning()
  } catch (e) {
    toast.error(e.messages?.[0] || __('Could not queue the backfill'))
  } finally {
    backfilling.value = false
  }
}

onMounted(loadStatus)
onUnmounted(() => clearInterval(pollTimer))
</script>
