<template>
  <LayoutHeader>
    <template #left-header>
      <ViewBreadcrumbs routeName="Planner" />
    </template>
    <template #right-header>
      <Button
        v-if="isOwnPlan"
        :label="__('Propose my week')"
        :disabled="!canEdit || proposing"
        :loading="proposing"
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
        :disabled="!dirty || !canEdit"
        :loading="saving"
        @click="savePlan"
      />
    </template>
  </LayoutHeader>

  <div
    class="flex flex-wrap items-center justify-between gap-x-4 gap-y-2 border-b px-5 py-2"
  >
    <div class="flex items-center gap-2">
      <Button
        variant="ghost"
        icon="chevron-left"
        :label="__('Previous week')"
        @click="shiftWeek(-7)"
      />
      <div class="text-base font-medium text-ink-gray-8 tabular-nums">
        {{ weekLabel }}
      </div>
      <Button
        variant="ghost"
        icon="chevron-right"
        :label="__('Next week')"
        @click="shiftWeek(7)"
      />
      <Button
        v-if="!isCurrentWeek"
        variant="ghost"
        :label="__('This week')"
        @click="goToCurrentWeek"
      />
    </div>
    <div class="flex flex-wrap items-center gap-3">
      <!-- Counts come from the server's rollup, never from the local buffer:
           the header must agree with the dashboard's adherence figures, and an
           unsaved draft is not something the rest of the CRM can see yet. -->
      <div
        v-if="server.loaded"
        class="flex items-center gap-2 text-sm text-ink-gray-6"
      >
        <span>{{ totals.planned }} {{ __('planned') }}</span>
        <span class="text-ink-green-9">{{ totals.done }} {{ __('done') }}</span>
        <span v-if="totals.missed" class="text-ink-red-9">
          {{ totals.missed }} {{ __('missed') }}
        </span>
        <span
          v-if="unsaved.total"
          class="rounded-full bg-surface-amber-1 px-2 py-0.5 text-ink-orange-9"
        >
          {{ __('{0} unsaved', [unsaved.total]) }}
        </span>
      </div>
      <Select
        v-if="repOptions.length > 1"
        :modelValue="planUser"
        :options="repOptions"
        :aria-label="__('Whose plan to show')"
        class="w-48"
        @update:modelValue="requestUser"
      />
    </div>
  </div>

  <div
    v-if="!canEdit && isOwnPlan && server.loaded"
    class="border-b bg-surface-gray-1 px-5 py-2 text-sm text-ink-gray-6"
  >
    {{
      __(
        'This week is older than the {0}-week matching window, so it can no longer be edited.',
        [MATCH_HORIZON_WEEKS],
      )
    }}
  </div>

  <!-- The plan moved under us. Reloading would take the unsaved buffer with
       it, so the choice is the user's rather than ours. -->
  <div
    v-if="stale"
    class="flex flex-wrap items-center gap-x-4 gap-y-2 border-b bg-surface-amber-1 px-5 py-2 text-sm text-ink-orange-9"
    role="alert"
  >
    <span class="flex-1">
      {{
        __(
          'This week changed somewhere else since you opened it. Your edits are still here, but saving would overwrite the newer version.',
        )
      }}
    </span>
    <Button
      size="sm"
      :label="__('Reload the week')"
      @click="reloadAfterConflict"
    />
    <Button
      size="sm"
      variant="ghost"
      :label="__('Keep editing')"
      @click="stale = false"
    />
  </div>

  <div v-if="outside.length" class="border-b px-5 py-2 text-sm text-ink-gray-6">
    {{
      __('{0} planned item(s) now fall outside this week. Save to move them.', [
        outside.length,
      ])
    }}
    <button
      v-for="item in outside"
      :key="item._uid"
      class="ml-2 underline underline-offset-2 hover:text-ink-gray-8"
      @click="goToWeekOf(item)"
    >
      {{ item.note || __(item.activity_type) }} · {{ item.planned_date }}
    </button>
  </div>

  <ErrorState
    v-if="plan.error"
    class="flex-1"
    :error="plan.error"
    :retry="() => plan.reload()"
  />

  <EmptyState
    v-else-if="showReadOnlyEmpty"
    class="flex-1"
    icon="calendar"
    :title="__('Nothing planned for this week')"
    :description="
      __('No activities are planned for the week of {0}.', [weekLabel])
    "
  />

  <!-- An editable week keeps its columns even when it is empty — they are the
       only way to add anything — so the empty state is a band above them
       rather than a replacement for them. -->
  <div
    v-else-if="showEditableEmpty"
    class="flex flex-wrap items-center gap-x-3 gap-y-1 border-b px-5 py-2"
  >
    <LucideCalendarClock class="size-4 text-ink-gray-5" aria-hidden="true" />
    <span class="text-p-base text-ink-gray-7">
      {{ __('Nothing planned for this week yet.') }}
    </span>
    <span class="text-p-base text-ink-gray-5">
      {{
        __(
          'Add activities day by day, or let the planner draft a week from your open suggestions.',
        )
      }}
    </span>
  </div>

  <div
    v-if="!plan.error && !showReadOnlyEmpty"
    class="flex flex-1 flex-col overflow-y-auto sm:flex-row sm:overflow-x-auto"
  >
    <div
      v-for="day in weekDays"
      :key="day.date"
      class="flex flex-col border-b last:border-b-0 sm:min-w-44 sm:flex-1 sm:border-b-0 sm:border-r sm:last:border-r-0"
      :class="[
        day.isWeekend ? 'bg-surface-gray-1' : '',
        dragOverDate === day.date ? 'v-drop-target' : '',
      ]"
      @dragover="onDragOver($event, day.date)"
      @dragleave="onDragLeave(day.date)"
      @drop="onDrop($event, day.date)"
    >
      <div
        class="flex items-baseline justify-between border-b px-3 py-2"
        :class="day.isToday ? 'text-ink-gray-9' : 'text-ink-gray-5'"
      >
        <span class="text-sm font-medium">{{ dayName(day.date) }}</span>
        <span
          class="text-sm tabular-nums"
          :class="day.isToday && 'font-display font-semibold text-brand'"
        >
          {{ dayOfMonth(day.date) }}
        </span>
      </div>

      <div class="flex flex-1 flex-col gap-1.5 p-1.5">
        <template v-if="plan.loading">
          <Skeleton
            v-for="n in 2"
            :key="n"
            shape="block"
            height="3.25rem"
            rounded="6px"
            :label="day.index === 0 && n === 1 ? __('Loading this week') : ''"
          />
        </template>

        <template v-else>
          <div
            v-for="item in byDay[day.date]"
            :key="item._uid"
            class="v-plan-card group rounded-md border border-outline-gray-1 bg-surface-elevation-1 px-2.5 py-2 shadow-sm"
            :class="dragging === item ? 'opacity-50' : ''"
            :data-plan-uid="item._uid"
            :draggable="canEdit"
            @dragstart="onDragStart($event, item)"
            @dragend="onDragEnd"
            @keydown="onCardKeydown($event, item)"
          >
            <div class="flex items-center justify-between gap-1">
              <div class="flex min-w-0 items-center gap-1.5">
                <component
                  :is="typeIcon(item.activity_type)"
                  class="size-3.5 shrink-0"
                  :class="statusColor(item.status)"
                  aria-hidden="true"
                />
                <!-- The card title is the edit affordance: a real button, so it
                     is reachable by keyboard and carries the item's own name.
                     Two lines, not one: a day column is ~140px wide, and a
                     single truncated line renders most notes as "Set the ne…". -->
                <button
                  data-plan-focus
                  class="line-clamp-2 rounded text-left text-sm text-ink-gray-8 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2"
                  :class="canEdit ? 'hover:text-ink-gray-9' : 'cursor-default'"
                  :disabled="!canEdit"
                  @click="editItem(item)"
                >
                  {{ item.note || __(item.activity_type) }}
                </button>
              </div>
              <div class="flex shrink-0 items-center gap-0.5">
                <Tooltip
                  v-if="item.manual_override"
                  :text="
                    __(
                      'Marked by hand — the daily matcher leaves this item alone.',
                    )
                  "
                >
                  <LucideUserCheck
                    class="size-3.5 text-ink-gray-5"
                    :aria-label="__('Manually overridden')"
                    role="img"
                  />
                </Tooltip>
                <Dropdown
                  v-if="canEdit"
                  :options="itemActions(item)"
                  placement="right"
                >
                  <Button
                    class="v-card-action !size-5"
                    variant="ghost"
                    icon="more-horizontal"
                    :label="__('Actions for this planned activity')"
                  />
                </Dropdown>
                <Button
                  v-if="canEdit"
                  class="v-card-action !size-5"
                  variant="ghost"
                  icon="x"
                  :label="__('Remove planned activity')"
                  @click="removeItem(item)"
                />
              </div>
            </div>

            <router-link
              v-if="referenceRoute(item)"
              :to="referenceRoute(item)"
              class="mt-1 block truncate rounded text-xs text-ink-gray-5 underline-offset-2 hover:text-ink-gray-7 hover:underline focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2"
            >
              {{ referenceKind(item) }} · {{ referenceTitle(item) }}
            </router-link>
            <div
              v-else-if="item.reference_docname"
              class="mt-1 truncate text-xs text-ink-gray-5"
            >
              {{ referenceKind(item) }} · {{ referenceTitle(item) }}
            </div>

            <div
              v-if="item.status !== 'Planned'"
              class="mt-1 text-xs"
              :class="statusColor(item.status)"
            >
              {{ statusLabel(item.status) }}
            </div>
          </div>

          <Button
            v-if="canEdit"
            class="w-full opacity-60 hover:opacity-100 focus-visible:opacity-100"
            variant="ghost"
            icon="plus"
            :label="__('Add an activity')"
            @click="addItem(day.date)"
          />

          <p
            v-else-if="!byDay[day.date]?.length"
            class="px-1 py-2 text-xs text-ink-gray-4"
          >
            {{ __('Nothing planned') }}
          </p>
        </template>
      </div>
    </div>
  </div>

  <!-- Keyboard moves change nothing visible where the focus is, so they are
       announced instead. -->
  <span class="sr-only" role="status" aria-live="polite">{{
    announcement
  }}</span>
