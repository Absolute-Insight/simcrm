<template>
  <div class="flex h-full flex-col gap-4 p-8">
    <div class="flex items-start justify-between gap-4">
      <div class="flex flex-col gap-1">
        <h2 class="v-title text-ink-gray-8">{{ __('Report Digests') }}</h2>
        <p class="text-p-sm text-ink-gray-5">
          {{
            __(
              'Mail a report to people on a schedule. Each recipient gets it rendered as themselves — a rep sees their own rows, a manager sees their team’s.',
            )
          }}
        </p>
      </div>
      <Button
        variant="solid"
        :label="__('New digest')"
        class="shrink-0"
        @click="openEditor(null)"
      >
        <template #prefix><LucidePlus class="size-4" /></template>
      </Button>
    </div>

    <div v-if="digests.loading" class="flex flex-col gap-3">
      <Skeleton shape="text" width="60%" :label="__('Loading digests')" />
      <Skeleton shape="block" width="100%" height="4rem" />
    </div>

    <ErrorState
      v-else-if="digests.error"
      :error="digests.error"
      :title="__('Could not load digests')"
      :retry="() => digests.reload()"
    />

    <div
      v-else-if="!digests.data?.length"
      class="flex flex-1 flex-col items-center justify-center gap-1 text-center"
    >
      <LucideMailCheck class="size-7 text-ink-gray-4" />
      <div class="text-base text-ink-gray-6">{{ __('No digests yet') }}</div>
      <div class="max-w-sm text-sm text-ink-gray-5">
        {{
          __(
            'A first one worth having: quota attainment by rep, weekly, to your sales managers.',
          )
        }}
      </div>
    </div>

    <div v-else class="min-h-0 flex-1 overflow-y-auto">
      <div
        v-for="digest in digests.data"
        :key="digest.name"
        class="group flex items-center gap-3 border-b border-outline-gray-1 px-1 py-2.5 last:border-b-0"
      >
        <Switch
          :model-value="!!digest.enabled"
          size="sm"
          @update:model-value="toggle(digest, $event)"
        />
        <button
          class="flex min-w-0 flex-1 flex-col items-start text-left"
          @click="openEditor(digest)"
        >
          <span class="truncate text-base text-ink-gray-8">
            {{ reportTitle(digest.report) }}
          </span>
          <span class="truncate text-sm text-ink-gray-5">
            {{ describe(digest) }}
          </span>
        </button>
        <Badge
          v-if="!digest.enabled"
          :label="__('Paused')"
          variant="subtle"
          theme="gray"
        />
        <Button
          class="opacity-0 transition group-hover:opacity-100"
          variant="ghost"
          icon="lucide-trash-2"
          :aria-label="__('Delete digest')"
          @click="askDelete(digest)"
        />
      </div>
    </div>

    <Dialog
      v-model="editorOpen"
      :title="draft.name ? __('Edit digest') : __('New digest')"
    >
      <template #default>
        <div class="flex flex-col gap-4">
          <!-- Options come from the report registry, so a report added to the
               product shows up here without this file being touched. -->
          <FormControl
            v-model="draft.report"
            type="select"
            :label="__('Report')"
            :options="reportOptions"
            :description="reportDescription"
          />

          <FormControl
            v-model="draft.frequency"
            type="select"
            :label="__('How often')"
            :options="frequencies"
            :description="
              draft.frequency === 'Weekly'
                ? __('Sent on Mondays, covering the previous seven days.')
                : __('Sent every morning, covering the previous day.')
            "
          />

          <FormControl
            v-model="draft.recipients"
            type="textarea"
            :rows="3"
            :label="__('Recipients')"
            :placeholder="'ana@example.com, sam@example.com'"
            :description="
              __(
                'Comma-separated. A digest carries deal values, so each address must belong to an enabled user of this site who holds a CRM role — entitlement is checked again at send, so someone offboarded stops receiving it.',
              )
            "
          />

          <div class="flex items-center gap-3">
            <Switch
              :model-value="!!draft.enabled"
              size="sm"
              :label="__('Enabled')"
              @update:model-value="draft.enabled = $event ? 1 : 0"
            />
          </div>

          <ErrorMessage :message="saveError" />
        </div>
      </template>
      <template #actions>
        <div class="flex justify-end gap-2">
          <Button :label="__('Cancel')" @click="editorOpen = false" />
          <Button
            variant="solid"
            :label="__('Save digest')"
            :loading="saving"
            @click="save"
          />
        </div>
      </template>
    </Dialog>

    <ConfirmDialog
      v-model="deleteOpen"
      :title="__('Delete digest')"
      :message="
        __('Stop sending “{0}”? This cannot be undone.', [
          reportTitle(pendingDelete?.report),
        ])
      "
      :on-confirm="confirmDelete"
    />
  </div>
