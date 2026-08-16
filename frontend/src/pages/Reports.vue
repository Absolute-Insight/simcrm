<template>
  <LayoutHeader>
    <template #left-header>
      <div
        class="font-display text-lg font-medium tracking-tight text-ink-gray-7 px-0.5 py-1"
      >
        {{ __('Reports') }}
      </div>
    </template>
    <template #right-header>
      <Button :label="__('Export CSV')" :disabled="!hasRows" @click="exportCsv">
        <template #prefix>
          <LucideDownload class="size-4" />
        </template>
      </Button>
      <Button :label="__('Print')" :disabled="!hasRows" @click="printReport">
        <template #prefix>
          <LucidePrinter class="size-4" />
        </template>
      </Button>
    </template>
  </LayoutHeader>

  <div class="flex flex-1 overflow-hidden">
    <!-- The picker is a vertical rail on a desktop and a Select on a phone:
         224px of rail out of a 375px viewport leaves nothing for the table. -->
    <nav
      class="hidden w-56 shrink-0 flex-col gap-0.5 border-r p-2 sm:flex print:hidden"
      role="tablist"
      :aria-label="__('Reports')"
      aria-orientation="vertical"
    >
      <div
        v-if="reports.loading && !reports.data?.length"
        class="flex flex-col gap-2 p-1.5"
      >
        <Skeleton
          shape="block"
          height="0.75rem"
          :label="__('Loading reports')"
        />
        <Skeleton shape="block" height="0.75rem" width="80%" />
        <Skeleton shape="block" height="0.75rem" width="65%" />
      </div>
      <ErrorState
        v-else-if="reports.error"
        compact
        :error="reports.error"
        :title="__('Could not load the report list')"
        :retry="reports.reload"
      />
      <template v-else>
        <button
          v-for="r in reports.data || []"
          :key="r.name"
          class="v-rail rounded-4 px-2.5 py-2 text-left text-base"
          :class="
            r.name === active
              ? 'bg-surface-elevation-3 text-ink-gray-9 shadow-sm'
              : 'text-ink-gray-6 hover:bg-surface-gray-2'
          "
          role="tab"
          :data-state="r.name === active ? 'active' : 'inactive'"
          :aria-selected="r.name === active"
          @click="active = r.name"
        >
          {{ r.title }}
        </button>
      </template>
    </nav>

    <div
      id="report-print-area"
      class="flex min-w-0 flex-1 flex-col overflow-hidden"
    >
      <div
        class="flex flex-wrap items-center gap-2 border-b px-3 py-2 sm:px-5 print:hidden"
      >
        <Select
          v-if="reportOptions.length"
          v-model="active"
          class="w-full sm:hidden"
          :options="reportOptions"
          :aria-label="__('Report')"
        />

        <!-- Same preset dropdown + user Link as the Dashboard filter bar, so
             the two analytics surfaces are filtered the same way. -->
        <template v-if="showPeriodFilter">
          <Dropdown
            v-if="!showDatePicker"
            :options="presetOptions"
            class="form-control"
            :button="{
              label: presetLabel,
              class:
                '!w-full justify-start [&>span]:mr-auto [&>svg]:text-ink-gray-5',
              variant: 'outline',
              iconRight: 'lucide-chevron-down',
              iconLeft: 'lucide-calendar',
            }"
          />
          <DateRangePicker
            v-else
            ref="datePickerRef"
            class="!w-48"
            :value="parseDateRange(dateRange)"
            variant="outline"
            :placeholder="__('Period')"
            :formatter="formatRange"
            @change="onDateRangeChange"
          >
            <template #prefix>
              <LucideCalendar class="size-4 text-ink-gray-5 mr-2" />
            </template>
          </DateRangePicker>
        </template>

        <Link
          v-if="isManager() || isAdmin()"
          class="form-control w-48"
          variant="outline"
          :value="scopeUser && getUser(scopeUser).full_name"
          doctype="User"
          :filters="{
            name: ['in', (crmUsers || []).map((u) => u.name)],
            ignore_user_type: 1,
          }"
          :placeholder="__('Sales User')"
          :hideMe="true"
          @change="(v) => (scopeUser = v || '')"
        >
          <template #prefix>
            <UserAvatar
              v-if="scopeUser"
              class="mr-2"
              :user="scopeUser"
              size="sm"
            />
          </template>
          <template #item-prefix="{ option }">
            <UserAvatar class="mr-2" :user="option.value" size="sm" />
          </template>
          <template #item-label="{ option }">
            <Tooltip :text="option.value">
              <div class="cursor-pointer text-ink-gray-9">
                {{ getUser(option.value).full_name }}
              </div>
            </Tooltip>
          </template>
        </Link>

        <div v-if="showing" class="ml-auto text-sm text-ink-gray-5">
          {{ __('{0} rows', [showing.rows.length]) }}
        </div>
      </div>

      <!-- Print-only masthead: the on-screen filter bar is hidden on paper, so
           the sheet has to say what it is a report of and over what period. -->
      <div v-if="showing" class="hidden px-5 pt-4 print:block">
        <div class="text-xl font-semibold">{{ showing.title }}</div>
        <div class="text-sm text-ink-gray-6">
          {{ showing.period === false ? __('As at today') : printedRange }}
        </div>
      </div>

      <ErrorState
        v-if="report.error"
        class="flex-1"
        :error="report.error"
        :title="__('Could not load this report')"
        :retry="report.reload"
      />

      <div v-else-if="!showing" class="flex-1 overflow-auto px-3 py-4 sm:px-5">
        <SkeletonTable
          :columns="skeletonColumns"
          :rows="8"
          :label="__('Loading report')"
        />
      </div>

      <div v-else class="flex-1 overflow-auto px-3 py-4 sm:px-5">
        <p class="mb-3 text-sm text-ink-gray-6 print:hidden">
          {{ showing.description }}
        </p>

        <EmptyState
          v-if="!showing.rows.length"
          icon="lucide-bar-chart-2"
          :title="__('Nothing to report')"
          :description="
            showing.period === false
              ? __('There is no open pipeline to summarise yet.')
              : __('No activity fell inside this period. Try a wider range.')
          "
          top="20%"
        />

        <table v-else class="w-full border-collapse text-base">
          <thead>
            <tr>
              <th
                v-for="col in showing.columns"
                :key="col.key"
                class="sticky top-0 border-b-2 border-outline-gray-2 bg-surface-base px-3 py-2 text-left text-xs font-medium uppercase tracking-wider text-ink-gray-5 print:static"
                :class="col.type !== 'text' && 'text-right'"
                :abbr="col.description || undefined"
              >
                <Tooltip v-if="col.description" :text="col.description">
                  <span class="inline-flex items-center gap-1">
                    {{ col.label }}
                    <LucideInfo class="size-3 shrink-0 print:hidden" />
                  </span>
                </Tooltip>
                <template v-else>{{ col.label }}</template>
              </th>
            </tr>
          </thead>
          <tbody>
            <tr
              v-for="(row, i) in showing.rows"
              :key="i"
              class="hover:bg-surface-gray-1"
            >
              <td
                v-for="col in showing.columns"
                :key="col.key"
                class="border-b border-outline-gray-1 px-3 py-2 tabular-nums"
                :class="col.type !== 'text' && 'text-right'"
              >
                {{ formatCell(row[col.key], col.type, baseCurrency) }}
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>
  </div>
