<template>
  <LayoutHeader>
    <template #left-header>
      <div class="flex items-center gap-1">
        <div
          class="font-display text-lg font-medium tracking-tight text-ink-gray-7 px-0.5 py-1"
        >
          {{ __('Planner') }}
        </div>
      </div>
    </template>
    <template #right-header>
      <Button
        v-if="isOwnPlan"
        :label="__('Propose my week')"
        @click="proposeWeek"
      >
        <template #prefix>
          <LucideSparkles class="size-4" />
        </template>
      </Button>
      <Button
        v-if="isOwnPlan"
        variant="solid"
        :label="__('Save plan')"
        :disabled="!dirty"
        :loading="saving"
        @click="savePlan"
      />
    </template>
  </LayoutHeader>

  <div class="flex items-center justify-between border-b px-5 py-2">
    <div class="flex items-center gap-2">
      <Button variant="ghost" icon="chevron-left" @click="shiftWeek(-7)" />
      <div class="text-base font-medium text-ink-gray-8 tabular-nums">
        {{ weekLabel }}
      </div>
      <Button variant="ghost" icon="chevron-right" @click="shiftWeek(7)" />
      <Button
        v-if="!isCurrentWeek"
        variant="ghost"
        :label="__('This week')"
        @click="goToCurrentWeek"
      />
    </div>
    <div class="flex items-center gap-3">
      <div
        v-if="plan.data"
        class="flex items-center gap-2 text-sm text-ink-gray-6"
      >
        <span>{{ totals.planned }} {{ __('planned') }}</span>
        <span class="text-ink-green-3">{{ totals.done }} {{ __('done') }}</span>
        <span v-if="totals.missed" class="text-ink-red-4">
          {{ totals.missed }} {{ __('missed') }}
        </span>
      </div>
      <Select
        v-if="isManager()"
        v-model="planUser"
        :options="userOptions"
        class="w-48"
      />
    </div>
  </div>

  <div class="flex flex-1 overflow-x-auto">
    <div
      v-for="day in weekDays"
      :key="day.date"
      class="flex min-w-44 flex-1 flex-col border-r last:border-r-0"
      :class="day.isWeekend ? 'bg-surface-gray-1' : ''"
    >
      <div
        class="flex items-baseline justify-between border-b px-3 py-2"
        :class="day.isToday ? 'text-ink-gray-9' : 'text-ink-gray-5'"
      >
        <span class="text-sm font-medium">{{ day.label }}</span>
        <span
          class="text-sm tabular-nums"
          :class="day.isToday && 'font-display font-semibold text-brand'"
        >
          {{ day.dayOfMonth }}
        </span>
      </div>
      <div class="flex flex-1 flex-col gap-1.5 p-1.5">
        <div
          v-for="(item, idx) in itemsByDay[day.date] || []"
          :key="idx"
          class="group rounded-md border border-outline-gray-1 bg-surface-elevation-1 px-2.5 py-2 shadow-sm"
        >
          <div class="flex items-center justify-between gap-1">
            <div class="flex min-w-0 items-center gap-1.5">
              <component
                :is="typeIcon(item.activity_type)"
                class="size-3.5 shrink-0"
                :class="statusColor(item.status)"
              />
              <span class="truncate text-sm text-ink-gray-8">
                {{ item.note || __(item.activity_type) }}
              </span>
            </div>
            <Button
              v-if="isOwnPlan && item.status === 'Planned'"
              class="opacity-0 group-hover:opacity-100 !size-5"
              variant="ghost"
              icon="x"
              @click="removeItem(item)"
            />
          </div>
          <div
            v-if="item.reference_docname"
            class="mt-1 truncate text-xs text-ink-gray-5"
          >
            {{ referenceLabel(item) }}
          </div>
          <div
            v-if="item.status !== 'Planned'"
            class="mt-1 text-xs"
            :class="statusColor(item.status)"
          >
            {{ __(item.status) }}
          </div>
        </div>
        <Button
          v-if="isOwnPlan"
          class="w-full opacity-40 hover:opacity-100"
          variant="ghost"
          icon="plus"
          @click="addItem(day.date)"
        />
      </div>
    </div>
  </div>
</template>
<script setup>
import LucideSparkles from '~icons/lucide/sparkles'
import LucidePhone from '~icons/lucide/phone'
import LucideCalendarClock from '~icons/lucide/calendar-clock'
import LucideCircleCheck from '~icons/lucide/circle-check'
import LucideMail from '~icons/lucide/mail'
import LayoutHeader from '@/components/LayoutHeader.vue'
import { renderFieldLayoutDialog } from '@/utils/renderFieldLayoutDialog'
import { usersStore } from '@/stores/users'
import { sessionStore } from '@/stores/session'
import {
  createResource,
  call,
  dayjs,
  Select,
  toast,
  usePageMeta,
} from 'frappe-ui'
import { computed, reactive, ref, watch } from 'vue'

const session = sessionStore()
const { crmUsers, isManager } = usersStore()

// frappe-ui's dayjs has no isoWeek plugin — derive Monday by weekday math
// (dayjs .day(): 0 = Sunday)
function mondayOf(d) {
  const day = d.day()
  return d.subtract(day === 0 ? 6 : day - 1, 'day').format('YYYY-MM-DD')
}

const weekStart = ref(mondayOf(dayjs()))
const planUser = ref(session.user)
const saving = ref(false)
const localItems = reactive({ list: [], baseline: '[]' })