</template>

<script setup>
import LucideCalendarClock from '~icons/lucide/calendar-clock'
import LucideCircleCheck from '~icons/lucide/circle-check'
import LucideMail from '~icons/lucide/mail'
import LucidePhone from '~icons/lucide/phone'
import LucideSparkles from '~icons/lucide/sparkles'
import LucideUserCheck from '~icons/lucide/user-check'
import EmptyState from '@/components/ListViews/EmptyState.vue'
import ErrorState from '@/components/ui/ErrorState.vue'
import LayoutHeader from '@/components/LayoutHeader.vue'
import Skeleton from '@/components/ui/Skeleton.vue'
import ViewBreadcrumbs from '@/components/ViewBreadcrumbs.vue'
import { describeError } from '@/utils/describeError'
import { renderFieldLayoutDialog } from '@/utils/renderFieldLayoutDialog'
import {
  EDITABLE_ITEM_FIELDS,
  MATCH_HORIZON_WEEKS,
  addDays,
  dedupeProposals,
  groupItemsByDay,
  isBeforeHorizon,
  mondayOf,
  moveItemToDate,
  planDiff,
  referenceNames,
  referenceRoute,
  rollupTotals,
  toSavePayload,
  todayInTimeZone,
  weekDayCells,
} from '@/utils/planner'
import { sessionStore } from '@/stores/session'
import { usersStore } from '@/stores/users'
import {
  Dropdown,
  Select,
  Tooltip,
  call,
  createResource,
  dayjs,
  getConfig,
  toast,
  usePageMeta,
} from 'frappe-ui'
import {
  computed,
  nextTick,
  onBeforeUnmount,
  onMounted,
  reactive,
  ref,
} from 'vue'
import { onBeforeRouteLeave } from 'vue-router'

