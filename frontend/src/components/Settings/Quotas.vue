<template>
  <div class="flex h-full flex-col gap-4 p-8">
    <div class="flex items-start justify-between gap-4">
      <div class="flex flex-col gap-1">
        <h2 class="v-title text-ink-gray-8">
          {{ __('Sales Targets') }}
        </h2>
        <p class="text-p-sm text-ink-gray-5">
          {{
            __(
              'Monthly revenue target per rep. Quarter, year and team numbers are summed from these — set the months and everything else follows.',
            )
          }}
        </p>
      </div>
      <div class="flex shrink-0 items-center gap-1">
        <Button
          variant="ghost"
          icon="lucide-chevron-left"
          :aria-label="__('Previous year')"
          @click="year -= 1"
        />
        <div class="w-14 text-center text-base font-medium tabular-nums">
          {{ year }}
        </div>
        <Button
          variant="ghost"
          icon="lucide-chevron-right"
          :aria-label="__('Next year')"
          @click="year += 1"
        />
      </div>
    </div>

    <!-- SkeletonTable rather than a centred spinner: this is a rep x month
         grid, and its docstring already names the quota table as a call site.
         A spinner in the middle of the pane says "something is happening
         somewhere"; the skeleton says what shape is coming and stops the
         layout jumping when it does. 14 columns: the rep, twelve months and
         the row total. -->
    <SkeletonTable
      v-if="grid.loading"
      :columns="14"
      :rows="6"
      density="compact"
      class="flex-1 px-1"
      :label="__('Loading sales targets')"
    />

    <!-- ErrorState, not frappe-ui's ErrorMessage: that renders the raw string
         a fetch rejects with, so a dropped connection put the literal words
         "Failed to fetch" on an admin's screen with nothing to do about it. -->
    <ErrorState
      v-else-if="grid.error"
      class="flex-1"
      :error="grid.error"
      :title="__('Could not load the sales targets')"
      :retry="grid.reload"
    />

    <div
      v-else-if="!rows.length"
      class="flex flex-1 flex-col items-center justify-center gap-1 text-center"
    >
      <LucideTarget class="size-7 text-ink-gray-4" />
      <div class="text-base text-ink-gray-6">
        {{ __('No sales users yet') }}
      </div>
      <div class="text-sm text-ink-gray-5">
        {{ __('Invite a rep, then set their monthly target here.') }}
      </div>
    </div>

    <div v-else class="min-h-0 flex-1 overflow-auto">
      <table class="w-full border-separate border-spacing-0 text-base">
        <thead>
          <tr>
            <th
              class="sticky left-0 top-0 z-20 border-b border-outline-gray-1 bg-surface-white px-3 py-2 text-left text-xs font-medium uppercase tracking-wider text-ink-gray-5"
            >
              {{ __('Rep') }}
            </th>
            <th
              v-for="(month, i) in grid.data.months"
              :key="month"
              class="sticky top-0 z-10 border-b border-outline-gray-1 bg-surface-white px-1 py-2 text-right text-xs font-medium uppercase tracking-wider text-ink-gray-5"
            >
              {{ monthLabels[i] }}
            </th>
            <th
              class="sticky right-0 top-0 z-20 border-b border-l border-outline-gray-1 bg-surface-white px-3 py-2 text-right text-xs font-medium uppercase tracking-wider text-ink-gray-5"
            >
              {{ __('Year') }}
            </th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="row in rows" :key="row.user" class="group">
            <td
              class="sticky left-0 z-10 border-b border-outline-gray-1 bg-surface-white px-3 py-1.5"
            >
              <div class="flex items-center gap-2">
                <span class="truncate text-ink-gray-8">{{
                  row.full_name
                }}</span>
                <Button
                  v-if="editable"
                  class="opacity-0 transition group-hover:opacity-100"
                  variant="ghost"
                  size="sm"
                  :label="__('Fill year')"
                  :title="__('Repeat January across every month')"
                  @click="copyForward(row)"
                />
              </div>
            </td>
            <td
              v-for="month in grid.data.months"
              :key="month"
              class="border-b border-outline-gray-1 px-0.5 py-1"
            >
              <input
                v-if="editable"
                :value="displayValue(row, month)"
                class="w-full rounded-4 border border-transparent bg-transparent px-1.5 py-1 text-right text-sm tabular-nums text-ink-gray-8 transition placeholder:text-ink-gray-4 hover:border-outline-gray-2 focus:border-outline-gray-3 focus:bg-surface-white focus:outline-none focus:ring-2 focus:ring-outline-gray-3"
                inputmode="decimal"
                placeholder="—"
                :aria-label="`${row.full_name} ${month}`"
                :title="exactTitle(row.quota?.[month])"
                @focus="onFocus($event, row, month)"
                @blur="onBlur($event, row, month)"
                @keydown.enter="$event.target.blur()"
              />
              <div
                v-else
                class="px-1.5 py-1 text-right text-sm tabular-nums text-ink-gray-7"
                :title="exactTitle(row.quota?.[month])"
              >
                {{ displayValue(row, month) || '—' }}
              </div>
            </td>
            <td
              class="sticky right-0 z-10 border-b border-l border-outline-gray-1 bg-surface-white px-3 py-1.5 text-right text-sm font-medium tabular-nums text-ink-gray-8"
            >
              {{ exactMoney(rowTotal(row)) }}
            </td>
          </tr>
          <tr>
            <td
              class="sticky left-0 z-10 bg-surface-white px-3 py-2 text-sm font-medium text-ink-gray-6"
            >
              {{ __('Team') }}
            </td>
            <td
              v-for="month in grid.data.months"
              :key="month"
              class="px-1.5 py-2 text-right text-sm tabular-nums text-ink-gray-6"
              :title="exactTitle(columnTotal(month))"
            >
              {{ money(columnTotal(month)) }}
            </td>
            <td
              class="sticky right-0 z-10 border-l border-outline-gray-1 bg-surface-white px-3 py-2 text-right text-sm font-semibold tabular-nums text-ink-gray-8"
            >
              {{ exactMoney(grandTotal) }}
            </td>
          </tr>
        </tbody>
      </table>
    </div>

    <p v-if="grid.data" class="shrink-0 text-p-xs text-ink-gray-5">
      {{
        __('Amounts are in {0}. Deal values are converted before comparison.', [
          grid.data.currency,
        ])
      }}
    </p>
  </div>
