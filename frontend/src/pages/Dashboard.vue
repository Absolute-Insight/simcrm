<template>
  <div class="flex flex-col h-full overflow-hidden">
    <LayoutHeader>
      <template #left-header>
        <ViewBreadcrumbs routeName="Dashboard" />
      </template>
      <template #right-header>
        <Button
          v-if="!editing"
          :label="__('Refresh')"
          :iconLeft="LucideRefreshCcw"
          @click="reloadAll"
        />
        <!-- Reading the dashboard works at any width; rearranging it does not.
             Editing is a drag-and-drop grid sized in 20 columns, and below
             WIDE_GRID_BREAKPOINT_PX the panels are stacked instead -- there is
             nothing to drag, and dragging is how the stored layout is written.
             Gated on that breakpoint rather than the phone one: at 800px the
             button used to appear and do nothing visible, which is the broken
             mode this comment already warned about. -->
        <Button
          v-if="!editing && showChartGrid && !isNarrowGrid"
          :label="__('Edit')"
          :iconLeft="LucidePenLine"
          @click="enableEditing"
        />
        <Button
          v-if="editing"
          :label="__('Chart')"
          iconLeft="lucide-plus"
          @click="showAddChartModal = true"
        />
        <Button
          v-if="editing && isAdmin()"
          :label="__('Reset to Default')"
          :iconLeft="LucideUndo2"
          @click="resetToDefault"
        />
        <Button v-if="editing" :label="__('Cancel')" @click="cancel" />
        <Button
          v-if="editing"
          variant="solid"
          :label="__('Save')"
          :disabled="!dirty"
          :loading="saveDashboard.loading"
          @click="save"
        />
      </template>
    </LayoutHeader>

    <div class="p-5 pb-2 flex flex-wrap items-center gap-4">
      <Dropdown
        v-if="!showDatePicker"
        v-model="preset"
        :options="options"
        class="form-control"
        :placeholder="__('Select Range')"
        :button="{
          label: presetLabel,
          class:
            '!w-full justify-start [&>span]:mr-auto [&>svg]:text-ink-gray-5',
          variant: 'outline',
          iconRight: 'chevron-down',
          iconLeft: 'calendar',
        }"
      />
      <DateRangePicker
        v-else
        ref="datePickerRef"
        class="!w-48"
        :value="parseDateRange(filters.period)"
        variant="outline"
        :placeholder="__('Period')"
        :formatter="formatRange"
        @change="
          (v) =>
            updateFilter('period', v, () => {
              showDatePicker = false
              if (!v) {
                filters.period = getLastXDays()
                preset = 'Last 30 Days'
              } else {
                preset = formatter(v)
              }
            })
        "
      >
        <template #prefix>
          <LucideCalendar class="size-4 text-ink-gray-5 mr-2" />
        </template>
      </DateRangePicker>
      <Link
        v-if="isAdmin() || isManager()"
        class="form-control w-48"
        variant="outline"
        :value="filters.user && getUser(filters.user).full_name"
        doctype="User"
        :filters="{
          name: ['in', users.data.crmUsers?.map((u) => u.name)],
          ignore_user_type: 1,
        }"
        :placeholder="__('Sales User')"
        :hideMe="true"
        @change="(v) => updateFilter('user', v)"
      >
        <template #prefix>
          <UserAvatar
            v-if="filters.user"
            class="mr-2"
            :user="filters.user"
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
      <!-- Three charts cannot slice by territory (quotas and rep plans are per
           rep, forecast snapshots store a total). They stay on screen and say so
           rather than disappearing or, worse, showing global numbers under a
           heading naming one region. -->
      <Link
        v-if="isAdmin() || isManager()"
        class="form-control w-48"
        variant="outline"
        :value="filters.territory"
        doctype="CRM Territory"
        :placeholder="__('All territories')"
        @change="(v) => updateFilter('territory', v)"
      >
        <template #prefix>
          <LucideMapPin class="mr-2 size-4 text-ink-gray-5" />
        </template>
      </Link>
    </div>

    <div class="w-full flex-1 overflow-y-auto px-5 pb-6">
      <!-- The headline numbers. Each one clicks through to the records behind
           it, which is the whole difference between a dashboard you read and a
           dashboard you work from. -->
      <div class="grid grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-4">
        <StatTile
          v-for="tile in tiles"
          :key="tile.name"
          :label="tile.label"
          :value="tile.resource.data?.value"
          :prefix="tile.resource.data?.prefix || ''"
          :suffix="tile.resource.data?.suffix || ''"
          :tooltip="tile.resource.data?.tooltip || ''"
          :delta="tile.resource.data?.delta ?? 0"
          :delta-suffix="tile.resource.data?.deltaSuffix || ''"
          :negative-is-better="!!tile.resource.data?.negativeIsBetter"
          :loading="tile.resource.loading"
          :error="tile.resource.error"
          :retry="() => tile.resource.reload()"
          :drilldown-label="drilldownLabelFor(tile)"
          :unfiltered-note="unfilteredNoteFor(tile.resource.data)"
          @drill="drillInto(tile.name, drilldownContext)"
        />
      </div>

      <div class="mt-4 grid grid-cols-1 gap-3 xl:grid-cols-2">
        <PanelCard
          v-for="(panel, panelIndex) in visiblePanels"
          :key="panel.id"
          :title="panel.title"
          :subtitle="panel.subtitle"
          :loading="panel.loading.value"
          :error="panel.error.value"
          :retry="panel.retry"
          :empty="panel.empty.value"
          :empty-title="panel.emptyTitle"
          :empty-description="panel.emptyDescription"
          :empty-icon="panel.emptyIcon"
        >
          <!-- Arrows rather than drag: the panels are a responsive grid that
               becomes one column on a phone, so a drag target would move under
               the pointer between breakpoints. Two buttons work the same at
               every width and are reachable from the keyboard without a
               drag-and-drop fallback. Labelled per panel, since "Move up" on
               its own says nothing when a screen reader lists all of them. -->
          <template #actions>
            <Button
              variant="ghost"
              icon="lucide-chevron-up"
              size="sm"
              :aria-label="__('Move {0} earlier', [panel.title])"
              :disabled="panelIndex === 0"
              class="opacity-0 transition focus-visible:opacity-100 group-hover/panel:opacity-100"
              @click="reorderPanel(panel.id, -1)"
            />
            <Button
              variant="ghost"
              icon="lucide-chevron-down"
              size="sm"
              :aria-label="__('Move {0} later', [panel.title])"
              :disabled="panelIndex === visiblePanels.length - 1"
              class="opacity-0 transition focus-visible:opacity-100 group-hover/panel:opacity-100"
              @click="reorderPanel(panel.id, 1)"
            />
            <Button
              variant="ghost"
              :label="__('Hide')"
              size="sm"
              class="opacity-0 transition focus-visible:opacity-100 group-hover/panel:opacity-100"
              @click="hidePanel(panel.id)"
            />
          </template>

          <!-- Deals that need attention, with the reason. A score with no
               "why" is something a rep learns to ignore. -->
          <ul v-if="panel.id === 'attention'" class="flex flex-col gap-2">
            <li v-for="row in riskRows" :key="row.key">
              <button
                type="button"
                class="flex w-full items-start justify-between gap-3 rounded-5 px-2 py-2 text-left transition hover:bg-surface-gray-2"
                @click="openRecord(row)"
              >
                <span class="flex min-w-0 flex-col">
                  <span class="truncate text-base text-ink-gray-8">
                    {{ recordLabel(row) }}
                  </span>
                  <span class="truncate text-sm text-ink-gray-5">
                    {{ riskReason(row) }}
                  </span>
                </span>
                <Badge
                  :label="urgencyBand(row.score)?.label || ''"
                  variant="subtle"
                  :theme="row.score >= 70 ? 'red' : 'amber'"
                />
              </button>
            </li>
          </ul>

          <!-- What the rep planned for today, against what is done. -->
          <div v-else-if="panel.id === 'today'" class="flex flex-col gap-3">
            <div class="flex items-baseline gap-2">
              <span class="font-display text-3xl-medium text-ink-gray-9">
                {{ todayBreakdown.done }}
              </span>
              <span class="text-base text-ink-gray-5">
                {{ __('of {0} done today', [todayBreakdown.planned]) }}
              </span>
            </div>
            <div
              class="h-1.5 w-full overflow-hidden rounded-full bg-surface-gray-3"
              role="img"
              :aria-label="__('{0}% of today\'s plan done', [todayAdherence])"
            >
              <div
                class="h-full rounded-full transition-[width]"
                :style="{
                  width: `${todayAdherence}%`,
                  background: 'var(--brand-gradient)',
                }"
              />
            </div>
            <ul class="flex flex-col gap-1">
              <li
                v-for="item in todayItems"
                :key="item.name"
                class="flex items-center justify-between gap-2 text-base"
              >
                <span class="truncate text-ink-gray-7">
                  {{ item.note || __(item.activity_type) }}
                </span>
                <span class="shrink-0 text-sm text-ink-gray-5">
                  {{ __(item.status) }}
                </span>
              </li>
            </ul>
            <Button
              :label="__('Open the planner')"
              variant="subtle"
              @click="router.push({ name: 'Planner' })"
            />
          </div>

          <!-- Manager panels are report rows, rendered as a compact table so
               the number in the panel and the number in the report are the
               same number. -->
          <table v-else class="w-full text-base">
            <tbody>
              <tr
                v-for="(row, i) in panel.rows.value"
                :key="i"
                class="border-b border-outline-gray-1 last:border-b-0"
              >
                <td class="py-1.5 pr-2 text-ink-gray-7">
                  {{ repName(row.user) }}
                </td>
                <td
                  class="py-1.5 text-right tabular-nums text-ink-gray-8"
                  :class="panel.tone?.(row)"
                >
                  {{ panel.cell(row) }}
                </td>
              </tr>
            </tbody>
          </table>
        </PanelCard>
      </div>

      <div v-if="hiddenPanels.length" class="mt-3 flex items-center gap-2">
        <span class="text-sm text-ink-gray-5">{{ __('Hidden:') }}</span>
        <Button
          v-for="panel in hiddenPanels"
          :key="panel.id"
          size="sm"
          variant="outline"
          :label="panel.title"
          @click="showPanel(panel.id)"
        />
      </div>

      <template v-if="showChartGrid">
        <h2 class="v-title-sm mt-6 text-ink-gray-8">{{ __('Charts') }}</h2>
        <SkeletonTable v-if="dashboardItems.loading" :rows="4" :columns="2" />
        <ErrorState
          v-else-if="dashboardItems.error"
          compact
          :error="dashboardItems.error"
          :retry="() => dashboardItems.reload()"
        />
        <DashboardGrid
          v-else-if="dashboardItems.data"
          v-model="dashboardItems.data"
          class="pt-1"
          :editing="editing"
        />
      </template>
    </div>
  </div>
  <AddChartModal
    v-if="showAddChartModal"
    v-model="showAddChartModal"
    v-model:items="dashboardItems.data"
  />
