<!--
  What is waiting to be sent, and what the server would not take.

  A refused entry is never dropped quietly: it stays here with the server's
  reason until the rep sends it again or throws it away, because it is their
  account of a visit and the only copy.
-->
<template>
  <div class="flex flex-col gap-4">
    <router-link
      :to="{ name: 'Field' }"
      class="-ml-1 flex min-h-9 w-fit items-center gap-1 rounded-5 pr-2 text-sm text-ink-gray-6 hover:text-ink-gray-8 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2"
    >
      <LucideChevronLeft class="size-4" aria-hidden="true" />
      {{ __('My week') }}
    </router-link>

    <p class="text-p-base text-ink-gray-6">
      {{
        connectivity.online
          ? __('Entries are sent as soon as they are saved.')
          : __(
              'No connection. Everything here is saved on this device and is sent when there is one.',
            )
      }}
    </p>

    <ul v-if="rows.length" class="flex flex-col gap-2">
      <li
        v-for="row in rows"
        :key="row.id"
        class="v-glass rounded-5 px-3.5 py-3"
      >
        <div class="flex items-start justify-between gap-3">
          <span class="min-w-0 text-base font-medium text-ink-gray-9">
            {{ row.title }}
          </span>
          <span class="shrink-0 text-sm tabular-nums text-ink-gray-5">
            {{ row.when }}
          </span>
        </div>
        <p
          v-if="row.detail"
          class="mt-1 line-clamp-3 whitespace-pre-line text-p-sm text-ink-gray-7"
        >
          {{ row.detail }}
        </p>

        <div
          v-if="row.status === 'rejected'"
          class="mt-2.5 rounded-5 bg-surface-red-1 px-3 py-2 text-p-sm text-ink-red-9"
          role="alert"
        >
          {{ row.error || __('The server did not accept this.') }}
        </div>
        <div
          v-else
          class="mt-2 flex items-center gap-1.5 text-sm text-ink-gray-6"
        >
          <component :is="row.icon" class="size-3.5" aria-hidden="true" />
          {{ row.state }}
        </div>

        <!-- Not while it is on the wire: the server may already have it,
             and "discarded" would then be untrue. -->
        <div
          v-if="row.status !== 'sent' && !row.sending"
          class="mt-2.5 flex flex-wrap items-center gap-2"
        >
          <Button
            v-if="row.status === 'rejected'"
            :label="__('Send again')"
            :disabled="!connectivity.online"
            @click="retryEntry(row.id)"
          />
          <template v-if="discarding === row.id">
            <Button
              theme="red"
              variant="solid"
              :label="__('Discard for good')"
              @click="discard(row.id)"
            />
            <Button
              variant="ghost"
              :label="__('Keep')"
              @click="discarding = null"
            />
          </template>
          <Button
            v-else
            variant="ghost"
            :label="__('Discard')"
            @click="discarding = row.id"
          />
        </div>
      </li>
    </ul>

    <div
      v-else
      class="flex flex-col items-center gap-1 rounded-5 border border-dashed px-4 py-10 text-center"
    >
      <LucideCloudCheck
        class="mb-1 size-6 text-ink-gray-5"
        aria-hidden="true"
      />
      <span class="text-base font-medium text-ink-gray-8">
        {{ __('Nothing waiting') }}
      </span>
      <span class="text-p-base text-ink-gray-6">
        {{ __('Everything you logged has reached the server.') }}
      </span>
    </div>
  </div>
</template>

<script setup>
import { connectivity } from '@/offline/connectivity'
import { discardEntry, outbox, retryEntry } from '@/offline/outbox'
import { useField } from '@/offline/useField'
import { describeEntry } from '@/utils/fieldOutbox'
import { savedWhen } from '@/utils/fieldPack'
import { activityLabel } from '@/utils/planner'
import { computed, ref } from 'vue'
import LucideChevronLeft from '~icons/lucide/chevron-left'
import LucideCloudCheck from '~icons/lucide/cloud-check'
import LucideCloudUpload from '~icons/lucide/cloud-upload'
import LucideRefreshCw from '~icons/lucide/refresh-cw'

const { pack, index } = useField()
const discarding = ref(null)

const names = {
  customerName: (name) =>
    index.value.byName.get(name)?.organization_name || name,
  taskTitle: (name) =>
    (pack.value?.tasks ?? []).find((task) => String(task.name) === String(name))
      ?.title || '',
  activityLabel: (type) => __(activityLabel(type)),
}

function whenLabel(ms) {
  const when = savedWhen(ms)
  if (!when) return ''
  return when.day === 'today' ? when.time : `${when.date} ${when.time}`
}

// refused first: they are the ones that need a person
const rows = computed(() =>
  [...outbox.entries]
    .sort(
      (a, b) =>
        (b.status === 'rejected') - (a.status === 'rejected') ||
        b.captured_at - a.captured_at,
    )
    .map((entry) => ({
      id: entry.id,
      status: entry.status,
      sending: !!entry.sending,
      error: entry.error,
      when: whenLabel(entry.captured_at),
      ...describeEntry(entry, names),
      state:
        entry.status === 'sent'
          ? __('Sent, updating')
          : entry.sending
            ? __('Sending')
            : __('Waiting to send'),
      icon: entry.status === 'sent' ? LucideRefreshCw : LucideCloudUpload,
    })),
)

async function discard(id) {
  await discardEntry(id)
  discarding.value = null
}
</script>