</template>

<script setup>
import LucideCalendar from '~icons/lucide/calendar'
import LucideDownload from '~icons/lucide/download'
import LucideInfo from '~icons/lucide/info'
import LucidePrinter from '~icons/lucide/printer'
import EmptyState from '@/components/ListViews/EmptyState.vue'
import LayoutHeader from '@/components/LayoutHeader.vue'
import Link from '@/components/Controls/Link.vue'
import UserAvatar from '@/components/UserAvatar.vue'
import ErrorState from '@/components/ui/ErrorState.vue'
import Skeleton from '@/components/ui/Skeleton.vue'
import SkeletonTable from '@/components/ui/SkeletonTable.vue'
import { getSettings } from '@/stores/settings'
import { usersStore } from '@/stores/users'
import { formatRange, getLastXDays, parseDateRange } from '@/utils/dashboard'
import { formatCell, toCsv } from '@/utils/reportExport'
import {
  createResource,
  DateRangePicker,
  Dropdown,
  Select,
  Tooltip,
  usePageMeta,
} from 'frappe-ui'
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'

const route = useRoute()
const router = useRouter()

const { crmUsers, getUser, isManager, isAdmin } = usersStore()
const { settings } = getSettings()

const PRESET_DAYS = [7, 30, 60, 90]
const DEFAULT_PRESET_DAYS = 30