</template>

<script setup lang="ts">
/**
 * The dashboard is role-aware on purpose.
 *
 * A rep opening this page wants "what needs me today"; a manager wants "how is
 * the team tracking". Those are different pages, so they are different panel
 * sets, chosen by role rather than by a widget picker the rep would have to
 * assemble themselves.
 *
 * The customisable chart grid is kept for managers rather than replaced. It is
 * the only place charts live, managers already have layouts saved in it, and
 * "opinionated defaults with light customisation" means the curated panels come
 * first and the grid stays underneath — not that the grid disappears.
 *
 * Panel show/hide is stored per user in localStorage. It is a display
 * preference for a fixed catalogue of panels, so it does not warrant a doctype;
 * `applyPanelPreference` is deliberately a filter over the catalogue, so a
 * panel added in a later release appears for everyone instead of staying
 * invisible behind a stale saved order.
 */
import AddChartModal from '@/components/Dashboard/AddChartModal.vue'
import LucideRefreshCcw from '~icons/lucide/refresh-ccw'
import LucideUndo2 from '~icons/lucide/undo-2'
import LucidePenLine from '~icons/lucide/pen-line'
import DashboardGrid from '@/components/Dashboard/DashboardGrid.vue'
import PanelCard from '@/components/Dashboard/PanelCard.vue'
import StatTile from '@/components/Dashboard/StatTile.vue'
import { useDrilldown } from '@/components/Dashboard/drilldown'
import ErrorState from '@/components/ui/ErrorState.vue'
import SkeletonTable from '@/components/ui/SkeletonTable.vue'
import UserAvatar from '@/components/UserAvatar.vue'
import ViewBreadcrumbs from '@/components/ViewBreadcrumbs.vue'
import LayoutHeader from '@/components/LayoutHeader.vue'
import Link from '@/components/Controls/Link.vue'
import { usersStore } from '@/stores/users'
import { isNarrowGrid } from '@/composables/settings'
import { copy } from '@/utils'
import { describeError } from '@/utils/describeError'
import {
  adherencePercent,
  applyPanelPreference,
  groupRisksByRecord,
  mondayOf,
  planBreakdown,
  reorderVisiblePanel,
  riskReason,
  toISODate,
} from '@/utils/dashboardHome'
import * as suggestionsModule from '@/stores/suggestions'
import { displayReferenceLabel, urgencyBand } from '@/utils/suggestions'
import {
  getLastXDays,
  formatter,
  formatRange,
  parseDateRange,
} from '@/utils/dashboard'
import {
  usePageMeta,
  createResource,
  Badge,
  DateRangePicker,
  Dropdown,
  Tooltip,
  toast,
} from 'frappe-ui'
import { ref, reactive, computed, provide } from 'vue'
import { useRouter } from 'vue-router'