const session = sessionStore()
const { getUser } = usersStore()

/* "Today" is a calendar date in the site's timezone, which is the timezone the
   server validates and matches in. Reading it off the browser clock puts a rep
   in another zone into the wrong week around the Sunday/Monday boundary. The
   backend exposes no current_week endpoint, so the site zone from boot
   (App.vue seeds it from window.timezone.system) is the closest source. */
const today = ref(todayInTimeZone(getConfig('systemTimezone')))

const weekStart = ref(mondayOf(today.value))
const planUser = ref(session.user)
const saving = ref(false)
const proposing = ref(false)
const stale = ref(false)
const announcement = ref('')
const dragging = ref(null)
const dragOverDate = ref('')

/* The buffer the user edits, and the last thing the server said. They are kept
   apart on purpose: the header totals and the optimistic-lock timestamp must
   come from the server's version, and `dirty` is the difference between them. */
const localItems = reactive({ list: [] })
const server = reactive({
  loaded: false,
  items: [],
  rollup: {},
  modified: null,
})

/* Display titles for referenced deals and leads, keyed 'DocType:name'. */
const titles = reactive({})

let uidSeq = 0

const plan = createResource({
  url: 'crm.api.rep_plan.get_plan',
  makeParams: () => ({ week_start: weekStart.value, user: planUser.value }),
  auto: true,
  /* Cleared before the request, not after it: leaving week N's rows on screen
     under week N+1's heading — or one rep's plan under another rep's name —
     is worse than showing nothing. */
  onFetch() {
    resetBuffers()
  },
  onSuccess(data) {
    today.value = todayInTimeZone(getConfig('systemTimezone'))
    adoptServerPlan(data)
    loadReferenceTitles(data.items)
  },
  onError(error) {
    resetBuffers()
    toast.error(errorText(error))
  },
})