</template>

<script setup>
import LucideTarget from '~icons/lucide/target'
import { usersStore } from '@/stores/users'
import { Button, call, createResource, toast } from 'frappe-ui'
import ErrorState from '@/components/ui/ErrorState.vue'
import SkeletonTable from '@/components/ui/SkeletonTable.vue'
import { computed, ref, watch } from 'vue'
import { formatCell } from '@/utils/reportExport'
import { quiet } from '@/utils/quiet'

const { isManager } = usersStore()

const year = ref(new Date().getFullYear())
const editable = computed(() => isManager())

const grid = createResource({
  url: 'crm.api.quota.get_quota_grid',
  makeParams: () => ({ year: year.value }),
  auto: true,
})

watch(year, () => quiet(grid.reload()))

const rows = computed(() => grid.data?.rows || [])

const monthLabels = computed(() =>
  (grid.data?.months || []).map((m) =>
    new Date(`${m}T00:00:00`).toLocaleDateString(undefined, { month: 'short' }),
  ),
)

const compact = new Intl.NumberFormat(undefined, {
  notation: 'compact',
  maximumFractionDigits: 1,
})

/* Narrow cells only. `!value` also caught a deliberate zero and drew it as an
   em dash, so a rep whose target for a month really is nothing was
   indistinguishable from one whose target was never set. */
function money(value) {
  if (value === null || value === undefined || value === '') return '—'
  return compact.format(value)
}

/* The two sticky total columns have room for the real figure, and these are the
   numbers a manager reads off the page and repeats. 249,900 and 250,400 both
   compact to "250K", which is a difference of five hundred disappearing from a
   sales target. Currency included, matching what the CSV export writes — the
   two surfaces used to disagree about the same cell. */
function exactMoney(value) {
  return formatCell(value, 'currency', grid.data?.currency || '')
}

/* Every compacted figure carries its exact value as a tooltip, so reading one
   back no longer requires clicking into the input. */
function exactTitle(value) {
  if (value === null || value === undefined || value === '') return ''
  return exactMoney(value)
}

function displayValue(row, month) {
  const amount = row.quota?.[month]
  // Compact, like the column totals. Twelve months across a settings dialog
  // leaves each cell around 40px, and "250,000" clips to "250,0" there -- a
  // target you cannot read back. `onFocus` swaps in the exact digits and the
  // cell title carries them too, so the full number is never more than a hover
  // away.
  return amount === null || amount === undefined ? '' : compact.format(amount)
}

function rowTotal(row) {
  return Object.values(row.quota || {}).reduce((sum, v) => sum + (v || 0), 0)
}

function columnTotal(month) {
  return rows.value.reduce((sum, row) => sum + (row.quota?.[month] || 0), 0)
}

const grandTotal = computed(() =>
  rows.value.reduce((sum, row) => sum + rowTotal(row), 0),
)

function onFocus(event, row, month) {
  // digits only while editing — grouping separators are for reading, not typing
  event.target.value = row.quota?.[month] || ''
  event.target.select()
}

async function onBlur(event, row, month) {
  const raw = event.target.value.replace(/[^\d.-]/g, '')
  const amount = raw === '' ? 0 : Number(raw)
  const previous = row.quota?.[month] || 0

  if (Number.isNaN(amount) || amount < 0) {
    event.target.value = displayValue(row, month)
    toast.error(__('Enter a number of {0} or more.', [0]))
    return
  }
  if (amount === previous) {
    event.target.value = displayValue(row, month)
    return
  }

  // paint the new value first so the grid totals move with the keystroke, then
  // reconcile with what the server actually stored
  row.quota = { ...row.quota, [month]: amount }
  try {
    await call('crm.api.quota.set_quota', {
      user: row.user,
      period_start: month,
      amount,
    })
  } catch (error) {
    row.quota = { ...row.quota, [month]: previous }
    toast.error(error.messages?.[0] || __('Could not save that target'))
  }
  event.target.value = displayValue(row, month)
}

async function copyForward(row) {
  const january = grid.data.months[0]
  if (!row.quota?.[january]) {
    toast.error(__('Set January first, then fill the year from it.'))
    return
  }
  try {
    await call('crm.api.quota.copy_quota_forward', {
      user: row.user,
      from_period: january,
      months: 11,
    })
    await grid.reload()
    toast.success(__('Filled {0} from January', [year.value]))
  } catch (error) {
    toast.error(error.messages?.[0] || __('Could not fill the year'))
  }
}
</script>