const { users, getUser, isManager, isAdmin } = usersStore()
const router = useRouter()
const { drillInto, canDrillInto } = useDrilldown()

const editing = ref(false)
const showDatePicker = ref(false)
const datePickerRef = ref(null)
const preset = ref('Last 30 Days')
const showAddChartModal = ref(false)

/* `__(preset)` looked like translation but could never work: the extractor
   only sees literals, so "Last 30 Days" was never in the catalogue, and the
   button stayed English beside a dropdown whose items translate correctly.
   Rebuilt from the parts, the way Reports.vue already does it. A custom range
   falls through as-is — it is a formatted date, already localised, and not a
   phrase anyone translates. */
const presetLabel = computed(() => {
  const value = preset.value || ''
  const lastNDays = /^Last (\d+) Days$/.exec(value)
  if (lastNDays) return __('Last {0} Days', [lastNDays[1]])
  if (value === 'Custom Range') return __('Custom Range')
  return value
})

const filters = reactive({
  period: getLastXDays(),
  user: null,
  territory: null,
})

const fromDate = computed(() => parseDateRange(filters.period)[0] || null)
const toDate = computed(() => parseDateRange(filters.period)[1] || null)

const isTeamView = computed(() => isAdmin() || isManager())
const showChartGrid = computed(() => isTeamView.value)

