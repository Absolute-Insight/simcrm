<template>
  <LayoutHeader>
    <template #left-header>
      <div
        class="font-display text-lg font-medium tracking-tight text-ink-gray-7 px-0.5 py-1"
      >
        {{ __('Analyst') }}
      </div>
    </template>
    <template #right-header>
      <Button
        v-if="analystMessages.length"
        :label="__('Clear')"
        @click="clearAnalyst"
      >
        <template #prefix>
          <LucideEraser class="size-4" />
        </template>
      </Button>
    </template>
  </LayoutHeader>

  <div class="flex min-h-0 flex-1 justify-center overflow-hidden">
    <div class="flex w-full max-w-4xl min-h-0 flex-col">
      <AgentChat
        :messages="analystMessages"
        :asking="analystAsking"
        :failure="analystFailure"
        :examples="exampleQuestions"
        :intro="intro"
        :placeholder="__('Ask about the business…')"
        :focus-when="true"
        @send="askAnalyst"
        @retry="retryAnalyst"
      >
        <template #message-extra="{ message }">
          <ul
            v-if="message.highlights?.length"
            class="ml-4 list-disc space-y-1 text-base text-ink-gray-8"
          >
            <li v-for="(line, index) in message.highlights" :key="index">
              {{ line }}
            </li>
          </ul>

          <div
            v-for="table in formattedTables(message)"
            :key="table.key"
            class="flex flex-col gap-2 rounded-lg border border-outline-gray-1 bg-surface-elevation-1 p-3"
          >
            <div class="flex items-center justify-between gap-2">
              <div class="flex min-w-0 items-center gap-2">
                <span class="truncate text-base font-medium text-ink-gray-8">
                  {{ table.title }}
                </span>
                <Badge variant="subtle" :label="table.source" />
              </div>
              <div class="flex shrink-0 items-center gap-2">
                <span class="text-xs text-ink-gray-5">
                  {{ periodLabel(message.period) }}
                </span>
                <Button
                  v-if="table.rows.length"
                  size="sm"
                  variant="ghost"
                  :aria-label="__('Export CSV')"
                  :tooltip="__('Export CSV')"
                  @click="exportCsv(table, message.period)"
                >
                  <template #icon>
                    <LucideDownload class="size-4" />
                  </template>
                </Button>
              </div>
            </div>

            <p v-if="table.error" class="text-sm text-ink-orange-9">
              {{
                __(
                  'This source could not be reached. The figures shown come from the CRM only.',
                )
              }}
            </p>
            <p v-else-if="!table.rows.length" class="text-sm text-ink-gray-5">
              {{ __('No rows in this period.') }}
            </p>
            <div v-else class="overflow-x-auto">
              <table class="analyst-table w-full text-sm">
                <thead>
                  <tr>
                    <th
                      v-for="column in table.columns"
                      :key="column.key"
                      :class="column.align === 'right' ? 'text-right' : ''"
                    >
                      {{ column.label }}
                    </th>
                  </tr>
                </thead>
                <tbody>
                  <tr v-for="(row, rowIndex) in table.rows" :key="rowIndex">
                    <td
                      v-for="(cell, cellIndex) in row"
                      :key="cellIndex"
                      :class="
                        table.columns[cellIndex]?.align === 'right'
                          ? 'text-right tabular-nums'
                          : ''
                      "
                    >
                      {{ cell }}
                    </td>
                  </tr>
                </tbody>
              </table>
            </div>
            <p v-if="table.note" class="text-xs text-ink-gray-5">
              {{ table.note }}
            </p>
          </div>

          <div
            v-if="message.caveats?.length"
            class="rounded-lg bg-surface-gray-1 px-3 py-2 text-sm text-ink-gray-6"
          >
            <p
              v-for="(line, index) in message.caveats"
              :key="index"
              class="leading-relaxed"
            >
              {{ line }}
            </p>
          </div>
        </template>

        <template #failure="{ failure }">
          <p class="text-sm text-ink-gray-6">{{ failureCopy(failure) }}</p>
        </template>

        <template #failure-actions="{ failure }">
          <Button
            v-if="failure === 'disabled'"
            size="sm"
            variant="subtle"
            :label="__('Open assistant settings')"
            @click="openAssistantSettings"
          />
          <Button
            v-else-if="failure === 'unavailable'"
            size="sm"
            variant="subtle"
            :label="__('Try again')"
            @click="retryAnalyst"
          />
        </template>
      </AgentChat>
    </div>
  </div>
