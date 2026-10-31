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
      v-if="!shown && !grid.error"
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
      <!-- min-w-full, not w-full: with twelve months plus two sticky columns
           a settings pane is narrower than the content. w-full made the table
           fit anyway, so month cells shrank below their figures ("1.5M" read
           "1.5N") and the sticky Year column painted over November. The
           container scrolls; the table keeps its width. The sticky cells sit
           on bg-surface-elevation-2, the pane's own surface: bg-surface-white
           is transparent in the dark theme, so the months scrolling underneath
           the Year column showed through it. -->
      <table class="min-w-full border-separate border-spacing-0 text-base">
        <thead>
          <tr>
            <th
              class="sticky left-0 top-0 z-20 border-b border-outline-gray-1 bg-surface-elevation-2 px-3 py-2 text-left text-xs font-medium uppercase tracking-wider text-ink-gray-5"
            >
              {{ __('Rep') }}
            </th>
            <th
              v-for="(month, i) in shown.months"
              :key="month"
              class="sticky top-0 z-10 min-w-[4rem] border-b border-outline-gray-1 bg-surface-elevation-2 px-1 py-2 text-right text-xs font-medium uppercase tracking-wider text-ink-gray-5"
            >
              {{ monthLabels[i] }}
            </th>
            <th
              class="sticky right-0 top-0 z-20 whitespace-nowrap border-b border-l border-outline-gray-1 bg-surface-elevation-2 px-3 py-2 text-right text-xs font-medium uppercase tracking-wider text-ink-gray-5"
            >
              {{ __('Year') }}
            </th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="row in rows" :key="row.user" class="group">
            <td
              class="sticky left-0 z-10 whitespace-nowrap border-b border-outline-gray-1 bg-surface-elevation-2 px-3 py-1.5"
            >
              <div class="flex items-center gap-2">
                <span
                  class="truncate text-ink-gray-8"
                  :title="
                    editable && !canEdit(row)
                      ? __('Your own target is set by an administrator')
                      : ''
                  "
                  >{{ row.full_name }}</span
                >
                <Button
                  v-if="canEdit(row)"
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
              v-for="month in shown.months"
              :key="month"
              class="min-w-[4rem] border-b border-outline-gray-1 px-0.5 py-1"
            >
              <input
                v-if="canEdit(row)"
                :value="cellValue(row, month)"
                class="w-full rounded-[var(--v-radius-control)] border border-transparent bg-transparent px-1.5 py-1 text-right text-sm tabular-nums text-ink-gray-8 transition placeholder:text-ink-gray-4 hover:border-outline-gray-2 focus:border-outline-gray-3 focus:bg-surface-white focus:outline-none focus:ring-2 focus:ring-outline-gray-3"
                inputmode="decimal"
                placeholder="—"
                :aria-label="`${row.full_name} ${month}`"
                :title="exactTitle(row.quota?.[month])"
                @focus="onFocus($event, row, month)"
                @input="onInput"
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
              class="sticky right-0 z-10 whitespace-nowrap border-b border-l border-outline-gray-1 bg-surface-elevation-2 px-3 py-1.5 text-right text-sm font-medium tabular-nums text-ink-gray-8"
            >
              {{ exactMoney(rowTotal(row)) }}
            </td>
          </tr>
          <tr>
            <td
              class="sticky left-0 z-10 bg-surface-elevation-2 px-3 py-2 text-sm font-medium text-ink-gray-6"
            >
              {{ __('Team') }}
            </td>
            <td
              v-for="month in shown.months"
              :key="month"
              class="min-w-[4rem] px-1.5 py-2 text-right text-sm tabular-nums text-ink-gray-6"
              :title="exactTitle(columnTotal(month))"
            >
              {{ money(columnTotal(month)) }}
            </td>
            <td
              class="sticky right-0 z-10 whitespace-nowrap border-l border-outline-gray-1 bg-surface-elevation-2 px-3 py-2 text-right text-sm font-semibold tabular-nums text-ink-gray-8"
            >
              {{ exactMoney(grandTotal) }}
            </td>
          </tr>
        </tbody>
      </table>
    </div>

    <p v-if="shown" class="shrink-0 text-p-xs text-ink-gray-5">
      {{
        __('Amounts are in {0}. Deal values are converted before comparison.', [
          shown.currency,
        ])
      }}
    </p>
  </div>
