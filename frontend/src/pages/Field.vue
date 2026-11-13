<!--
  Field mode — the week, the customers and the tasks, from the copy on this
  device, so they open at a site with no reception.

  It carries its own chrome on purpose. The app shell's sidebar, notification
  bell and settings each start with a request to the server, and this is the
  one surface that must paint without one. Online it is the same screen reading
  the same copy, kept fresh in the background -- so what a rep sees at the mine
  is what they saw in the office, not a fallback nobody had looked at.
-->
<template>
  <!-- h-dvh, not h-full: the tab bar has to sit at the bottom of what is
       actually visible, and on a phone that is the viewport minus whatever
       browser chrome is showing right now. -->
  <div class="v-lux-stage flex h-dvh flex-col bg-surface-base">
    <header class="shrink-0 border-b">
      <div
        class="mx-auto flex w-full max-w-2xl items-center justify-between gap-3 px-4 py-3"
      >
        <div class="min-w-0">
          <div class="v-kpi-label">{{ __('Field mode') }}</div>
          <h1
            class="truncate font-display text-xl font-semibold leading-tight tracking-tight text-ink-gray-9"
          >
            {{ title }}
          </h1>
        </div>
        <div class="flex shrink-0 items-center gap-1.5">
          <button
            type="button"
            class="v-glass flex min-h-9 items-center gap-1.5 rounded-full px-3 text-sm tabular-nums focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 disabled:cursor-default"
            :class="status.tone"
            :disabled="!connectivity.online || state.syncing"
            :aria-label="status.hint"
            @click="syncPack()"
          >
            <component
              :is="status.icon"
              class="size-3.5 shrink-0"
              :class="state.syncing && 'animate-spin'"
              aria-hidden="true"
            />
            <span>{{ status.label }}</span>
          </button>
          <Button
            v-if="connectivity.online"
            variant="ghost"
            :icon="LucideLayoutGrid"
            :aria-label="__('Open the full app')"
            :tooltip="__('Open the full app')"
            @click="openFullApp"
          />
        </div>
      </div>
    </header>

    <!-- Said once, under the header, in words: the pill alone is a colour and
         an icon, and "is this current?" is the question a rep on site has. -->
    <div
      v-if="!connectivity.online && pack"
      class="shrink-0 border-b bg-surface-orange-1 text-ink-orange-9"
      role="status"
    >
      <div class="mx-auto w-full max-w-2xl px-4 py-2 text-sm">
        {{ offlineNotice }}
      </div>
    </div>

    <main class="min-h-0 flex-1 overflow-y-auto">
      <div class="mx-auto w-full max-w-2xl px-4 py-4">
        <router-view v-if="pack" />

        <div
          v-else-if="!state.loaded || state.syncing"
          class="flex flex-col gap-2"
        >
          <Skeleton
            v-for="n in 4"
            :key="n"
            shape="block"
            height="4.5rem"
            rounded="10px"
            :label="n === 1 ? __('Saving your week and customers') : ''"
          />
        </div>

        <!-- Online and still nothing: the sync itself failed. -->
        <ErrorState
          v-else-if="connectivity.online && state.error"
          :error="state.error"
          :retry="() => syncPack()"
        />

        <div
          v-else
          class="flex flex-col items-center gap-3 px-4 py-16 text-center"
        >
          <div
            class="grid size-11 place-items-center rounded-full bg-surface-orange-1"
          >
            <LucideWifiOff
              class="size-5 text-ink-orange-9"
              aria-hidden="true"
            />
          </div>
          <div class="flex max-w-sm flex-col gap-1">
            <span class="text-lg-medium text-ink-gray-8">
              {{ __('Nothing is saved on this device yet') }}
            </span>
            <span class="text-p-base text-ink-gray-6">
              {{
                __(
                  'Open Vectora once with a connection and your week and customers are saved here for the next time there is none.',
                )
              }}
            </span>
          </div>
          <Button
            variant="solid"
            :label="__('Try again')"
            :loading="state.syncing"
            @click="retry"
          />
        </div>
      </div>
    </main>

    <nav
      class="shrink-0 border-t bg-surface-base"
      :aria-label="__('Field mode')"
      style="padding-bottom: env(safe-area-inset-bottom)"
    >
      <div class="mx-auto grid w-full max-w-2xl grid-cols-3">
        <router-link
          v-for="tab in tabs"
          :key="tab.name"
          :to="{ name: tab.name }"
          class="flex min-h-14 flex-col items-center justify-center gap-0.5 text-xs focus-visible:outline focus-visible:outline-2 focus-visible:-outline-offset-2"
          :class="
            tab.active
              ? 'font-medium text-ink-gray-9'
              : 'text-ink-gray-5 hover:text-ink-gray-7'
          "
          :aria-current="tab.active ? 'page' : undefined"
        >
          <component
            :is="tab.icon"
            class="size-5"
            :class="tab.active && 'text-brand'"
            aria-hidden="true"
          />
          <span>{{ tab.label }}</span>
        </router-link>
      </div>
    </nav>
  </div>