const plan = createResource({
  url: 'crm.api.rep_plan.get_plan',
  makeParams: () => ({ week_start: weekStart.value, user: planUser.value }),
  auto: true,
  onSuccess(data) {
    localItems.list = (data.items || []).map((i) => ({ ...i }))
    localItems.baseline = JSON.stringify(localItems.list)
  },
})

watch([weekStart, planUser], () => plan.reload())

const isOwnPlan = computed(() => planUser.value === session.user)
const dirty = computed(
  () => JSON.stringify(localItems.list) !== localItems.baseline,
)
const isCurrentWeek = computed(() => weekStart.value === mondayOf(dayjs()))

const weekLabel = computed(() => {
  const start = dayjs(weekStart.value)
  return `${start.format('D MMM')} – ${start.add(6, 'day').format('D MMM YYYY')}`
})

const weekDays = computed(() => {
  const today = dayjs().format('YYYY-MM-DD')
  return Array.from({ length: 7 }, (_, i) => {
    const d = dayjs(weekStart.value).add(i, 'day')
    return {
      date: d.format('YYYY-MM-DD'),
      label: d.format('ddd'),
      dayOfMonth: d.format('D'),
      isToday: d.format('YYYY-MM-DD') === today,
      isWeekend: i >= 5,
    }
  })
})

const itemsByDay = computed(() => {
  const out = {}
  for (const item of localItems.list) {
    ;(out[item.planned_date] ||= []).push(item)
  }
  return out
})

const totals = computed(() => {
  const t = { planned: 0, done: 0, missed: 0 }
  for (const item of localItems.list) {
    t.planned += 1
    if (item.status === 'Done') t.done += 1
    if (item.status === 'Missed') t.missed += 1
  }
  return t
})

const userOptions = computed(() => {
  const options = (crmUsers.value || []).map((u) => ({
    label: u.full_name || u.name,
    value: u.name,
  }))
  // the session user must always be selectable (Administrator is not a CRM user)
  if (!options.some((o) => o.value === session.user)) {
    options.unshift({ label: session.user, value: session.user })
  }
  return options
})

function shiftWeek(days) {
  weekStart.value = dayjs(weekStart.value).add(days, 'day').format('YYYY-MM-DD')
}

function goToCurrentWeek() {
  weekStart.value = mondayOf(dayjs())
}

function typeIcon(type) {
  return {
    Call: LucidePhone,
    Meeting: LucideCalendarClock,
    Task: LucideCircleCheck,
    Email: LucideMail,
  }[type]
}

function statusColor(status) {
  if (status === 'Done') return 'text-ink-green-3'
  if (status === 'Missed') return 'text-ink-red-4'
  return 'text-ink-gray-5'
}

function referenceLabel(item) {
  const kind = item.reference_doctype === 'CRM Deal' ? __('Deal') : __('Lead')
  return `${kind} · ${item.reference_docname}`
}

function removeItem(item) {
  localItems.list = localItems.list.filter((i) => i !== item)
}

async function addItem(date) {
  const data = await renderFieldLayoutDialog({
    title: __('Plan an activity'),
    size: 'md',
    fields: [
      {
        fieldname: 'activity_type',
        fieldtype: 'Select',
        label: __('Activity'),
        options: 'Call\nMeeting\nTask\nEmail',
      },
      { fieldname: 'note', fieldtype: 'Data', label: __('Note') },
      {
        fieldname: 'deal',
        fieldtype: 'Link',
        label: __('Related deal'),
        options: 'CRM Deal',
      },
      {
        fieldname: 'lead',
        fieldtype: 'Link',
        label: __('Related lead'),
        options: 'CRM Lead',
      },
    ],
    required: ['activity_type'],
    defaults: { activity_type: 'Task' },
    submitLabel: __('Add to plan'),
    cancelLabel: __('Cancel'),
  })
  if (!data) return
  localItems.list = [
    ...localItems.list,
    {
      activity_type: data.activity_type,
      planned_date: date,
      note: data.note,
      reference_doctype: data.deal ? 'CRM Deal' : data.lead ? 'CRM Lead' : null,
      reference_docname: data.deal || data.lead || null,
      status: 'Planned',
    },
  ]
}

async function proposeWeek() {
  const drafts = await call('crm.api.rep_plan.propose_week', {
    week_start: weekStart.value,
  })
  if (!drafts?.length) {
    toast(__('No open suggestions to plan from.'))
    return
  }
  const planned = new Set(
    localItems.list.map((i) => i.suggestion).filter(Boolean),
  )
  const fresh = drafts.filter((d) => !planned.has(d.suggestion))
  if (!fresh.length) {
    toast(__('All current suggestions are already in this plan.'))
    return
  }
  localItems.list = [
    ...localItems.list,
    ...fresh.map((d) => ({ ...d, status: 'Planned' })),
  ]
  toast.success(
    __('{0} items proposed — review and save to confirm.', [fresh.length]),
  )
}

async function savePlan() {
  saving.value = true
  try {
    await call('crm.api.rep_plan.save_plan', {
      week_start: weekStart.value,
      items: localItems.list,
    })
    plan.reload()
    toast.success(__('Plan saved'))
  } finally {
    saving.value = false
  }
}

usePageMeta(() => ({ title: __('Planner') }))
</script>
