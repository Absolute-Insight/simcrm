<template>
  <div class="flex h-full flex-col gap-4 p-8">
    <div class="flex flex-col gap-1">
      <h2 class="v-title text-ink-gray-8">
        {{ __('Visit Targets') }}
      </h2>
      <p class="text-p-sm text-ink-gray-5">
        {{
          __(
            'Planned customer visits each rep should complete in a working week. Calls, emails and unplanned meetings are not counted. A month or a fortnight is measured against the same number, pro-rated by its working days.',
          )
        }}
      </p>
    </div>

    <div
      v-if="canChangeLock"
      class="flex items-center justify-between gap-6 rounded-5 border border-outline-gray-1 px-3 py-2.5"
    >
      <div class="flex flex-col">
        <div class="text-p-base-medium text-ink-gray-7">
          {{ __('Plan only for today or later') }}
        </div>
        <div class="text-p-sm text-ink-gray-5">
          {{
            __(
              'Reps cannot plan, move or remove an activity on a day that has passed, and log unplanned work on the day itself. Outcomes can still be logged afterwards.',
            )
          }}
        </div>
      </div>
      <CheckSwitch
        :modelValue="!!settings.doc?.lock_past_plans"
        size="sm"
        :disabled="settings.setValue.loading"
        @update:modelValue="setLock"
      />
    </div>

    <SkeletonTable
      v-if="targets.loading && !targets.data"
      :columns="2"
      :rows="6"
      density="compact"
      class="flex-1 px-1"
      :label="__('Loading visit targets')"
    />

    <ErrorState
      v-else-if="targets.error"
      class="flex-1"
      :error="targets.error"
      :title="__('Could not load the visit targets')"
      :retry="targets.reload"
    />

    <div
      v-else-if="!rows.length"
      class="flex flex-1 flex-col items-center justify-center gap-1 text-center"
    >
      <LucideMapPin class="size-7 text-ink-gray-4" />
      <div class="text-base text-ink-gray-6">
        {{ __('No sales users yet') }}
      </div>
      <div class="text-sm text-ink-gray-5">
        {{ __('Invite a rep, then set their weekly visit target here.') }}
      </div>
    </div>

    <div v-else class="min-h-0 flex-1 overflow-auto">
      <table class="min-w-full border-separate border-spacing-0 text-base">
        <thead>
          <tr>
            <th
              class="sticky top-0 z-10 border-b border-outline-gray-1 bg-surface-elevation-2 px-3 py-2 text-left text-xs font-medium uppercase tracking-wider text-ink-gray-5"
            >
              {{ __('Rep') }}
            </th>
            <th
              class="sticky top-0 z-10 w-40 border-b border-outline-gray-1 bg-surface-elevation-2 px-3 py-2 text-right text-xs font-medium uppercase tracking-wider text-ink-gray-5"
            >
              {{ __('Visits per week') }}
            </th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="row in rows" :key="row.user">
            <td
              class="whitespace-nowrap border-b border-outline-gray-1 px-3 py-1.5"
            >
              <span class="truncate text-ink-gray-8">{{ row.full_name }}</span>
            </td>
            <td class="w-40 border-b border-outline-gray-1 px-1 py-1">
              <input
                v-if="row.editable"
                :value="displayValue(row)"
                class="w-full rounded-[var(--v-radius-control)] border border-transparent bg-transparent px-1.5 py-1 text-right text-sm tabular-nums text-ink-gray-8 transition placeholder:text-ink-gray-4 hover:border-outline-gray-2 focus:border-outline-gray-3 focus:bg-surface-white focus:outline-none focus:ring-2 focus:ring-outline-gray-3"
                inputmode="numeric"
                placeholder="—"
                :aria-label="__('{0} visits per week', [row.full_name])"
                @focus="$event.target.select()"
                @blur="onBlur($event, row)"
                @keydown.enter="$event.target.blur()"
              />
              <div
                v-else
                class="px-1.5 py-1 text-right text-sm tabular-nums text-ink-gray-7"
                :title="
                  row.user === currentUser
                    ? __('Your own target is set by your manager.')
                    : ''
                "
              >
                {{ displayValue(row) || '—' }}
              </div>
            </td>
          </tr>
        </tbody>
      </table>
    </div>

    <p class="shrink-0 text-p-xs text-ink-gray-5">
      {{
        __(
          'Clear a cell, or enter 0, to remove a target. Reps with no target show as "No target" on the dashboard rather than as behind.',
        )
      }}
    </p>
  </div>
</template>

<script setup>
import { PhMapPin as LucideMapPin } from '@phosphor-icons/vue'
import { call, createResource, toast } from 'frappe-ui'
import CheckSwitch from '@/components/ui/CheckSwitch.vue'
import ErrorState from '@/components/ui/ErrorState.vue'
import SkeletonTable from '@/components/ui/SkeletonTable.vue'
import { sessionStore } from '@/stores/session'
import { getSettings } from '@/stores/settings'
import { usersStore } from '@/stores/users'
import { computed } from 'vue'

const { user: currentUser } = sessionStore()
const { _settings: settings } = getSettings()
const { isManager, isAdmin } = usersStore()

// FCRM Settings is writable by Sales Managers and System Managers
const canChangeLock = computed(() => isManager() || isAdmin())

async function setLock(value) {
  try {
    await settings.setValue.submit({ lock_past_plans: value ? 1 : 0 })
    toast.success(
      value
        ? __('Reps now plan for today or later')
        : __('Reps can plan on past days again'),
    )
  } catch (error) {
    toast.error(error.messages?.[0] || __('Could not change the setting'))
  }
}

const targets = createResource({
  url: 'crm.api.visit_targets.get_visit_targets',
  auto: true,
})

const rows = computed(() => targets.data || [])

function displayValue(row) {
  return row.visits_per_week ? String(row.visits_per_week) : ''
}

async function onBlur(event, row) {
  const raw = event.target.value.trim()
  const value = raw === '' ? 0 : Number(raw)
  const previous = row.visits_per_week || 0

  if (!Number.isInteger(value) || value < 0) {
    event.target.value = displayValue(row)
    toast.error(__('Enter a whole number of visits, 0 or more.'))
    return
  }
  if (value === previous) {
    event.target.value = displayValue(row)
    return
  }

  // paint first, then reconcile with what the server stored
  row.visits_per_week = value || null
  try {
    const saved = await call('crm.api.visit_targets.set_visit_target', {
      user: row.user,
      visits_per_week: value,
    })
    row.visits_per_week = saved?.visits_per_week || null
  } catch (error) {
    row.visits_per_week = previous || null
    toast.error(error.messages?.[0] || __('Could not save that target'))
  }
  event.target.value = displayValue(row)
}
</script>