const active = ref(String(route.query.report || ''))
const scopeUser = ref(String(route.query.user || ''))
const dateRange = ref(
  String(route.query.range || '') || getLastXDays(DEFAULT_PRESET_DAYS),
)

/* Which preset the current range corresponds to, so a bookmarked URL reopens
   showing "Last 30 Days" rather than an anonymous custom range. */
function presetDaysFor(range) {
  return PRESET_DAYS.find((days) => getLastXDays(days) === range) ?? null
}

const showDatePicker = ref(presetDaysFor(dateRange.value) === null)
const datePickerRef = ref(null)

const presetLabel = computed(() => {
  const days = presetDaysFor(dateRange.value)
  return days === null
    ? __('Custom Range')
    : __('Last {0} Days', [String(days)])
})

const presetOptions = computed(() => [
  {
    group: 'Presets',
    hideLabel: true,
    options: PRESET_DAYS.map((days) => ({
      label: __('Last {0} Days', [String(days)]),
      onClick: () => {
        showDatePicker.value = false
        dateRange.value = getLastXDays(days)
      },
    })),
  },
  {
    label: __('Custom Range'),
    onClick: () => {
      showDatePicker.value = true
      nextTick(() => datePickerRef.value?.open())
    },
  },
])

function onDateRangeChange(value) {
  const next = Array.isArray(value) ? value.join(',') : value
  if (!next) {
    showDatePicker.value = false
    dateRange.value = getLastXDays(DEFAULT_PRESET_DAYS)
    return
  }
  dateRange.value = next
}

const fromDate = computed(() => parseDateRange(dateRange.value)[0])
const toDate = computed(() => parseDateRange(dateRange.value)[1])
const printedRange = computed(
  () => `${formatRange(fromDate.value)} – ${formatRange(toDate.value)}`,
)

const reports = createResource({
  url: 'crm.api.reports.list_reports',
  initialData: [],
  auto: true,
  onSuccess(data) {
    // The registry owns which reports exist and which one is first; a
    // hardcoded default here would silently break when it is reordered.
    if (!data?.length) return
    if (!data.some((r) => r.name === active.value)) active.value = data[0].name
  },
})

const reportOptions = computed(() =>
  (reports.data || []).map((r) => ({ label: r.title, value: r.name })),
)

const activeReport = computed(() =>
  (reports.data || []).find((r) => r.name === active.value),
)

/* pipeline_by_stage is a snapshot of the pipeline as it stands, not of a
   window, so the registry marks it period:false and the picker goes away
   rather than offering a control that changes nothing. */
const showPeriodFilter = computed(() => activeReport.value?.period !== false)

const requestKey = computed(() =>
  [active.value, fromDate.value, toDate.value, scopeUser.value].join('|'),
)
const loadedKey = ref('')

const report = createResource({
  url: 'crm.api.reports.get_report',
  makeParams: () => ({
    name: active.value,
    from_date: fromDate.value,
    to_date: toDate.value,
    user: scopeUser.value || null,
  }),
  auto: false,
  onSuccess() {
    loadedKey.value = requestKey.value
  },
})

/* The payload only stands for the selection that produced it. Rendering
   `report.data` directly is what let a failed or in-flight reload keep the
   previous report's rows on screen under a newly chosen report or period. */
const showing = computed(() =>
  loadedKey.value && loadedKey.value === requestKey.value ? report.data : null,
)