// A manager reading one rep's dashboard is reading that rep's numbers; with no
// rep chosen they are reading the team's. A rep only ever reads their own, and
// the server pins that regardless of what is sent.
const scopeUser = computed(() => filters.user || null)
const scopeTerritory = computed(() => filters.territory || null)

function chartResource(name: string) {
  return createResource({
    url: 'crm.api.dashboard.get_chart',
    makeParams: () => ({
      name,
      type: 'number_chart',
      from_date: fromDate.value,
      to_date: toDate.value,
      user: scopeUser.value,
      territory: scopeTerritory.value,
    }),
    auto: true,
  })
}

const TILE_CATALOGUE = [
  { name: 'total_leads', label: __('Leads'), teamOnly: true },
  { name: 'ongoing_deals', label: __('Open deals'), teamOnly: false },
  { name: 'won_deals', label: __('Won deals'), teamOnly: false },
  { name: 'plan_adherence', label: __('Plan adherence'), teamOnly: false },
  { name: 'quota_attainment', label: __('Quota attainment'), teamOnly: false },
]

const tileResources = Object.fromEntries(
  TILE_CATALOGUE.map((t) => [t.name, chartResource(t.name)]),
)

const tiles = computed(() =>
  TILE_CATALOGUE.filter((t) => isTeamView.value || !t.teamOnly).map((t) => ({
    ...t,
    resource: tileResources[t.name],
  })),
)

const drilldownContext = computed(() => ({
  user: scopeUser.value,
  fromDate: fromDate.value,
  toDate: toDate.value,
}))

/* The server says which charts its territory filter actually reached. The ones
   it did not have to say so: a tile silently answering for the whole company,
   sitting beside tiles that are scoped to one region, is the "two answers to
   one question" failure with no way to tell which is which. */
function unfilteredNoteFor(
  data: { territory?: string; territory_filtered?: boolean } | undefined,
) {
  if (!data?.territory || data.territory_filtered) return ''
  return __('Not filtered by {0}', [data.territory])
}

function drilldownLabelFor(tile: { name: string; label: string }) {
  return canDrillInto(tile.name, drilldownContext.value)
    ? __('Show the records behind {0}', [tile.label])
    : ''
}

// The shell inbox already loads and label-resolves these rows; reusing its
// store means the dashboard shows the same records under the same names, and
// costs no second request.
const { suggestions, referenceLabels } = suggestionsModule