</template>

<script setup>
import ErrorState from '@/components/ui/ErrorState.vue'
import Skeleton from '@/components/ui/Skeleton.vue'
import { connectivity, probe } from '@/offline/connectivity'
import { markFieldModeUsed, syncPack } from '@/offline/pack'
import { useField } from '@/offline/useField'
import { savedWhen } from '@/utils/fieldPack'
import { computed, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import LucideBuilding2 from '~icons/lucide/building-2'
import LucideCalendarDays from '~icons/lucide/calendar-days'
import LucideCloudAlert from '~icons/lucide/cloud-alert'
import LucideLayoutGrid from '~icons/lucide/layout-grid'
import LucideListChecks from '~icons/lucide/list-checks'
import LucideRefreshCw from '~icons/lucide/refresh-cw'
import LucideWifiOff from '~icons/lucide/wifi-off'

const route = useRoute()
const router = useRouter()
const { pack, state } = useField()

const SECTIONS = {
  Field: 'Field',
  FieldCustomers: 'FieldCustomers',
  FieldCustomer: 'FieldCustomers',
  FieldTasks: 'FieldTasks',
}

const tabs = computed(() =>
  [
    { name: 'Field', label: __('My week'), icon: LucideCalendarDays },
    { name: 'FieldCustomers', label: __('Customers'), icon: LucideBuilding2 },
    { name: 'FieldTasks', label: __('Tasks'), icon: LucideListChecks },
  ].map((tab) => ({ ...tab, active: SECTIONS[route.name] === tab.name })),
)

const title = computed(
  () => tabs.value.find((tab) => tab.active)?.label ?? __('Field mode'),
)

function whenText(when) {
  if (!when) return ''
  if (when.day === 'today') return __('today at {0}', [when.time])
  if (when.day === 'yesterday') return __('yesterday at {0}', [when.time])
  return __('on {0} at {1}', [when.date, when.time])
}

const saved = computed(() => savedWhen(state.syncedAt))

const offlineNotice = computed(() =>
  saved.value
    ? __('No connection. This is what was saved {0}.', [whenText(saved.value)])
    : __('No connection. Showing what is saved on this device.'),
)

const status = computed(() => {
  if (!connectivity.online) {
    return {
      label: __('Offline'),
      hint: __('No connection'),
      icon: LucideWifiOff,
      tone: 'text-ink-orange-9',
    }
  }
  if (state.syncing) {
    return {
      label: __('Syncing'),
      hint: __('Syncing'),
      icon: LucideRefreshCw,
      tone: 'text-ink-gray-7',
    }
  }
  if (state.error) {
    return {
      label: __('Sync failed'),
      hint: __('Sync failed. Try again'),
      icon: LucideCloudAlert,
      tone: 'text-ink-red-9',
    }
  }
  return {
    label: saved.value ? saved.value.time : __('Sync'),
    hint: saved.value
      ? __('Saved {0}. Sync now', [whenText(saved.value)])
      : __('Sync now'),
    icon: LucideRefreshCw,
    tone: 'text-ink-gray-7',
  }
})

/* Back to where offline interrupted them, when it did; otherwise home. */
function openFullApp() {
  const intended = connectivity.intended
  connectivity.intended = null
  router.push(intended || { name: 'Home' })
}

async function retry() {
  if (await probe()) syncPack()
}

onMounted(() => {
  markFieldModeUsed()
  // opening field mode is asking for a current copy
  if (connectivity.online) syncPack()
})
</script>