</template>

<script setup>
import { PhDownloadSimple as LucideDownload } from '@phosphor-icons/vue'
import { PhEraser as LucideEraser } from '@phosphor-icons/vue'
import AgentChat from '@/components/AgentChat.vue'
import LayoutHeader from '@/components/LayoutHeader.vue'
import { activeSettingsPage, showSettings } from '@/composables/settings'
import {
  analystAsking,
  analystFailure,
  analystFailureReason,
  analystMessages,
  askAnalyst,
  clearAnalyst,
  retryAnalyst,
} from '@/stores/analyst'
import { formatTable, monthLabel } from '@/utils/analystTables'
import { Badge } from 'frappe-ui'

const intro = __(
  'Ask about the business in plain language. Vectora runs its own calculations — revenue, pipeline, forecasts, targets, deals at risk — and the Analyst explains the figures. Every number on this page comes from those calculations, not from the model. With an ERP connected it can also read invoices, payments and receivables.',
)

const exampleQuestions = [
  __('How did revenue grow over the last six months?'),
  __('Which reps are behind quota this quarter?'),
  __('Which deals and accounts are likely to go quiet?'),
  __('Project revenue for the next quarter'),
  __(
    'What came in as cash last month against what we invoiced? (needs an ERP)',
  ),
]

function formattedTables(message) {
  return (message.tables || []).map((table) =>
    formatTable(table, message.currency),
  )
}

function periodLabel(period) {
  if (!period?.from_date || !period?.to_date) return ''
  return `${monthLabel(period.from_date.slice(0, 7))} – ${monthLabel(period.to_date.slice(0, 7))}`
}

function failureCopy(failure) {
  if (failure === 'disabled') {
    return analystFailureReason.value === 'analyst_off'
      ? __(
          'The Analyst is switched off. Turn on "Allow the Analyst to read CRM and ERP data" in Settings → Assistant.',
        )
      : __(
          'The model tier is switched off. Point Vectora at a model endpoint in Settings → Assistant to enable it.',
        )
  }
  return __(
    'The Analyst could not be reached right now. Your question was not lost — try again in a moment.',
  )
}

function openAssistantSettings() {
  activeSettingsPage.value = 'Assistant'
  showSettings.value = true
}

function exportCsv(table, period) {
  const blob = new Blob([table.csv()], { type: 'text/csv;charset=utf-8' })
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = `${table.key}-${period?.from_date || ''}-to-${period?.to_date || ''}.csv`
  // Firefox ignores a click on an anchor that is not in the document, and
  // revoking the URL in the same tick can abort the download.
  document.body.appendChild(link)
  link.click()
  link.remove()
  setTimeout(() => URL.revokeObjectURL(url), 0)
}
</script>

<style scoped>
.analyst-table th {
  padding: 0.375rem 0.5rem;
  border-bottom: 1px solid var(--outline-gray-2);
  text-align: left;
  font-weight: 600;
  color: var(--ink-gray-8);
}

/* The measure columns: this rule must outrank the base th rule above, which
   the bare utility class does not. */
.analyst-table th.text-right {
  text-align: right;
}

.analyst-table td {
  padding: 0.375rem 0.5rem;
  border-bottom: 1px solid var(--outline-gray-1);
  vertical-align: top;
  color: var(--ink-gray-7);
}
</style>