function resetBuffers() {
  localItems.list = []
  server.loaded = false
  server.items = []
  server.rollup = {}
  server.modified = null
  stale.value = false
}

function withUid(item) {
  return { ...item, _uid: item._uid || `plan-${++uidSeq}` }
}

function adoptServerPlan(data) {
  server.loaded = true
  server.items = (data?.items || []).map((i) => ({ ...i }))
  server.rollup = data?.rollup || {}
  server.modified = data?.modified || null
  localItems.list = server.items.map(withUid)
  stale.value = false
}

/* An action that only touches matcher-owned fields (mark done, mark missed,
   clear override) must not throw away what the user is drafting, so the
   response is merged row by row instead of replacing the buffer. */
function mergeServerPlan(data) {
  server.loaded = true
  server.items = (data?.items || []).map((i) => ({ ...i }))
  server.rollup = data?.rollup || {}
  server.modified = data?.modified || null

  const byName = new Map(server.items.map((i) => [String(i.name), i]))
  localItems.list = localItems.list.map((item) => {
    const fresh = item.name && byName.get(String(item.name))
    if (!fresh) return item
    return {
      ...item,
      status: fresh.status,
      manual_override: fresh.manual_override,
      fulfilled_by_doctype: fresh.fulfilled_by_doctype,
      fulfilled_by: fresh.fulfilled_by,
    }
  })
}

const isOwnPlan = computed(() => planUser.value === session.user)
const beforeHorizon = computed(() =>
  isBeforeHorizon(weekStart.value, today.value),
)
const canEdit = computed(
  () => isOwnPlan.value && !beforeHorizon.value && !plan.loading && !plan.error,
)

const unsaved = computed(() => planDiff(localItems.list, server.items))
const dirty = computed(() => unsaved.value.total > 0)
const totals = computed(() => rollupTotals(server.rollup))

const isCurrentWeek = computed(() => weekStart.value === mondayOf(today.value))

const weekLabel = computed(() => {
  const start = dayjs(weekStart.value)
  return `${start.format('D MMM')} – ${start.add(6, 'day').format('D MMM YYYY')}`
})

const weekDays = computed(() => weekDayCells(weekStart.value, today.value))
const weekDates = computed(() => weekDays.value.map((d) => d.date))

const grouped = computed(() =>
  groupItemsByDay(localItems.list, weekDates.value),
)
const byDay = computed(() => grouped.value.byDay)
const outside = computed(() => grouped.value.outside)

const isEmptyWeek = computed(
  () => server.loaded && !plan.loading && localItems.list.length === 0,
)
const showReadOnlyEmpty = computed(() => isEmptyWeek.value && !canEdit.value)
const showEditableEmpty = computed(() => isEmptyWeek.value && canEdit.value)

/* Only the reps whose plans this user may actually open. Listing every CRM
   user offered rows that 403 on selection. */
const visibleReps = createResource({
  url: 'crm.api.rep_plan.get_visible_reps',
  auto: true,
  initialData: [],
})

function repLabel(name) {
  return getUser(name)?.full_name || name
}

const repOptions = computed(() => {
  const names = new Set([session.user, ...(visibleReps.data || [])])
  return [...names].map((name) => ({ label: repLabel(name), value: name }))
})

