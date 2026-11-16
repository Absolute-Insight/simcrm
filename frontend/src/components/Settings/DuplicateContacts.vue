<template>
  <div class="flex h-full flex-col gap-4 p-8">
    <div class="flex flex-col gap-1">
      <h2 class="v-title text-ink-gray-8">
        {{ __('Duplicate Contacts') }}
      </h2>
      <p class="text-p-sm text-ink-gray-5">
        {{
          __(
            'Contacts that share an email address. Keep one and merge the others into it: their deals, events, calls and emails move to the one you keep, along with any address or number it lacks, and the others are deleted.',
          )
        }}
      </p>
    </div>

    <SkeletonTable
      v-if="duplicates.loading && !duplicates.data"
      :columns="5"
      :rows="6"
      density="compact"
      class="flex-1 px-1"
      :label="__('Loading duplicate contacts')"
    />

    <ErrorState
      v-else-if="duplicates.error"
      class="flex-1"
      :error="duplicates.error"
      :title="__('Could not load the duplicate contacts')"
      :retry="duplicates.reload"
    />

    <div
      v-else-if="!groups.length"
      class="flex flex-1 flex-col items-center justify-center gap-1 text-center"
    >
      <LucideUsersThree class="size-7 text-ink-gray-4" />
      <div class="text-base text-ink-gray-6">
        {{ __('No duplicate contacts') }}
      </div>
      <div class="text-sm text-ink-gray-5">
        {{ __('No two contacts you can see share an email address.') }}
      </div>
    </div>

    <div v-else class="flex min-h-0 flex-1 flex-col gap-3 overflow-auto">
      <section
        v-for="group in groups"
        :key="group.email"
        class="rounded-5 border border-outline-gray-1"
      >
        <header
          class="flex items-center justify-between gap-3 border-b border-outline-gray-1 bg-surface-gray-1 px-3 py-2"
        >
          <span class="truncate text-base font-medium text-ink-gray-8">
            {{ group.email }}
          </span>
          <span class="shrink-0 text-sm text-ink-gray-5">
            {{ __('{0} contacts', [group.contacts.length]) }}
          </span>
        </header>
        <div class="overflow-x-auto">
          <table class="min-w-full text-base">
            <thead>
              <tr>
                <th
                  v-for="column in COLUMNS"
                  :key="column.key"
                  class="whitespace-nowrap px-3 py-1.5 text-xs font-medium uppercase tracking-wider text-ink-gray-5"
                  :class="column.align === 'right' ? 'text-right' : 'text-left'"
                >
                  {{ column.label }}
                </th>
                <th class="w-24 px-3 py-1.5">
                  <span class="sr-only">{{ __('Actions') }}</span>
                </th>
              </tr>
            </thead>
            <tbody>
              <tr
                v-for="contact in group.contacts"
                :key="contact.name"
                class="border-t border-outline-gray-1"
              >
                <td class="max-w-56 px-3 py-1.5">
                  <router-link
                    :to="{
                      name: 'Contact',
                      params: { contactId: contact.name },
                    }"
                    class="block truncate text-ink-gray-8 underline-offset-2 hover:underline"
                    :title="contact.name"
                    @click="closeSettings"
                  >
                    {{ contact.full_name || contact.name }}
                  </router-link>
                </td>
                <td
                  class="max-w-48 truncate px-3 py-1.5 text-ink-gray-7"
                  :title="contact.company_name || ''"
                >
                  {{ contact.company_name || '—' }}
                </td>
                <td class="whitespace-nowrap px-3 py-1.5 text-ink-gray-7">
                  {{ userName(contact.customer_owner) }}
                </td>
                <td class="whitespace-nowrap px-3 py-1.5 text-ink-gray-7">
                  {{ userName(contact.owner) }}
                </td>
                <td
                  class="whitespace-nowrap px-3 py-1.5 text-right tabular-nums text-ink-gray-7"
                >
                  {{ contact.deals }}
                </td>
                <td
                  class="whitespace-nowrap px-3 py-1.5 text-right tabular-nums text-ink-gray-5"
                >
                  {{ formatCreated(contact.creation) }}
                </td>
                <td class="px-3 py-1 text-right">
                  <Button
                    size="sm"
                    :label="__('Keep')"
                    :tooltip="__('Merge the others into this one')"
                    :disabled="merging"
                    @click="askMerge(group, contact)"
                  />
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </section>
    </div>

    <div
      v-if="total > PAGE_LENGTH"
      class="flex shrink-0 items-center justify-between gap-3"
    >
      <span class="text-sm text-ink-gray-5 tabular-nums">
        {{
          __('{0}–{1} of {2} addresses', [
            start + 1,
            Math.min(start + PAGE_LENGTH, total),
            total,
          ])
        }}
      </span>
      <div class="flex gap-2">
        <Button
          :label="__('Previous')"
          :disabled="start === 0 || duplicates.loading"
          @click="goTo(start - PAGE_LENGTH)"
        />
        <Button
          :label="__('Next')"
          :disabled="start + PAGE_LENGTH >= total || duplicates.loading"
          @click="goTo(start + PAGE_LENGTH)"
        />
      </div>
    </div>

    <ConfirmDialog
      v-model="confirmOpen"
      :title="__('Merge duplicate contacts')"
      :message="confirmMessage"
      :confirmLabel="__('Merge')"
      :onConfirm="merge"
    />
  </div>
