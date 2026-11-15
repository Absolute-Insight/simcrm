<template>
  <Dropdown :options="options" align="end" @update:open="onMenuToggle">
    <Button
      variant="solid"
      class="rounded-l-none border-l border-outline-gray-5"
      :tooltip="__('Schedule send')"
      :aria-label="__('Schedule send')"
      :disabled="disabled"
      icon="lucide-chevron-down"
      @pointerdown="openedAt = dayjs()"
    />
  </Dropdown>
  <Dialog
    v-model:open="showPicker"
    :title="__('Schedule send')"
    size="sm"
    :actions="[
      {
        label: __('Schedule send'),
        variant: 'solid',
        disabled: !pickedOk,
        onClick: schedulePicked,
      },
    ]"
  >
    <DateTimePicker
      v-model="pickedTime"
      :placeholder="__('Pick date & time')"
      :isDateUnavailable="
        (date) =>
          date.isBefore(dayjs(), 'day') ||
          date.isAfter(dayjs().add(MAX_DAYS_AHEAD, 'day'), 'day')
      "
    />
    <ErrorMessage
      class="mt-2"
      :message="
        !pickedTime || pickedOk
          ? ''
          : pickedInFuture
            ? __('Pick a time within the next {0} days', [MAX_DAYS_AHEAD])
            : __('Pick a time in the future')
      "
    />
  </Dialog>
</template>

<script setup lang="ts">
import {
  Dialog,
  DateTimePicker,
  Dropdown,
  ErrorMessage,
  dayjs,
  getConfig,
} from 'frappe-ui'
import type { Dayjs } from 'frappe-ui'
import { computed, h, ref, watch } from 'vue'

defineProps<{ disabled?: boolean }>()

// `confirmed` is set when the user already confirmed the time in the picker dialog
const emit = defineEmits<{
  schedule: [sendAfter: string, label: string, confirmed: boolean]
}>()

const localTimezone: string =
  getConfig('localTimezone') || Intl.DateTimeFormat().resolvedOptions().timeZone
const systemTimezone: string | null = getConfig('systemTimezone')

const openedAt = ref(dayjs())
const showPicker = ref(false)
const pickedTime = ref('')

watch(showPicker, (open) => {
  if (open) pickedTime.value = ''
})

// The picker shows the user's own clock, so read its value in their timezone
const pickedAt = computed(() =>
  pickedTime.value ? dayjs.tz(pickedTime.value, localTimezone) : null,
)
// dayjs() is not reactive, so a computed that compares against it keeps the
// answer it had when the time was picked. Bumping this makes them ask again.
const clockRead = ref(0)
const pickedInFuture = computed(() => {
  void clockRead.value
  return !!pickedAt.value?.isAfter(dayjs())
})

// Ours, not upstream's. frappe clears email queue rows 30 days after they were
// made, whatever their status, so an email scheduled further out than that
// stays "Scheduled" on the timeline for good and is never sent.
const MAX_DAYS_AHEAD = 28
const pickedOk = computed(() => {
  void clockRead.value
  return (
    pickedInFuture.value &&
    !pickedAt.value?.isAfter(dayjs().add(MAX_DAYS_AHEAD, 'day'))
  )
})

function at(day: Dayjs, hour: number) {
  return day.hour(hour).minute(0).second(0)
}

const slots = [
  { label: __('Morning'), hour: 9, icon: 'lucide-sunrise' },
  { label: __('Afternoon'), hour: 13, icon: 'lucide-sun' },
  { label: __('Evening'), hour: 18, icon: 'lucide-sunset' },
]

function slotOptions(day: Dayjs, after: Dayjs) {
  return slots
    .map((slot) => ({ ...slot, time: at(day, slot.hour) }))
    .filter(({ time }) => time.isAfter(after))
    .map(({ label, icon, time }) => ({
      label,
      icon,
      slots: {
        suffix: () =>
          h('span', { class: 'text-ink-gray-5' }, time.format('h:mm A')),
      },
      onClick: () => schedule(time),
    }))
}

// The composer stays mounted from page load, so the menu is dated from when it
// opens. The open event covers the keyboard (Enter, Space, ArrowDown), which
// the trigger's pointerdown does not.
function onMenuToggle(open: boolean) {
  if (open) openedAt.value = dayjs()
}

// Rebuilt each time the menu opens, so "today" and "tomorrow" never go stale
const options = computed(() => {
  const now = openedAt.value.tz(localTimezone)
  const today = slotOptions(now, now)
  const tomorrow = slotOptions(now.add(1, 'day'), now)
  return [
    ...(today.length ? [{ group: __('Today'), options: today }] : []),
    { group: __('Tomorrow'), options: tomorrow },
    {
      group: '',
      hideLabel: true,
      options: [
        {
          label: __('Custom date & time…'),
          onClick: () => (showPicker.value = true),
        },
      ],
    },
  ]
})

function schedule(time: Dayjs, confirmed = false) {
  const system = systemTimezone ? time.tz(systemTimezone) : time
  emit(
    'schedule',
    system.format('YYYY-MM-DD HH:mm:ss'),
    time.format('ddd, D MMM, h:mm A'),
    confirmed,
  )
}

function schedulePicked() {
  // Re-checked against the clock as it is now: the time can pass while the
  // dialog sits open. A refusal also shows why, and disables the button.
  clockRead.value++
  if (!pickedOk.value) return
  showPicker.value = false
  schedule(pickedAt.value as Dayjs, true)
}
</script>
