<template>
  <div class="flex h-full flex-col gap-6 p-8 overflow-y-auto">
    <div class="flex justify-between">
      <h2 class="text-xl font-semibold text-ink-gray-8">
        {{ __('Acumatica Settings') }}
      </h2>
      <CheckSwitch
        v-if="settings.doc"
        v-model="settings.doc.enabled"
        :label="settings.doc.enabled ? __('Enabled') : __('Disabled')"
      />
    </div>

    <!-- A manager whose customers are scoped may not read the settings document
         (its log names every rep's customers): they get the issues that are
         theirs below, filtered on the server, and no connection settings. -->
    <p v-if="managedElsewhere" class="text-p-base text-ink-gray-6">
      {{ __('Connection settings are managed by a System Manager.') }}
    </p>
    <ErrorState
      v-else-if="settings.get.error"
      :error="settings.get.error"
      :title="__('Could not load Acumatica settings')"
      :retry="() => settings.reload()"
    />
    <template v-else-if="settings.doc">
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
          v-model="settings.doc.quote_expiry_grace_days"
          type="number"
          :label="__('Quote Expiry Grace (days)')"
          :description="
            __(
              'Days past a quote\'s validity before the nightly sync marks its deal Expired. The deal can still be won or lost afterwards. Deals edited in the last 14 days are left alone; 0 switches this off.',
            )
          "
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
          v-model.number="settings.doc.customer_id_max_length"
          type="number"
          :label="__('Customer ID max length')"
          :description="
            __(
              'Acumatica CUSTOMER ID segment length; only used with From Organization Name',
            )
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
        <template v-if="settings.doc.create_customer_on_status_change">
          <Link
            v-model="settings.doc.deal_status"
            doctype="CRM Deal Status"
            :label="__('Deal Status')"
            :placeholder="__('Won')"
            class="w-64"
          />
          <div class="grid grid-cols-1 gap-4 sm:grid-cols-2">
            <FormControl
              v-model="settings.doc.new_customer_class"
              :label="__('New customer class')"
              placeholder="COD"
              :description="
                __(
                  'The class supplies terms, credit limit and statement cycle; Vectora never sends those.',
                )
              "
            />
            <Link
              v-model="settings.doc.home_country"
              doctype="Country"
              :label="__('Home country')"
              :placeholder="__('South Africa')"
            />
            <FormControl
              v-model="settings.doc.tax_zone_home"
              :label="__('Tax zone at home')"
              placeholder="01"
              :description="
                __('Blank leaves the tax zone to the customer class')
              "
            />
            <FormControl
              v-model="settings.doc.tax_zone_abroad"
              :label="__('Tax zone abroad')"
              placeholder="02"
              :description="
                __('Blank leaves the tax zone to the customer class')
              "
            />
          </div>
          <p class="text-p-sm text-ink-gray-6">
            {{
              __(
                'A customer is created once its organization has an address with line 1, city and country, and the deal a primary contact with a first name and an email or phone — the deal owner is told what is missing. One that looks like an existing Acumatica customer waits under sync issues below for a manager to link or confirm.',
              )
            }}
          </p>
        </template>
      </div>

      <div class="flex flex-col gap-4 border-t border-outline-elevation-2 pt-4">
        <div class="flex flex-col gap-1.5">
          <FormControl
            v-model="settings.doc.create_deals_from_quotes"
            type="checkbox"
            :label="__('Create deals from new quotes')"
          />
          <p class="text-p-sm text-ink-gray-6">
            {{
              __(
                "Each sync turns quotes raised in Acumatica into deals — owned by the quote's salesperson, Won, Lost or open as the quote is. Turning this on, or moving the date earlier, makes the next sync read every quote from that date; Run backfill does it now.",
              )
            }}
          </p>
        </div>
        <template v-if="settings.doc.create_deals_from_quotes">
          <div class="flex w-64 flex-col gap-1.5">
            <FormLabel :label="__('Quotes dated from')" />
            <DatePicker
              v-model="settings.doc.create_deals_from_quotes_since"
              variant="subtle"
              class="w-full"
            />
            <p class="text-p-sm text-ink-gray-6">
              {{ __('Older quotes never become deals, even on a backfill.') }}
            </p>
          </div>
        </template>
      </div>

      <div class="flex flex-col gap-4 border-t border-outline-elevation-2 pt-4">
        <div class="flex flex-col gap-2">
          <FormLabel :label="__('Salesperson owners')" />
          <p class="text-p-sm text-ink-gray-6">
            {{
              __(
                "Acumatica salesperson ID → CRM user, and the branch their quotes are booked in. Quotes from anyone not listed go to Administrator; a customer created from a deal gets its owner's salesperson when exactly one ID maps to them; a quote created from a deal goes to its owner's branch, or the API user's default branch when none is set.",
              )
            }}
          </p>
          <template v-if="ownersUnreadable">
            <p class="text-p-sm text-ink-red-9">
              {{
                __(
                  'The saved mapping cannot be read. Fix it below as a JSON object of salesperson ID to user email, or clear it to start over.',
                )
              }}
            </p>
            <FormControl
              v-model="settings.doc.salesperson_owners"
              type="textarea"
              :rows="4"
              :aria-label="__('Salesperson owners')"
              class="font-mono"
            />
          </template>
          <div
            v-for="(row, i) in ownersUnreadable ? [] : ownerRows"
            :key="i"
            class="flex flex-wrap items-center gap-2"
          >
            <FormControl
              v-model="row.code"
              :placeholder="__('Salesperson ID')"
              :aria-label="__('Salesperson ID')"
              class="w-40"
              @update:model-value="syncOwners"
            />
            <Link
              v-model="row.user"
              doctype="User"
              :filters="{ enabled: 1, user_type: 'System User' }"
              :placeholder="__('User')"
              class="w-64"
              @update:model-value="syncOwners"
            />
            <FormControl
              v-model="row.branch"
              :placeholder="__('Quote branch')"
              :aria-label="__('Quote branch')"
              class="w-32"
              @update:model-value="syncOwners"
            />
            <Button
              variant="ghost"
              icon="lucide-x"
              :aria-label="__('Remove')"
              @click="removeOwner(i)"
            />
          </div>
          <div v-if="!ownersUnreadable">
            <Button
              :label="__('Add salesperson')"
              icon-left="lucide-plus"
              @click="ownerRows.push({ code: '', user: '', branch: '' })"
            />
          </div>
        </div>
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
    </template>

    <template v-if="settings.doc || managedElsewhere">
      <div v-if="statusError" class="text-p-sm text-ink-orange-9">
        {{ __('Could not load the sync status.') }} {{ statusError }}
      </div>
      <div v-if="status" class="flex flex-col gap-2 text-p-sm text-ink-gray-6">
        <div>
          {{ __('Last synced') }} ({{ __('UTC') }}):
          {{ formatIssueTime(status.last_synced_at) || __('never') }} ·
          {{ __('Sync') }}: {{ status.running ? __('running') : __('idle') }} ·
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
            class="group flex flex-col gap-2 border-b border-outline-gray-1 py-2 last:border-b-0 sm:flex-row sm:items-center sm:gap-3"
          >
            <div
              class="min-w-0 flex-1 text-ink-gray-8"
              :class="needsAction(issue) ? 'break-words' : 'truncate'"
              :title="issue.detail"
            >
              {{ issue.entity }} · {{ issue.remote_id }} · {{ issue.kind }} ·
              {{ issue.detail }} · {{ formatIssueTime(issue.detected_on) }}
            </div>
            <div class="flex shrink-0 flex-wrap items-center gap-2">
              <template
                v-for="c in duplicateCandidates(issue)"
                :key="c.customerId"
              >
                <Button
                  v-if="c.canLink"
                  :label="__('Link to {0}', [c.customerId])"
                  :title="c.name"
                  :loading="resolving === `${issue.name}:${c.customerId}`"
                  :disabled="!!resolving"
                  @click="linkCustomer(issue, c)"
                />
              </template>
              <Button
                v-if="canConfirmNew(issue)"
                :label="__('Create as new')"
                :disabled="!!resolving"
                @click="askConfirmNew(issue)"
              />
              <Button
                variant="ghost"
                :label="__('Dismiss')"
                @click="dismissIssue(issue)"
              />
            </div>
          </div>
        </div>
      </div>
    </template>

    <ConfirmDialog
      v-model="confirmNew.show"
      :title="__('Create a new Acumatica customer?')"
      :message="
        hasSameVat(confirmNew.issue)
          ? __(
              '{0} has the same VAT number as an existing Acumatica customer. Create it as a new customer only if it is a separate account of that taxpayer, such as a branch. Use Link instead if it is the same account.',
              [confirmNew.issue?.remote_id],
            )
          : __(
              '{0} will be created as a new customer in Acumatica, even though it looks like an existing one. Use Link instead if it is the same business.',
              [confirmNew.issue?.remote_id],
            )
      "
      :confirm-label="__('Create as new')"
      :onConfirm="confirmNewCustomer"
      :onCancel="() => (confirmNew.show = false)"
    />
  </div>
</template>

<script setup>
import CheckSwitch from '@/components/ui/CheckSwitch.vue'
import ErrorState from '@/components/ui/ErrorState.vue'
import ConfirmDialog from '@/components/ui/ConfirmDialog.vue'
import { computed, reactive, ref, watch, onMounted, onUnmounted } from 'vue'
import {
  createDocumentResource,
  call,
  DatePicker,
  FormControl,
  FormLabel,
  Button,
  toast,
} from 'frappe-ui'
import Link from '@/components/Controls/Link.vue'
import {
  parseOwnerMap,
  serialiseBranchMap,
  serialiseOwnerMap,
} from '@/utils/salespersonOwners.js'
import {
  canConfirmNew,
  duplicateCandidates,
  formatIssueTime,
  hasSameVat,
  settingsManagedElsewhere,
} from '@/utils/acumaticaIssues.js'

const settings = createDocumentResource({
  doctype: 'CRM Acumatica Settings',
  name: 'CRM Acumatica Settings',
  auto: true,
})

// Matches the Select options on the doctype field; sending anything else silently
// falls back to AutoNumber in outbound.push_customer_for_deal.
const customerNumberingOptions = ['AutoNumber', 'From Organization Name']

const tokenHint = __(
  "Paste into Acumatica's push notification as header X-Vectora-Key. Stored encrypted; generate a new one if lost.",
)

const status = ref(null)
const statusError = ref('')
const issues = ref([])
const backfilling = ref(false)
const testing = ref(false)
let pollTimer = null
let unmounted = false

// The rows are the editor's; the doc holds their JSON. Re-read the rows only when
// the doc's value is not the one the rows just wrote (a load, a reload), so a row
// being typed into is not swept away as incomplete.
const ownerRows = ref([])
// What is stored cannot be read as a mapping: show it to fix rather than rows,
// which would overwrite it with the first edit.
const ownersUnreadable = ref(false)
let ownersWritten = null
let branchesWritten = null
watch(
  () => [settings.doc?.salesperson_owners, settings.doc?.salesperson_branches],
  ([raw, rawBranches]) => {
    if (raw === ownersWritten && rawBranches === branchesWritten) return
    const rows = parseOwnerMap(raw, rawBranches)
    ownersUnreadable.value = rows === null
    ownerRows.value = rows || []
  },
  { immediate: true },
)

function syncOwners() {
  ownersWritten = serialiseOwnerMap(ownerRows.value)
  branchesWritten = serialiseBranchMap(ownerRows.value)
  settings.doc.salesperson_owners = ownersWritten
  settings.doc.salesperson_branches = branchesWritten
}

function removeOwner(i) {
  ownerRows.value.splice(i, 1)
  syncOwners()
}

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
    statusError.value = ''
    // Follow any running sync, not just one this tab started: the nightly sweep,
    // a webhook or another admin's backfill otherwise read "running" once and
    // kept the button disabled until a reload. Not after unmount -- a read still
    // in flight then would start a timer nothing ever clears.
    if (status.value?.running && !pollTimer && !unmounted) pollWhileRunning()
  } catch (e) {
    // the panel is informational; a failed read must not blow up the page,
    // but silently showing nothing read as "no sync has ever run"
    status.value = null
    issues.value = []
    statusError.value = e?.messages?.[0] || e?.message || ''
  }
}