function errorText(error) {
  const described = describeError(error)
  return described.message || __('Something went wrong. Please try again.')
}

// -- navigation guards ------------------------------------------------------

function confirmDiscard() {
  if (!dirty.value) return true
  return window.confirm(__('You have unsaved plan changes. Discard them?'))
}

function shiftWeek(days) {
  if (!confirmDiscard()) return
  weekStart.value = addDays(weekStart.value, days)
  plan.reload()
}

function goToCurrentWeek() {
  if (!confirmDiscard()) return
  weekStart.value = mondayOf(today.value)
  plan.reload()
}

function goToWeekOf(item) {
  if (!confirmDiscard()) return
  weekStart.value = mondayOf(item.planned_date)
  plan.reload()
}

function requestUser(name) {
  if (name === planUser.value) return
  if (!confirmDiscard()) return
  planUser.value = name
  plan.reload()
}

function warnOnUnload(event) {
  if (!dirty.value) return
  event.preventDefault()
  // Chrome ignores the string but requires returnValue to be set.
  event.returnValue = ''
}

onMounted(() => window.addEventListener('beforeunload', warnOnUnload))
onBeforeUnmount(() => window.removeEventListener('beforeunload', warnOnUnload))
onBeforeRouteLeave(() => confirmDiscard())

// -- presentation -----------------------------------------------------------

function dayName(date) {
  return dayjs(date).format('ddd')
}

function dayOfMonth(date) {
  return dayjs(date).format('D')
}

function typeIcon(type) {
  return (
    {
      Call: LucidePhone,
      Meeting: LucideCalendarClock,
      Task: LucideCircleCheck,
      Email: LucideMail,
    }[type] || LucideCircleCheck
  )
}

function statusColor(status) {
  if (status === 'Done') return 'text-ink-green-9'
  if (status === 'Missed') return 'text-ink-red-9'
  return 'text-ink-gray-5'
}

function statusLabel(status) {
  if (status === 'Done') return __('Done')
  if (status === 'Missed') return __('Missed')
  return __('Planned')
}

function referenceKind(item) {
  if (item.reference_doctype === 'CRM Deal') return __('Deal')
  if (item.reference_doctype === 'CRM Lead') return __('Lead')
  // An unknown reference type is runtime data; showing it verbatim is honest,
  // and calling it a Lead — as this used to — is not.
  return item.reference_doctype || ''
}

function referenceTitle(item) {
  return (
    titles[`${item.reference_doctype}:${item.reference_docname}`] ||
    item.reference_docname
  )
}

/* Titles are decoration: the docname already identifies the record, so a
   failed lookup degrades to it rather than becoming an error state. */
async function fetchTitles(doctype, names, fields, pick) {
  const missing = names.filter((name) => !(`${doctype}:${name}` in titles))
  if (!missing.length) return
  try {
    const rows = await call('frappe.client.get_list', {
      doctype,
      filters: [['name', 'in', missing]],
      fields: ['name', ...fields],
      limit_page_length: 0,
    })
    for (const row of rows || []) {
      titles[`${doctype}:${row.name}`] = pick(row) || row.name
    }
  } catch {
    // leave the docname standing in
  }
}

function loadReferenceTitles(items) {
  const { deals, leads } = referenceNames(items)
  fetchTitles(
    'CRM Deal',
    deals,
    ['organization', 'lead_name'],
    (row) => row.organization || row.lead_name,
  )
  fetchTitles(
    'CRM Lead',
    leads,
    ['lead_name', 'organization'],
    (row) => row.lead_name || row.organization,
  )
}

// -- editing ----------------------------------------------------------------

function itemDialogFields() {
  return [
    {
      fieldname: 'activity_type',
      fieldtype: 'Select',
      label: __('Activity'),
      options: 'Call\nMeeting\nTask\nEmail',
    },
    { fieldname: 'planned_date', fieldtype: 'Date', label: __('Day') },
    { fieldname: 'note', fieldtype: 'Data', label: __('Note') },
    {
      // One doctype picker plus one Dynamic Link, so there is no precedence
      // rule to get wrong when both a deal and a lead are filled in.
      fieldname: 'reference_doctype',
      fieldtype: 'Select',
      label: __('Related to'),
      options: [
        { label: '', value: '' },
        { label: __('Deal'), value: 'CRM Deal' },
        { label: __('Lead'), value: 'CRM Lead' },
      ],
    },
    {
      fieldname: 'reference_docname',
      fieldtype: 'Dynamic Link',
      label: __('Record'),
      options: 'reference_doctype',
    },
  ]
}

