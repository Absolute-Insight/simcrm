<template>
  <div class="flex min-h-0 flex-1 flex-col">
    <div
      class="flex flex-wrap items-center gap-x-4 gap-y-2 border-b px-5 py-2 text-sm text-ink-gray-6"
    >
      <Select
        :modelValue="type"
        :options="typeOptions"
        :aria-label="__('Show activity type')"
        class="w-48"
        @update:modelValue="(value) => (type = value)"
      />
      <span v-if="shown" class="tabular-nums">
        {{
          __('{0} planned · {1} done · {2} missed · {3} cancelled', [
            teamTotals.planned,
            teamTotals.done,
            teamTotals.missed,
            teamTotals.cancelled,
          ])
        }}
      </span>
    </div>

    <ErrorState
      v-if="team.error"
      class="flex-1"
      :error="team.error"
      :retry="() => team.reload()"
    />

    <SkeletonTable
      v-else-if="!shown"
      :columns="8"
      :rows="6"
      density="compact"
      class="flex-1 px-5 py-3"
      :label="__('Loading the team week')"
    />

    <EmptyState
      v-else-if="!rows.length"
      class="flex-1"
      icon="lucide-users"
      :title="__('No reps to show')"
      :description="__('Reps you manage appear here with their week.')"
    />

    <!-- One row per rep, one column per day. The rep column is sticky so a
         phone can scroll the week sideways and still see whose row it is. -->
    <div v-else class="v-lux-stage min-h-0 flex-1 overflow-auto">
      <table class="min-w-full border-separate border-spacing-0 text-sm">
        <thead>
          <tr>
            <th
              class="v-kpi-label sticky left-0 top-0 z-20 min-w-40 border-b border-r border-outline-gray-1 bg-surface-elevation-2 px-3 py-2 text-left text-ink-gray-5"
            >
              {{ __('Rep') }}
            </th>
            <th
              v-for="day in days"
              :key="day.date"
              class="sticky top-0 z-10 min-w-36 border-b border-r border-outline-gray-1 bg-surface-elevation-2 px-2 py-2 text-left last:border-r-0"
              :class="day.isToday ? 'text-ink-gray-9' : 'text-ink-gray-5'"
            >
              <span class="v-kpi-label">{{ dayLabel(day.date) }}</span>
            </th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="rep in rows" :key="rep.user" class="align-top">
            <td
              class="sticky left-0 z-10 border-b border-r border-outline-gray-1 bg-surface-elevation-2 px-3 py-2"
            >
              <button
                class="block max-w-44 truncate text-left font-medium text-ink-gray-8 underline-offset-2 hover:underline focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2"
                :title="__('Open {0}\'s week', [rep.full_name])"
                @click="emit('open-rep', rep.user)"
              >
                {{ rep.full_name }}
              </button>
              <div class="mt-0.5 text-xs tabular-nums text-ink-gray-5">
                {{
                  __('{0} of {1} done', [rep.totals.done, rep.totals.planned])
                }}
              </div>
            </td>
            <td
              v-for="day in days"
              :key="day.date"
              class="border-b border-r border-outline-gray-1 p-1 last:border-r-0"
              :class="day.isWeekend ? 'bg-surface-gray-1' : ''"
            >
              <div class="flex flex-col gap-1">
                <div
                  v-for="item in rep.byDay[day.date]"
                  :key="item.name"
                  class="v-glass flex items-start gap-1.5 rounded-4 px-1.5 py-1"
                  :title="itemTitle(item)"
                >
                  <component
                    :is="typeIcon(item.activity_type)"
                    class="mt-0.5 size-3.5 shrink-0"
                    :class="statusColor(item.status)"
                    aria-hidden="true"
                  />
                  <div class="min-w-0">
                    <div class="truncate text-xs text-ink-gray-8">
                      {{
                        item.organization ||
                        item.note ||
                        activityLabel(item.activity_type)
                      }}
                    </div>
                    <div
                      class="truncate text-xs"
                      :class="statusColor(item.status)"
                    >
                      {{ __(activityLabel(item.activity_type)) }} ·
                      {{ statusLabel(item.status) }}
                    </div>
                  </div>
                </div>
              </div>
            </td>
          </tr>
        </tbody>
      </table>
    </div>
  </div>
</template>

<script setup>
import EmptyState from '@/components/ListViews/EmptyState.vue'
import ErrorState from '@/components/ui/ErrorState.vue'
import SkeletonTable from '@/components/ui/SkeletonTable.vue'
import {
  ACTIVITY_TYPES,
  activityLabel,
  rollupItems,
  rollupTotals,
  teamGrid,
  todayInTimeZone,
  weekDayCells,
} from '@/utils/planner'
import { statusColor, statusLabel, typeIcon } from '@/utils/plannerDisplay'
import { quiet } from '@/utils/quiet'
import { Select, createResource, dayjs, getConfig } from 'frappe-ui'
import { computed, ref, watch } from 'vue'

const props = defineProps({
  weekStart: { type: String, required: true },
  today: { type: String, required: true },
})
const emit = defineEmits(['open-rep'])

const type = ref('')

const typeOptions = computed(() => [
  { label: __('All activity types'), value: '' },
  ...ACTIVITY_TYPES.map((t) => ({ label: __(t.label), value: t.value })),
])

/* Re-read on every load, like the rep's week does: a manager who leaves the
   team week open past midnight should not see yesterday marked as today. */
const today = ref(props.today)

/* frappe-ui keeps whichever response lands last, not the last one asked for:
   two quick week changes answered out of order put the previous week's totals
   under the new week's header, over an empty grid. Only an answer for the
   week on screen is kept, and only shown while that week is. */
const answered = ref(null)
const shown = computed(() =>
  answered.value?.week_start === props.weekStart ? answered.value : null,
)

const team = createResource({
  url: 'crm.api.rep_plan.get_team_week',
  makeParams: () => ({ week_start: props.weekStart }),
  auto: true,
  onSuccess(data) {
    if (data?.week_start !== props.weekStart) return
    answered.value = data
    today.value = todayInTimeZone(getConfig('systemTimezone'))
  },
})

watch(
  () => props.weekStart,
  () => quiet(team.reload()),
)

const days = computed(() => weekDayCells(props.weekStart, today.value))

const rows = computed(() =>
  teamGrid(
    shown.value?.reps || [],
    days.value.map((d) => d.date),
    type.value,
  ),
)

const teamTotals = computed(() =>
  rollupTotals(
    rollupItems(
      (shown.value?.reps || [])
        .flatMap((rep) => rep.items || [])
        .filter((item) => !type.value || item.activity_type === type.value),
    ),
  ),
)

function dayLabel(date) {
  return dayjs(date).format('ddd D')
}

function itemTitle(item) {
  return [
    activityLabel(item.activity_type),
    item.organization,
    item.note,
    item.outcome,
    statusLabel(item.status),
  ]
    .filter(Boolean)
    .join(' · ')
}
</script>
