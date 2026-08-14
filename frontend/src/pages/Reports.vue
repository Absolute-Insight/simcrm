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
      <Button :label="__('Export CSV')" @click="exportCsv">
        <template #prefix>
          <LucideDownload class="size-4" />
        </template>
      </Button>
      <Button :label="__('Print')" @click="printReport">
        <template #prefix>
          <LucidePrinter class="size-4" />
        </template>
      </Button>
    </template>
  </LayoutHeader>

  <div class="flex flex-1 overflow-hidden">
    <div class="flex w-56 shrink-0 flex-col gap-0.5 border-r p-2 print:hidden">
      <button
        v-for="r in reports.data || []"
        :key="r.name"
        class="rounded px-2.5 py-2 text-left text-base transition"
        :class="
          r.name === active
            ? 'bg-surface-elevation-3 text-ink-gray-9 shadow-sm'
            : 'text-ink-gray-6 hover:bg-surface-gray-2'
        "
        @click="active = r.name"
      >
        {{ __(r.title) }}
      </button>
    </div>

    <div id="report-print-area" class="flex flex-1 flex-col overflow-hidden">
      <div
        class="flex items-center justify-between border-b px-5 py-2 print:hidden"
      >
        <div class="flex items-center gap-2">
          <DateRangePicker
            class="!w-56"
            :value="parseDateRange(dateRange)"
            variant="outline"
            :placeholder="__('Date range')"
            @change="
              (v) =>
                (dateRange = Array.isArray(v)
                  ? v.join(',')
                  : v || getLastXDays())
            "
          />
          <Select
            v-if="isManager()"
            v-model="scopeUser"
            :options="userOptions"
            class="w-44"
          />
        </div>
        <div v-if="report.data" class="text-sm text-ink-gray-5">
          {{ report.data.rows.length }} {{ __('rows') }}
        </div>
      </div>

      <div class="hidden print:block px-5 pt-4">
        <div class="text-xl font-semibold">{{ report.data?.title }}</div>
        <div class="text-sm text-ink-gray-6">{{ fromDate }} – {{ toDate }}</div>
      </div>

      <div v-if="report.data" class="flex-1 overflow-auto px-5 py-4">
        <p class="mb-3 text-sm text-ink-gray-6 print:hidden">
          {{ __(report.data.description) }}
        </p>
        <table class="w-full border-collapse text-base">
          <thead>
            <tr>
              <th
                v-for="col in report.data.columns"
                :key="col.key"
                class="sticky top-0 border-b-2 border-outline-gray-2 bg-surface-base px-3 py-2 text-left text-xs font-medium uppercase tracking-wider text-ink-gray-5"
                :class="col.type !== 'text' && 'text-right'"
              >
                {{ __(col.label) }}
              </th>
            </tr>
          </thead>
          <tbody>
            <tr
              v-for="(row, i) in report.data.rows"
              :key="i"
              class="hover:bg-surface-gray-1"
            >
              <td
                v-for="col in report.data.columns"
                :key="col.key"
                class="border-b border-outline-gray-1 px-3 py-2 tabular-nums"
                :class="col.type !== 'text' && 'text-right'"
              >
                {{ formatCell(row[col.key], col.type) }}
              </td>
            </tr>
            <tr v-if="!report.data.rows.length">
              <td
                :colspan="report.data.columns.length"
                class="px-3 py-8 text-center text-ink-gray-5"
              >
                {{ __('No data in this period.') }}
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>
  </div>
</template>
<script setup>
import LucideDownload from '~icons/lucide/download'
import LucidePrinter from '~icons/lucide/printer'
import LayoutHeader from '@/components/LayoutHeader.vue'
import { usersStore } from '@/stores/users'
import { getLastXDays, parseDateRange } from '@/utils/dashboard'
import { createResource, DateRangePicker, Select, usePageMeta } from 'frappe-ui'
import { computed, ref, watch } from 'vue'

const { crmUsers, isManager } = usersStore()

const active = ref('pipeline_by_stage')
const scopeUser = ref('')
const dateRange = ref(getLastXDays())

const fromDate = computed(() => parseDateRange(dateRange.value)[0])
const toDate = computed(() => parseDateRange(dateRange.value)[1])

const reports = createResource({
  url: 'crm.api.reports.list_reports',
  initialData: [],
  auto: true,
})

const report = createResource({
  url: 'crm.api.reports.get_report',
  makeParams: () => ({
    name: active.value,
    from_date: fromDate.value,
    to_date: toDate.value,
    user: scopeUser.value || null,
  }),
  auto: true,
})

watch([active, dateRange, scopeUser], () => report.reload())

const userOptions = computed(() => [
  { label: __('Everyone'), value: '' },
  ...(crmUsers.value || []).map((u) => ({
    label: u.full_name || u.name,
    value: u.name,
  })),
])

const currencyFormat = new Intl.NumberFormat(undefined, {
  maximumFractionDigits: 0,
})

function formatCell(value, type) {
  if (value === null || value === undefined || value === '') return '—'
  if (type === 'currency') return currencyFormat.format(value)
  if (type === 'percent') return `${value}%`
  return value
}

function exportCsv() {
  const data = report.data
  if (!data) return
  const esc = (v) => {
    const s = String(v ?? '')
    return /[",\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s
  }
  const lines = [
    data.columns.map((c) => esc(c.label)).join(','),
    ...data.rows.map((row) =>
      data.columns.map((c) => esc(row[c.key])).join(','),
    ),
  ]
  const blob = new Blob([lines.join('\n')], { type: 'text/csv;charset=utf-8' })
  const link = document.createElement('a')
  link.href = URL.createObjectURL(blob)
  link.download = `${data.name}-${fromDate.value}-to-${toDate.value}.csv`
  link.click()
  URL.revokeObjectURL(link.href)
}

function printReport() {
  window.print()
}

usePageMeta(() => ({ title: __('Reports') }))
</script>
<style>
@media print {
  /* the report table is the page: hide the app shell around it */
  body * {
    visibility: hidden;
  }
  #report-print-area,
  #report-print-area * {
    visibility: visible;
  }
  #report-print-area {
    position: absolute;
    inset: 0;
  }
}
</style>