const riskRows = computed(() =>
  groupRisksByRecord(suggestions.data || [], { limit: 6 }),
)

function recordLabel(row: { doctype: string; docname: string }) {
  // display form: three deals at one org must not read as one deal three times
  return (
    displayReferenceLabel(referenceLabels, row.doctype, row.docname) ||
    row.docname
  )
}

function openRecord(row: { doctype: string; docname: string }) {
  const name = row.doctype === 'CRM Lead' ? 'Lead' : 'Deal'
  const key = row.doctype === 'CRM Lead' ? 'leadId' : 'dealId'
  router.push({ name, params: { [key]: row.docname } })
}

const today = computed(() => toISODate(new Date()))

const myPlan = createResource({
  url: 'crm.api.rep_plan.get_plan',
  makeParams: () => ({ week_start: mondayOf(new Date()) }),
  auto: true,
})

const todayItems = computed(() =>
  (myPlan.data?.items || []).filter(
    (i) => toISODate(i.planned_date) === today.value,
  ),
)
const todayBreakdown = computed(() =>
  planBreakdown(myPlan.data?.items || [], { on: today.value }),
)
const todayAdherence = computed(() => adherencePercent(todayBreakdown.value))

function reportResource(name: string) {
  return createResource({
    url: 'crm.api.reports.get_report',
    makeParams: () => ({
      name,
      from_date: fromDate.value,
      to_date: toDate.value,
      user: scopeUser.value,
      territory: scopeTerritory.value,
    }),
    auto: isTeamView.value,
  })
}

const teamAdherence = reportResource('plan_adherence_by_rep')
const teamQuota = reportResource('quota_attainment_by_rep')

function repName(user: string) {
  return getUser(user)?.full_name || user
}

const PANEL_CATALOGUE = computed(() => {
  const panels = [
    {
      id: 'attention',
      title: __('Needs your attention'),
      subtitle: __('Ranked by urgency, with the reason'),
      loading: computed(() => suggestions.loading),
      error: computed(() => suggestions.error),
      retry: () => suggestions.reload(),
      empty: computed(() => !suggestions.loading && !riskRows.value.length),
      emptyTitle: __('Nothing needs you right now'),
      emptyDescription: __('New signals appear here as they are detected.'),
      rows: computed(() => riskRows.value),
      cell: () => '',
    },
  ]

  if (!isTeamView.value) {
    panels.push({
      id: 'today',
      title: __('Today'),
      subtitle: __('Your plan against what is done'),
      loading: computed(() => myPlan.loading),
      error: computed(() => myPlan.error),
      retry: () => myPlan.reload(),
      empty: computed(() => !myPlan.loading && !todayBreakdown.value.planned),
      emptyTitle: __('Nothing planned for today'),
      emptyDescription: __('Plan your week to see it here.'),
      rows: computed(() => todayItems.value),
      cell: () => '',
    })
    return panels
  }

  panels.push(
    {
      id: 'adherence',
      title: __('Plan adherence by rep'),
      subtitle: __('Planned activities due in the period, and how many landed'),
      loading: computed(() => teamAdherence.loading),
      error: computed(() => teamAdherence.error),
      retry: () => teamAdherence.reload(),
      empty: computed(
        () =>
          !teamAdherence.loading && !(teamAdherence.data?.rows || []).length,
      ),
      emptyTitle: __('No plans in this period'),
      emptyDescription: __('Adherence appears once reps plan their weeks.'),
      rows: computed(() => teamAdherence.data?.rows || []),
      cell: (row) => `${row.adherence}%`,
      tone: (row) => (row.adherence < 60 ? 'text-ink-orange-9' : ''),
    },
    {
      id: 'quota',
      title: __('Quota attainment'),
      subtitle: __('Closed-won against target, per rep'),
      loading: computed(() => teamQuota.loading),
      error: computed(() => teamQuota.error),
      retry: () => teamQuota.reload(),
      empty: computed(
        () => !teamQuota.loading && !(teamQuota.data?.rows || []).length,
      ),
      emptyTitle: __('No targets set'),
      emptyDescription: __('Set monthly targets in Settings → Sales Targets.'),
      rows: computed(() => teamQuota.data?.rows || []),
      cell: (row) => `${row.attainment}%`,
      tone: (row) => (row.attainment < 80 ? 'text-ink-orange-9' : ''),
    },
  )
  return panels
})

const PREFERENCE_KEY = 'vectora:dashboard-panels'

