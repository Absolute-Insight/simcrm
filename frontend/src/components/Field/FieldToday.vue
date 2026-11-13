<!-- The rep's week, a day at a time, from the plans saved on this device. -->
<template>
  <div class="flex flex-col gap-4">
    <div class="flex items-center justify-between gap-2">
      <Button
        variant="ghost"
        icon="lucide-chevron-left"
        :aria-label="__('Previous week')"
        :disabled="!canGoBack"
        @click="shiftWeek(-1)"
      />
      <div class="text-base font-medium tabular-nums text-ink-gray-8">
        {{ weekLabel }}
      </div>
      <Button
        variant="ghost"
        icon="lucide-chevron-right"
        :aria-label="__('Next week')"
        :disabled="!canGoForward"
        @click="shiftWeek(1)"
      />
    </div>

    <!-- Seven buttons, one per day. The count is the reason to tap a day, so it
         is on the button rather than discovered after tapping. -->
    <div class="grid grid-cols-7 gap-1" role="tablist" :aria-label="weekLabel">
      <button
        v-for="day in cells"
        :key="day.date"
        type="button"
        role="tab"
        :aria-selected="day.date === selected"
        :aria-label="dayAria(day)"
        class="relative flex min-h-14 flex-col items-center justify-center gap-0.5 rounded-5 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2"
        :class="
          day.date === selected
            ? 'v-glass text-ink-gray-9'
            : 'text-ink-gray-5 hover:text-ink-gray-7'
        "
        @click="selected = day.date"
      >
        <span class="v-kpi-label">{{ weekdayName(day.date) }}</span>
        <span
          class="font-display text-lg font-semibold leading-none tabular-nums tracking-tight"
          :class="day.isToday && 'text-brand'"
        >
          {{ Number(day.date.slice(8, 10)) }}
        </span>
        <span
          class="h-1 text-[0.625rem] leading-none tabular-nums text-ink-gray-5"
        >
          {{ day.count || '' }}
        </span>
        <span
          v-if="day.isToday"
          class="absolute inset-x-2 bottom-0 h-0.5 rounded-full"
          :style="{ background: 'var(--brand-gradient)' }"
          aria-hidden="true"
        />
      </button>
    </div>

    <div class="flex flex-col gap-2" role="tabpanel">
      <div class="flex items-baseline justify-between">
        <h2 class="text-base font-medium text-ink-gray-8">
          {{ selectedLabel }}
        </h2>
        <span v-if="items.length" class="text-sm tabular-nums text-ink-gray-5">
          {{ summary }}
        </span>
      </div>

      <FieldPlanItem v-for="item in items" :key="item.name" :item="item" />

      <div
        v-if="!items.length"
        class="flex flex-col items-center gap-1 rounded-5 border border-dashed px-4 py-10 text-center"
      >
        <LucideCalendarDays
          class="mb-1 size-6 text-ink-gray-5"
          aria-hidden="true"
        />
        <span class="text-base font-medium text-ink-gray-8">
          {{ weekSaved ? __('Nothing planned') : __('This week is not saved') }}
        </span>
        <span class="text-p-base text-ink-gray-6">
          {{
            weekSaved
              ? __('No activities are planned for this day.')
              : __(
                  'This device holds last week, this week and next. Connect to load another.',
                )
          }}
        </span>
      </div>
    </div>
  </div>
</template>

<script setup>
import FieldPlanItem from '@/components/Field/FieldPlanItem.vue'
import { useField } from '@/offline/useField'
import { shortDate, weekdayName } from '@/utils/fieldPack'
import { addDays, mondayOf, weekDayCells } from '@/utils/planner'
import { computed, ref, watch } from 'vue'
import LucideCalendarDays from '~icons/lucide/calendar-days'

const { days, weeks, today } = useField()

const selected = ref(today.value)
const weekStart = computed(() => mondayOf(selected.value))

/* The phone carries three weeks. The arrows stop at their edges rather than
   walking into weeks it has nothing for -- except the week holding today,
   which is always reachable: after a fortnight with no signal the saved weeks
   are all in the past, and "today" must still be somewhere. */
const reachable = computed(() =>
  [...new Set([...weeks.value, mondayOf(today.value)])].sort(),
)
const position = computed(() => reachable.value.indexOf(weekStart.value))
const canGoBack = computed(() => position.value > 0)
const canGoForward = computed(
  () => position.value > -1 && position.value < reachable.value.length - 1,
)
const weekSaved = computed(() => weeks.value.includes(weekStart.value))

function shiftWeek(step) {
  const next = reachable.value[position.value + step]
  if (!next) return
  // land on today when the week has it, otherwise on its Monday
  selected.value = next === mondayOf(today.value) ? today.value : next
}

// the pack arrived or changed under an open screen: stay inside what it holds
watch(reachable, (list) => {
  if (!list.includes(weekStart.value)) selected.value = today.value
})

const cells = computed(() =>
  weekDayCells(weekStart.value, today.value).map((day) => ({
    ...day,
    count: days.value.get(day.date)?.length ?? 0,
  })),
)

const items = computed(() => days.value.get(selected.value) ?? [])

const weekLabel = computed(
  () =>
    `${shortDate(weekStart.value)} – ${shortDate(addDays(weekStart.value, 6))}`,
)

const selectedLabel = computed(() => {
  const label = `${weekdayName(selected.value)} ${shortDate(selected.value)}`
  return selected.value === today.value ? __('Today, {0}', [label]) : label
})

const summary = computed(() => {
  const done = items.value.filter((item) => item.status === 'Done').length
  return __('{0} of {1} done', [done, items.value.length])
})

function dayAria(day) {
  const label = `${weekdayName(day.date)} ${shortDate(day.date)}`
  return day.count ? __('{0}, {1} planned', [label, day.count]) : label
}
</script>