function normaliseDialogData(data) {
  const reference_doctype = data.reference_doctype || null
  return {
    activity_type: data.activity_type,
    planned_date: data.planned_date,
    note: data.note || null,
    reference_doctype,
    // clearing the doctype has to clear the name with it, or the row keeps a
    // dangling reference the server will happily store
    reference_docname: reference_doctype
      ? data.reference_docname || null
      : null,
  }
}

async function addItem(date) {
  const data = await renderFieldLayoutDialog({
    title: __('Plan an activity'),
    size: 'md',
    fields: itemDialogFields(),
    required: ['activity_type', 'planned_date'],
    defaults: { activity_type: 'Task', planned_date: date },
    submitLabel: __('Add to plan'),
    cancelLabel: __('Cancel'),
  })
  if (!data) return
  localItems.list = [
    ...localItems.list,
    withUid({ ...normaliseDialogData(data), status: 'Planned' }),
  ]
}

async function editItem(item) {
  if (!canEdit.value) return
  const defaults = {}
  for (const field of EDITABLE_ITEM_FIELDS) defaults[field] = item[field]
  const data = await renderFieldLayoutDialog({
    title: __('Edit planned activity'),
    size: 'md',
    fields: itemDialogFields(),
    required: ['activity_type', 'planned_date'],
    defaults,
    submitLabel: __('Save changes'),
    cancelLabel: __('Cancel'),
  })
  if (!data) return
  // `name` and `suggestion` ride along untouched: they are what tell the
  // server this is the same row edited, not a replacement, so the matcher
  // state and the suggestion link survive the save.
  localItems.list = localItems.list.map((candidate) =>
    candidate === item
      ? { ...candidate, ...normaliseDialogData(data) }
      : candidate,
  )
}

function removeItem(item) {
  localItems.list = localItems.list.filter((i) => i !== item)
}

// -- rescheduling -----------------------------------------------------------

function onDragStart(event, item) {
  if (!canEdit.value) return
  dragging.value = item
  event.dataTransfer.effectAllowed = 'move'
  // Firefox refuses to start a drag without payload.
  event.dataTransfer.setData('text/plain', item._uid)
}

function onDragEnd() {
  dragging.value = null
  dragOverDate.value = ''
}

function onDragOver(event, date) {
  if (!dragging.value) return
  event.preventDefault()
  event.dataTransfer.dropEffect = 'move'
  dragOverDate.value = date
}

function onDragLeave(date) {
  if (dragOverDate.value === date) dragOverDate.value = ''
}

function onDrop(event, date) {
  if (!dragging.value) return
  event.preventDefault()
  moveTo(dragging.value, date)
  onDragEnd()
}

/* The keyboard equivalent of the drag. Shift+Arrow rather than a bare arrow so
   it cannot be mistaken for caret movement, and it stays inside the displayed
   week because the drop targets do too — leaving the week is what the Day
   field in the edit dialog is for. */
function onCardKeydown(event, item) {
  if (!canEdit.value || !event.shiftKey) return
  const delta =
    event.key === 'ArrowLeft' ? -1 : event.key === 'ArrowRight' ? 1 : 0
  if (!delta) return
  event.preventDefault()
  moveTo(item, addDays(item.planned_date, delta))
}

async function moveTo(item, date) {
  if (!weekDates.value.includes(date)) return
  const next = moveItemToDate(localItems.list, item, date)
  if (next === localItems.list) return
  localItems.list = next
  announcement.value = __('{0} moved to {1}', [
    item.note || item.activity_type,
    dayjs(date).format('ddd D MMM'),
  ])
  // The card is re-created in the other column, so focus has to be put back on
  // it or a keyboard user loses their place after one move.
  await nextTick()
  document
    .querySelector(`[data-plan-uid="${item._uid}"] [data-plan-focus]`)
    ?.focus()
}

// -- fulfilment overrides ---------------------------------------------------