async function dismissIssue(issue) {
  try {
    await call('crm.integrations.acumatica.api.dismiss_sync_issue', {
      issue_name: issue.name,
    })
    await refreshAfterAction()
  } catch (e) {
    toast.error(e.messages?.[0] || __('Could not dismiss the issue'))
  }
}

// The panel's resolution actions; the server checks the role, the organization and
// the customer again, so a stale row can only be refused, never misapplied.
const resolving = ref('')
const confirmNew = reactive({ show: false, issue: null })

// The actions change the settings' sync-issue rows on the server. Reloading the doc
// keeps a later Save from carrying the copy this panel loaded before them.
async function refreshAfterAction() {
  await Promise.all([
    loadStatus(),
    managedElsewhere.value ? null : keepingEdits(() => settings.reload()),
  ])
}

// A reload replaces the doc on screen with the server's copy, which silently threw
// away an instance URL, a secret or a salesperson row typed but not yet saved --
// Dismiss on an unrelated issue row was enough. Hold the unsaved fields across the
// call and put them back (the same guard ERPNextSettings has).
async function keepingEdits(fn) {
  const edits = Object.fromEntries(
    Object.entries(settings.doc || {}).filter(
      ([field, value]) =>
        JSON.stringify(value) !== JSON.stringify(settings.originalDoc?.[field]),
    ),
  )
  // The salesperson rows are the editor's own state: the doc only holds the JSON
  // of the complete ones, so a row still being typed is in no field to restore.
  const rows = ownerRows.value
  const rowsEdited =
    'salesperson_owners' in edits ||
    'salesperson_branches' in edits ||
    rows.some((row) => !row.code?.trim() || !row.user?.trim())
  try {
    return await fn()
  } finally {
    if (settings.doc) {
      Object.assign(settings.doc, edits)
      if (rowsEdited && !ownersUnreadable.value) {
        // as syncOwners leaves it: the watcher then sees the JSON these rows wrote
        ownersWritten = settings.doc.salesperson_owners
        branchesWritten = settings.doc.salesperson_branches
        ownerRows.value = rows
      }
    }
  }
}