const hasRows = computed(() => Boolean(showing.value?.rows?.length))

/* Keep the loading table the shape of the answer where we already know it —
   the previous payload's columns are the closest guess available. */
const skeletonColumns = computed(() => report.data?.columns?.length || 4)

const baseCurrency = computed(
  () => settings.value?.currency || window.sysdefaults?.currency || 'USD',
)

watch(
  requestKey,
  () => {
    if (active.value) report.fetch()
  },
  { immediate: true },
)

/* Deep-linkable state. `replace` rather than `push`: changing a filter is not
   a place in history to go back to, but the URL still has to be bookmarkable. */
watch([active, dateRange, scopeUser, showPeriodFilter], () => {
  const query = {
    report: active.value || undefined,
    range: showPeriodFilter.value ? dateRange.value || undefined : undefined,
    user: scopeUser.value || undefined,
  }
  /* Written straight to history rather than through router.replace: App.vue
     keys the router-view on the full path, so a query change there would tear
     the page down and refetch everything on every filter interaction. */
  const href = router.resolve({ name: 'Reports', query }).href
  if (href !== window.location.pathname + window.location.search) {
    window.history.replaceState(window.history.state, '', href)
  }
})

function exportCsv() {
  const data = showing.value
  if (!data) return

  const blob = new Blob([toCsv(data.columns, data.rows, baseCurrency.value)], {
    type: 'text/csv;charset=utf-8',
  })
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = `${data.name}-${fromDate.value}-to-${toDate.value}.csv`
  // Firefox ignores a click on an anchor that is not in the document, and
  // revoking the URL in the same tick can abort the download.
  document.body.appendChild(link)
  link.click()
  link.remove()
  setTimeout(() => URL.revokeObjectURL(url), 0)
}

function printReport() {
  window.print()
}

/* The print rules below have to reach <body>, so the style block cannot be
   scoped. This class is what keeps them inert on every other route: without
   it, visiting Reports once made Ctrl+P print a blank sheet app-wide. */
onMounted(() => document.body.classList.add('printing-report'))
onBeforeUnmount(() => document.body.classList.remove('printing-report'))

usePageMeta(() => ({ title: __('Reports') }))
</script>
<style>
@media print {
  @page {
    margin: 12mm;
  }

  /* The app shell is a fixed-height scroller (h-screen + overflow-auto) and so
     is the report body. A browser clips rather than paginates inside an
     overflow container, so without unwinding every one of them the sheet stops
     at whatever happened to be on screen. `:has()` reaches the whole ancestor
     chain, which lives in layout components this page does not own. */
  html,
  body.printing-report,
  body.printing-report:has(#report-print-area) *:has(#report-print-area) {
    height: auto !important;
    max-height: none !important;
    overflow: visible !important;
  }

  /* Everything alongside the report — sidebar, app header, the report rail —
     is removed from layout rather than merely hidden, so it leaves no blank
     band at the top of the first page. */
  body.printing-report
    :has(#report-print-area)
    > *:not(#report-print-area):not(:has(#report-print-area)) {
    display: none !important;
  }

  /* Belt and braces for engines without :has(): nothing but the report inks. */
  body.printing-report * {
    visibility: hidden;
  }
  body.printing-report #report-print-area,
  body.printing-report #report-print-area * {
    visibility: visible;
  }

  /* Static, not absolute: an absolutely positioned box is laid out against a
     single page box, which is exactly how the report used to lose page two. */
  body.printing-report #report-print-area {
    position: static !important;
    display: block !important;
    width: 100% !important;
  }
  body.printing-report #report-print-area,
  body.printing-report #report-print-area * {
    height: auto !important;
    max-height: none !important;
    overflow: visible !important;
    flex: none !important;
  }

  /* A sticky header does not paginate; a table header group does — it reprints
     on every sheet, which is the only way a long table stays readable. */
  body.printing-report #report-print-area thead {
    display: table-header-group;
  }
  body.printing-report #report-print-area thead th {
    position: static !important;
  }
  body.printing-report #report-print-area tr {
    break-inside: avoid;
  }
}
</style>