</template>

<script setup>
import { PhTarget as LucideTarget } from '@phosphor-icons/vue'
import { usersStore } from '@/stores/users'
import {
  Button,
  call,
  createResource,
  frappeRequest,
  getConfig,
  toast,
} from 'frappe-ui'
import ErrorState from '@/components/ui/ErrorState.vue'
import SkeletonTable from '@/components/ui/SkeletonTable.vue'
import { computed, ref, watch } from 'vue'
import { parseAmount } from '@/utils/amountInput'
import { formatCell } from '@/utils/reportExport'
import { quiet } from '@/utils/quiet'

const { isManager, isAdmin, getUser } = usersStore()

const year = ref(new Date().getFullYear())
const editable = computed(() => isManager())

const isOwnRow = (row) => row.user === getUser().name

/* A manager does not set their own target -- crm.api.quota._not_the_caller
   refuses it to anyone but an administrator -- so their row is read-only here
   rather than editable and then refused. */
function canEdit(row) {
  return editable.value && (!isOwnRow(row) || isAdmin())
}

const grid = createResource({
  url: 'crm.api.quota.get_quota_grid',
  makeParams: () => ({ year: year.value }),
  /* Two quick clicks on a year arrow put two requests in flight, and whichever
     landed last became the grid: the header could read 2028 over 2027's
     targets, and an edit made there wrote to 2027. An answer -- or a failure --
     for any year but the one in the header is dropped as an abort, which
     createResource treats as a deliberate stop and leaves its data alone for. */
  resourceFetcher: (options) => {
    const send = getConfig('resourceFetcher') || frappeRequest
    const superseded = () => Number(options.params?.year) !== year.value
    const dropped = () =>
      Object.assign(new Error('Superseded by another year'), {
        name: 'AbortError',
      })
    return send(options).then(
      (data) => {
        if (superseded()) throw dropped()
        return data
      },
      (error) => {
        throw superseded() ? dropped() : error
      },
    )
  },
  auto: true,
})

watch(year, () => quiet(grid.reload()))

// The grid for the year in the header, and nothing while that year loads: the
// previous year's data must not be shown, or edited, under the new heading.
const shown = computed(() =>
  Number(grid.data?.year) === year.value ? grid.data : null,
)

const rows = computed(() => shown.value?.rows || [])

const monthLabels = computed(() =>
  (shown.value?.months || []).map((m) =>
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

/* The cell being edited and the text in it. Bound through :value, so a
   re-render while it is focused -- a save elsewhere rolling back, a total
   moving -- puts back what is being typed. It used to live only in the DOM, and
   every re-render patched the compact label ("100K") over it, which the blur
   then saved as 100. */
const editing = ref(null)

function cellValue(row, month) {
  const cell = editing.value
  return cell?.user === row.user && cell.month === month
    ? cell.text
    : displayValue(row, month)
}

function onFocus(event, row, month) {
  // digits only while editing — grouping separators are for reading, not typing
  editing.value = { user: row.user, month, text: `${row.quota?.[month] || ''}` }
  event.target.value = editing.value.text
  event.target.select()
}

function onInput(event) {
  if (editing.value) editing.value.text = event.target.value
}

async function onBlur(event, row, month) {
  const amount = parseAmount(event.target.value)
  const previous = row.quota?.[month] || 0
  // the cell shows its compact label again from the next render
  editing.value = null

  if (Number.isNaN(amount) || amount < 0) {
    toast.error(__('Enter a number of {0} or more.', [0]))
    return
  }
  if (amount === previous) return

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
}

async function copyForward(row) {
  const january = shown.value.months[0]
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