</template>

<script setup>
import { PhUsersThree as LucideUsersThree } from '@phosphor-icons/vue'
import { Button, call, createResource, dayjs, toast } from 'frappe-ui'
import ConfirmDialog from '@/components/ui/ConfirmDialog.vue'
import ErrorState from '@/components/ui/ErrorState.vue'
import SkeletonTable from '@/components/ui/SkeletonTable.vue'
import { showSettings } from '@/composables/settings'
import { usersStore } from '@/stores/users'
import { computed, ref } from 'vue'

const PAGE_LENGTH = 20

const COLUMNS = [
  { key: 'name', label: __('Contact') },
  { key: 'company', label: __('Customer') },
  { key: 'customer_owner', label: __('Account owner') },
  { key: 'owner', label: __('Created by') },
  { key: 'deals', label: __('Deals'), align: 'right' },
  { key: 'creation', label: __('Created'), align: 'right' },
]

const { getUser } = usersStore()

const start = ref(0)

const duplicates = createResource({
  url: 'crm.api.contact.get_duplicate_contacts',
  makeParams: () => ({ start: start.value, page_length: PAGE_LENGTH }),
  auto: true,
})

const groups = computed(() => duplicates.data?.groups || [])
const total = computed(() => duplicates.data?.total || 0)

function goTo(next) {
  start.value = Math.max(next, 0)
  duplicates.reload()
}

// the contact opens behind the settings modal otherwise
function closeSettings() {
  showSettings.value = false
}

function userName(email) {
  if (!email) return '—'
  return getUser(email)?.full_name || email
}

function formatCreated(value) {
  return value ? dayjs(value).format('D MMM YYYY') : ''
}

const confirmOpen = ref(false)
const pending = ref(null)

const confirmMessage = computed(() => {
  if (!pending.value) return ''
  const { keep, others } = pending.value
  return __(
    'Merge {0} into {1}? Their deals, events, calls and emails move to {1}, and {0} will be deleted. Anyone who could see any of these contacts, through a deal, a share or the customer, will see {1} with all of it. This cannot be undone.',
    [
      others.map((c) => c.full_name || c.name).join(', '),
      keep.full_name || keep.name,
    ],
  )
})

function askMerge(group, keep) {
  pending.value = {
    keep,
    others: group.contacts.filter((c) => c.name !== keep.name),
  }
  confirmOpen.value = true
}

// the server merges at most this many at once; a larger group goes in turns
const MERGE_CHUNK = 20
const merging = ref(false)

async function merge({ hideDialog }) {
  const { keep, others } = pending.value || {}
  if (!keep || !others?.length) return hideDialog()
  if (merging.value) return
  merging.value = true
  try {
    const names = others.map((c) => c.name)
    for (let i = 0; i < names.length; i += MERGE_CHUNK) {
      await call('crm.api.contact.merge_duplicate_contacts', {
        target: keep.name,
        sources: names.slice(i, i + MERGE_CHUNK),
      })
    }
    toast.success(__('Contacts merged'))
    hideDialog()
    pending.value = null
    // the merged group is gone: a page that empties steps back one
    if (groups.value.length === 1 && start.value > 0) {
      start.value = Math.max(start.value - PAGE_LENGTH, 0)
    }
  } catch (error) {
    toast.error(error.messages?.[0] || __('Could not merge these contacts'))
  } finally {
    merging.value = false
    // a refusal part-way leaves some merged: show what is there now
    duplicates.reload()
  }
}
</script>