const managedElsewhere = computed(() =>
  settingsManagedElsewhere(settings.get.error),
)

function needsAction(issue) {
  return issue.kind === 'Possible Duplicate' || issue.kind === 'Push Blocked'
}

async function linkCustomer(issue, candidate) {
  resolving.value = `${issue.name}:${candidate.customerId}`
  try {
    await call('crm.integrations.acumatica.api.link_existing_customer', {
      organization: issue.remote_id,
      customer_id: candidate.customerId,
    })
    toast.success(
      __('{0} linked to Acumatica customer {1}', [
        issue.remote_id,
        candidate.customerId,
      ]),
    )
    await refreshAfterAction()
  } catch (e) {
    toast.error(e.messages?.[0] || __('Could not link the customer'))
  } finally {
    resolving.value = ''
  }
}

function askConfirmNew(issue) {
  confirmNew.issue = issue
  confirmNew.show = true
}

async function confirmNewCustomer({ hideDialog }) {
  const issue = confirmNew.issue
  if (!issue) return hideDialog()
  resolving.value = `${issue.name}:new`
  try {
    const out = await call(
      'crm.integrations.acumatica.api.confirm_new_customer',
      { organization: issue.remote_id },
    )
    toast.success(
      out?.queued
        ? __('{0} will be created in Acumatica shortly', [issue.remote_id])
        : __(
            '{0} is confirmed as new; it is created when one of its deals reaches the trigger status',
            [issue.remote_id],
          ),
    )
    hideDialog()
    await refreshAfterAction()
  } catch (e) {
    toast.error(e.messages?.[0] || __('Could not confirm the customer'))
  } finally {
    resolving.value = ''
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
onUnmounted(() => {
  unmounted = true
  clearInterval(pollTimer)
})
</script>