</template>

<script setup>
import LucidePlus from '~icons/lucide/plus'
import LucideMailCheck from '~icons/lucide/mail-check'
import ConfirmDialog from '@/components/ui/ConfirmDialog.vue'
import ErrorState from '@/components/ui/ErrorState.vue'
import Skeleton from '@/components/ui/Skeleton.vue'
import { actionErrorMessage } from '@/utils/reportActionError'
import {
  Badge,
  Button,
  Dialog,
  ErrorMessage,
  FormControl,
  Switch,
  call,
  createListResource,
  createResource,
  toast,
} from 'frappe-ui'
import { computed, reactive, ref } from 'vue'

const frequencies = computed(() => [
  { label: __('Daily'), value: 'Daily' },
  { label: __('Weekly'), value: 'Weekly' },
])

const EMPTY = {
  name: null,
  report: '',
  frequency: 'Weekly',
  enabled: 1,
  recipients: '',
}

/* The same endpoint the Reports page lists from, so the two cannot disagree
   about what this site publishes. The digest doctype's own Select is asserted
   equal to that registry in test_report_digest, and validate() refuses a
   report the site does not publish — the send loop skips an unknown key
   silently, which is right for a withdrawn report but would otherwise make a
   typo into mail that never arrives. */
const reports = createResource({
  url: 'crm.api.reports.list_reports',
  auto: true,
  initialData: [],
})

const reportOptions = computed(() =>
  (reports.data || []).map((r) => ({ label: r.title, value: r.name })),
)

const reportTitle = (name) =>
  (reports.data || []).find((r) => r.name === name)?.title || name || ''

const reportDescription = computed(
  () => (reports.data || []).find((r) => r.name === draft.report)?.description,
)

const digests = createListResource({
  doctype: 'CRM Report Digest',
  fields: ['name', 'report', 'frequency', 'enabled', 'recipients'],
  orderBy: 'modified desc',
  pageLength: 100,
  auto: true,
})

const editorOpen = ref(false)
const saving = ref(false)
const saveError = ref('')
const draft = reactive({ ...EMPTY })

const deleteOpen = ref(false)
const pendingDelete = ref(null)

function recipientCount(digest) {
  return (digest.recipients || '').split(',').filter((e) => e.trim()).length
}

function describe(digest) {
  const when = digest.frequency === 'Weekly' ? __('Weekly') : __('Daily')
  const count = recipientCount(digest)
  return `${when} · ${__('{0} recipients', [count])}`
}

function openEditor(digest) {
  Object.assign(draft, digest ? { ...EMPTY, ...digest } : { ...EMPTY })
  if (!draft.report) draft.report = reports.data?.[0]?.name || ''
  saveError.value = ''
  editorOpen.value = true
}

async function save() {
  saveError.value = ''
  if (!draft.report) {
    saveError.value = __('Choose a report.')
    return
  }
  if (!draft.recipients?.trim()) {
    saveError.value = __('Add at least one recipient.')
    return
  }
  saving.value = true
  const { name, ...values } = draft
  try {
    if (name) {
      await digests.setValue.submit({ name, ...values })
    } else {
      await digests.insert.submit(values)
    }
    await digests.reload()
    editorOpen.value = false
    toast.success(__('Digest saved'))
  } catch (error) {
    /* The server's own message is the useful one here — "sam@example.com has no
       CRM role, so they cannot receive CRM data" tells the admin exactly which
       address to fix. actionErrorMessage only supplies a fallback. */
    saveError.value = actionErrorMessage(
      error,
      __('Could not save the digest.'),
    )
  } finally {
    saving.value = false
  }
}

async function toggle(digest, enabled) {
  const previous = digest.enabled
  digest.enabled = enabled ? 1 : 0
  try {
    await call('frappe.client.set_value', {
      doctype: 'CRM Report Digest',
      name: digest.name,
      fieldname: 'enabled',
      value: enabled ? 1 : 0,
    })
  } catch (error) {
    digest.enabled = previous
    toast.error(actionErrorMessage(error, __('Could not change the digest.')))
  }
}

function askDelete(digest) {
  pendingDelete.value = digest
  deleteOpen.value = true
}

async function confirmDelete({ hideDialog }) {
  try {
    await digests.delete.submit(pendingDelete.value.name)
    await digests.reload()
    hideDialog()
    toast.success(__('Digest deleted'))
  } catch (error) {
    toast.error(actionErrorMessage(error, __('Could not delete the digest.')))
  }
}
</script>