function itemActions(item) {
  const actions = [
    { label: __('Edit'), icon: 'edit-2', onClick: () => editItem(item) },
    {
      label: __('Move a day earlier'),
      icon: 'arrow-left',
      onClick: () => moveTo(item, addDays(item.planned_date, -1)),
    },
    {
      label: __('Move a day later'),
      icon: 'arrow-right',
      onClick: () => moveTo(item, addDays(item.planned_date, 1)),
    },
  ]

  // The override endpoints address a stored child row, so an item that has
  // never been saved has nothing for them to address.
  if (item.name) {
    if (item.status !== 'Done') {
      actions.push({
        label: __('Mark as done'),
        icon: 'check-circle',
        onClick: () => overrideItem('mark_fulfilled', item),
      })
    }
    if (item.status !== 'Missed') {
      actions.push({
        label: __('Mark as missed'),
        icon: 'x-circle',
        onClick: () => overrideItem('mark_missed', item),
      })
    }
    if (item.manual_override) {
      actions.push({
        label: __('Hand back to the matcher'),
        icon: 'rotate-ccw',
        onClick: () => overrideItem('clear_override', item),
      })
    }
  }

  actions.push({
    label: __('Remove from plan'),
    icon: 'trash-2',
    onClick: () => removeItem(item),
  })
  return actions
}

const OVERRIDE_DONE = {
  mark_fulfilled: () => __('Marked as done.'),
  mark_missed: () => __('Marked as missed.'),
  clear_override: () => __('Handed back to the matcher.'),
}

async function overrideItem(method, item) {
  try {
    const data = await call(`crm.api.rep_plan.${method}`, { item: item.name })
    mergeServerPlan(data)
    toast.success(OVERRIDE_DONE[method]())
  } catch (error) {
    toast.error(errorText(error))
  }
}

// -- proposing and saving ---------------------------------------------------

async function proposeWeek() {
  if (proposing.value) return
  proposing.value = true
  try {
    const drafts = await call('crm.api.rep_plan.propose_week', {
      week_start: weekStart.value,
    })
    if (!drafts?.length) {
      toast(__('No open suggestions to plan from.'))
      return
    }
    const fresh = dedupeProposals(drafts, localItems.list)
    if (!fresh.length) {
      toast(__('All current suggestions are already in this plan.'))
      return
    }
    localItems.list = [
      ...localItems.list,
      ...fresh.map((draft) => withUid({ ...draft, status: 'Planned' })),
    ]
    toast.success(
      __('{0} items proposed — review and save to confirm.', [fresh.length]),
    )
  } catch (error) {
    toast.error(errorText(error))
  } finally {
    proposing.value = false
  }
}

async function savePlan() {
  if (saving.value || !canEdit.value) return
  saving.value = true
  try {
    const data = await call('crm.api.rep_plan.save_plan', {
      week_start: weekStart.value,
      items: toSavePayload(localItems.list),
      // round-tripped so the server can tell us the week moved under us rather
      // than silently overwriting whoever got there first
      modified: server.modified || undefined,
    })
    adoptServerPlan(data)
    loadReferenceTitles(data.items)
    toast.success(__('Plan saved'))
  } catch (error) {
    // The buffer is deliberately left alone on every failure path: a save that
    // did not happen must not cost the user their edits.
    if (error?.exc_type === 'TimestampMismatchError') stale.value = true
    else toast.error(errorText(error))
  } finally {
    saving.value = false
  }
}

function reloadAfterConflict() {
  if (!confirmDiscard()) return
  stale.value = false
  plan.reload()
}

usePageMeta(() => ({ title: __('Planner') }))
</script>

<style scoped>
/* Hover-revealed controls have to come back for keyboard users too: a focusable
   control at opacity 0 is a tab stop nobody can see, and the global
   focus-visible ring then outlines nothing. */
.v-card-action {
  opacity: 0;
  transition: opacity var(--motion-fast) var(--motion-ease);
}

.v-plan-card:hover .v-card-action,
.v-plan-card:focus-within .v-card-action,
.v-card-action:focus-visible {
  opacity: 1;
}

/* Coarse pointers get no hover, so the actions are always shown there. */
@media (hover: none) {
  .v-card-action {
    opacity: 1;
  }
}

.v-drop-target {
  background-color: var(--surface-gray-2);
  box-shadow: inset 0 0 0 2px var(--outline-gray-3);
}
</style>