function loadPreference() {
  try {
    return JSON.parse(localStorage.getItem(PREFERENCE_KEY) || '{}')
  } catch {
    return {}
  }
}

const preference = ref(loadPreference())

function savePreference() {
  try {
    localStorage.setItem(PREFERENCE_KEY, JSON.stringify(preference.value))
  } catch {
    /* storage disabled: the preference just does not survive the session */
  }
}

const visiblePanels = computed(() =>
  applyPanelPreference(PANEL_CATALOGUE.value, preference.value),
)

const hiddenPanels = computed(() => {
  const shown = new Set(visiblePanels.value.map((p) => p.id))
  return PANEL_CATALOGUE.value.filter((p) => !shown.has(p.id))
})

function hidePanel(id: string) {
  const hidden = new Set(preference.value.hidden || [])
  hidden.add(id)
  preference.value = { ...preference.value, hidden: [...hidden] }
  savePreference()
}

function showPanel(id: string) {
  const hidden = (preference.value.hidden || []).filter((h: string) => h !== id)
  preference.value = { ...preference.value, hidden }
  savePreference()
}

function reorderPanel(id: string, direction: number) {
  preference.value = {
    ...preference.value,
    order: reorderVisiblePanel(
      PANEL_CATALOGUE.value,
      preference.value,
      id,
      direction,
    ),
  }
  savePreference()
}

function updateFilter(key: string, value: unknown, callback?: () => void) {
  filters[key] = value
  callback?.()
  reloadAll()
}

function reloadAll() {
  dashboardItems.reload()
  Object.values(tileResources).forEach((r) => r.reload())
  suggestions.reload()
  if (isTeamView.value) {
    teamAdherence.reload()
    teamQuota.reload()
  } else {
    myPlan.reload()
  }
}

const options = computed(() => [
  {
    group: 'Presets',
    hideLabel: true,
    options: [7, 30, 60, 90].map((days) => ({
      label: __('Last {0} Days', [days]),
      onClick: () => {
        preset.value = `Last ${days} Days`
        filters.period = getLastXDays(days)
        reloadAll()
      },
    })),
  },
  {
    label: __('Custom Range'),
    onClick: () => {
      showDatePicker.value = true
      setTimeout(() => datePickerRef.value?.open(), 0)
      preset.value = 'Custom Range'
      filters.period = null // Reset period to allow custom date selection
    },
  },
])

const dashboardItems = createResource({
  url: 'crm.api.dashboard.get_dashboard',
  makeParams() {
    return {
      from_date: fromDate.value,
      to_date: toDate.value,
      user: filters.user,
      territory: scopeTerritory.value,
    }
  },
  auto: true,
})

const dirty = computed(() => {
  if (!editing.value) return false
  return JSON.stringify(dashboardItems.data) !== JSON.stringify(oldItems.value)
})

const oldItems = ref([])

provide('fromDate', fromDate)
provide('toDate', toDate)
provide('filters', filters)

function enableEditing() {
  editing.value = true
  oldItems.value = copy(dashboardItems.data)
}

function cancel() {
  editing.value = false
  dashboardItems.data = copy(oldItems.value)
}

// Without onError, frappe-ui rethrows: the spinner stops, the page stays in
// edit mode, and a permission or validation failure says nothing at all. The
// layout the manager just arranged is gone on the next reload with no clue why.
function reportFailure(error: unknown) {
  const described = describeError(error)
  toast.error(
    described.message || __('Something went wrong. Please try again.'),
  )
}

const saveDashboard = createResource({
  url: 'frappe.client.set_value',
  method: 'POST',
  onSuccess: () => {
    dashboardItems.reload()
    editing.value = false
  },
  onError: reportFailure,
})

function save() {
  const dashboardItemsCopy = copy(dashboardItems.data)

  dashboardItemsCopy.forEach((item: Record<string, unknown>) => {
    delete item.data
  })

  saveDashboard.submit({
    doctype: 'CRM Dashboard',
    name: 'Manager Dashboard',
    fieldname: 'layout',
    value: JSON.stringify(dashboardItemsCopy),
  })
}

function resetToDefault() {
  createResource({
    url: 'crm.api.dashboard.reset_to_default',
    auto: true,
    onSuccess: () => {
      dashboardItems.reload()
      editing.value = false
    },
    onError: reportFailure,
  })
}

usePageMeta(() => {
  return { title: __('Dashboard') }
})
</script>
