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
        v-model="preset"
        :options="options"
        class="form-control"
        :placeholder="__('Select Range')"
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
        ref="datePickerRef"
        class="!w-64"
        :modelValue="parseDateRange(filters.period)"
        variant="outline"
        :placeholder="__('Period')"
        format="D MMM YYYY"
        @change="onPeriodChange"
      >
        <template #prefix>
          <LucideCalendar class="size-4 text-ink-gray-5 mr-2" />
        </template>
      </DateRangePicker>
      <Select
        v-if="isAdmin() || isManager()"
        class="w-48"
        :modelValue="filters.user || ALL_REPS"
        :options="repFilterOptions"
        :aria-label="__('Rep')"
        @update:modelValue="
          (v) => updateFilter('user', v === ALL_REPS ? '' : v)
        "
      />
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

    <div class="v-lux-stage w-full flex-1 overflow-y-auto px-5 pb-6">
      <!-- The headline numbers. Each one clicks through to the records behind
           it, which is the whole difference between a dashboard you read and a
           dashboard you work from. -->
      <div
        class="grid grid-cols-1 gap-3 sm:grid-cols-2"
        :class="kpiTiles.length === 3 ? 'xl:grid-cols-3' : 'xl:grid-cols-4'"
      >
        <StatTile
          v-for="tile in kpiTiles"
          :key="tile.name"
          :label="tile.label"
          :accent="
            tile.name === 'deals_at_risk' &&
            (tile.resource.data?.value || 0) > 0
              ? 'danger'
              : ''
          "
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

      <!-- The hero: the trend everyone asks about first, at a size that
           answers before it is clicked. Beside it, the two percentages that
           are targets rather than counts, drawn as rings. -->
      <div class="mt-4 grid grid-cols-1 gap-3 xl:grid-cols-3">
        <div
          class="h-80 overflow-hidden rounded-6 xl:col-span-2"
          :class="
            heroTrend.loading ||
            heroTrend.error ||
            axisChartEmpty(heroTrend.data)
              ? 'v-glass'
              : ''
          "
        >
          <SkeletonTable v-if="heroTrend.loading" :rows="5" :columns="3" />
          <ErrorState
            v-else-if="heroTrend.error"
            compact
            :error="heroTrend.error"
            :retry="() => heroTrend.reload()"
          />
          <div
            v-else-if="axisChartEmpty(heroTrend.data)"
            class="relative h-full"
          >
            <EmptyState
              icon="lucide-line-chart"
              :title="__('Nothing here yet')"
              :description="
                __('Leads, deals and wins chart here as they are logged.')
              "
              top="15%"
              width="lg"
            />
          </div>
          <DashboardItem
            v-else-if="heroTrend.data"
            :index="0"
            :item="{ type: 'axis_chart', data: heroTrend.data }"
          />
        </div>
        <div class="flex flex-col gap-3">
          <RadialGauge
            v-for="tile in gaugeTiles"
            :key="tile.name"
            class="flex-1"
            :label="tile.label"
            :value="tile.resource.data?.value"
            :suffix="tile.resource.data?.suffix || '%'"
            :hint="tile.resource.data?.tooltip || ''"
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
      </div>

      <div class="mt-4 grid grid-cols-1 gap-3 xl:grid-cols-2">
        <PanelCard
          v-for="(panel, panelIndex) in visiblePanels"
          :key="panel.id"
          :class="panel.wide ? 'xl:col-span-2' : ''"
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
                  v-if="urgencyBand(row.score)"
                  :label="urgencyBand(row.score).label"
                  variant="subtle"
                  :theme="riskBadgeTheme(urgencyBand(row.score).key)"
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

          <!-- The pipeline as bars rather than a table: stage sizes are the
               one panel where the shape IS the answer. The count (and value,
               when forecasting is on) stays as text — the bar only ranks. -->
          <div v-else-if="panel.id === 'pipeline'" class="flex flex-col gap-3">
            <p
              v-if="panel.note?.value"
              class="flex items-start gap-2 rounded-4 bg-surface-orange-1 px-3 py-2 text-sm text-ink-orange-9"
            >
              <LucideInfo class="mt-0.5 size-4 shrink-0" />
              <span>{{ panel.note.value }}</span>
            </p>
            <div
              v-for="(row, i) in panel.rows.value"
              :key="i"
              class="flex flex-col gap-1.5"
            >
              <div class="flex items-baseline justify-between gap-2 text-base">
                <span class="truncate text-ink-gray-7">{{ row.stage }}</span>
                <span class="shrink-0 tabular-nums text-ink-gray-8">
                  {{ panel.cell(row) }}
                </span>
              </div>
              <div
                class="h-2 w-full overflow-hidden rounded-full bg-surface-gray-3"
                aria-hidden="true"
              >
                <div
                  class="h-full rounded-full"
                  :style="{
                    width: `${pipelineShare(panel.rows.value, row)}%`,
                    background: 'var(--brand-gradient)',
                  }"
                />
              </div>
            </div>
          </div>

          <!-- A panel with several figures per row: the report's own columns,
               a header row, and the rep's name first (or the panel's own
               rowLabel). `stats` puts the period's totals above the table. -->
          <div v-else-if="panel.columns" class="overflow-x-auto">
            <p
              v-if="panel.note?.value"
              class="mb-3 flex items-start gap-2 rounded-4 bg-surface-gray-2 px-3 py-2 text-sm text-ink-gray-7"
            >
              <LucideInfo class="mt-0.5 size-4 shrink-0" />
              <span>{{ panel.note.value }}</span>
            </p>
            <dl
              v-if="panel.stats"
              class="mb-4 grid grid-cols-3 gap-x-4 gap-y-3 sm:grid-cols-6"
            >
              <div
                v-for="stat in panel.stats.value"
                :key="stat.key"
                class="flex flex-col gap-0.5"
              >
                <dt class="v-kpi-label text-ink-gray-5">{{ stat.label }}</dt>
                <dd
                  class="font-display text-2xl font-semibold tabular-nums text-ink-gray-9"
                  :class="stat.tone"
                >
                  {{ stat.value }}
                </dd>
              </div>
            </dl>
            <table class="w-full text-base">
              <thead>
                <tr class="border-b border-outline-gray-1">
                  <th
                    class="py-1.5 pr-2 text-left text-xs font-medium uppercase tracking-wider text-ink-gray-5"
                  >
                    {{ panel.rowHeader || __('Rep') }}
                  </th>
                  <th
                    v-for="column in panel.columns"
                    :key="column.key"
                    class="whitespace-nowrap py-1.5 pl-3 text-right text-xs font-medium uppercase tracking-wider text-ink-gray-5"
                  >
                    {{ column.label }}
                  </th>
                </tr>
              </thead>
              <tbody>
                <tr
                  v-for="(row, i) in panel.rows.value"
                  :key="i"
                  class="border-b border-outline-gray-1 last:border-b-0"
                >
                  <td class="py-1.5 pr-2 text-ink-gray-7">
                    {{
                      panel.rowLabel
                        ? panel.rowLabel(row)
                        : row.rep || repName(row.user)
                    }}
                  </td>
                  <td
                    v-for="column in panel.columns"
                    :key="column.key"
                    class="whitespace-nowrap py-1.5 pl-3 text-right tabular-nums text-ink-gray-8"
                  >
                    {{ formatCell(row[column.key], column.type, baseCurrency) }}
                  </td>
                </tr>
              </tbody>
            </table>
          </div>

          <!-- Manager panels are report rows, rendered as a compact table so
               the number in the panel and the number in the report are the
               same number. Rows are per rep unless the panel says otherwise
               via its own rowLabel. -->
          <div v-else>
            <!-- The report's own notice, when it has one — "forecasting is
                 off" is why a pipeline's expected value reads 0, and a panel
                 that shows the zero without the reason reads as broken. Same
                 string the Reports page shows, from the same helper. -->
            <p
              v-if="panel.note?.value"
              class="mb-3 flex items-start gap-2 rounded-4 bg-surface-orange-1 px-3 py-2 text-sm text-ink-orange-9"
            >
              <LucideInfo class="mt-0.5 size-4 shrink-0" />
              <span>{{ panel.note.value }}</span>
            </p>
            <table class="w-full text-base">
              <tbody>
                <tr
                  v-for="(row, i) in panel.rows.value"
                  :key="i"
                  class="border-b border-outline-gray-1 last:border-b-0"
                >
                  <td class="py-1.5 pr-2 text-ink-gray-7">
                    {{
                      panel.rowLabel ? panel.rowLabel(row) : repName(row.user)
                    }}
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
          </div>
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

      <!-- Reps get a read-only chart strip: the same charts, from the same
           endpoint, that managers place in their grid — scoped to the rep's
           own records by the server. Before this a plain Sales User saw no
           chart at all. -->
      <template v-if="!isTeamView">
        <h2 class="v-title-sm mt-6 text-ink-gray-8">{{ __('Your trends') }}</h2>
        <div class="mt-2 grid grid-cols-1 gap-3">
          <div
            v-for="chart in repCharts"
            :key="chart.name"
            class="h-72 overflow-hidden rounded-6"
            :class="
              chart.resource.loading ||
              chart.resource.error ||
              axisChartEmpty(chart.resource.data)
                ? 'v-glass'
                : ''
            "
          >
            <SkeletonTable
              v-if="chart.resource.loading"
              :rows="4"
              :columns="2"
            />
            <ErrorState
              v-else-if="chart.resource.error"
              compact
              :error="chart.resource.error"
              :retry="() => chart.resource.reload()"
            />
            <!-- A trend with nothing in it draws as bare axes, which reads as
                 a broken widget. Say what it is instead. Server-provided
                 emptyState payloads still render through DashboardItem. -->
            <div
              v-else-if="axisChartEmpty(chart.resource.data)"
              class="relative h-full"
            >
              <EmptyState
                icon="lucide-line-chart"
                :title="__('Nothing here yet')"
                :description="chart.emptyDescription"
                top="15%"
                width="lg"
              />
            </div>
            <DashboardItem
              v-else-if="chart.resource.data"
              :index="0"
              :item="{ type: 'axis_chart', data: chart.resource.data }"
            />
          </div>
        </div>
      </template>

      <template v-if="showChartGrid">
        <h2 class="v-title-sm mt-6 text-ink-gray-8">{{ __('Charts') }}</h2>
        <!-- Not while arranging: a filter change refreshes the figures under
             the grid, and swapping it for a skeleton would drop it mid-edit. -->
        <SkeletonTable
          v-if="dashboardItems.loading && !editing"
          :rows="4"
          :columns="2"
        />
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
import DashboardItem from '@/components/Dashboard/DashboardItem.vue'
import EmptyState from '@/components/ListViews/EmptyState.vue'
import { PhArrowCounterClockwise as LucideRefreshCcw } from '@phosphor-icons/vue'
import { PhArrowUUpLeft as LucideUndo2 } from '@phosphor-icons/vue'
import { PhPencilLine as LucidePenLine } from '@phosphor-icons/vue'
import { PhInfo as LucideInfo } from '@phosphor-icons/vue'
import DashboardGrid from '@/components/Dashboard/DashboardGrid.vue'
import PanelCard from '@/components/Dashboard/PanelCard.vue'
import RadialGauge from '@/components/Dashboard/RadialGauge.vue'
import StatTile from '@/components/Dashboard/StatTile.vue'
import { useDrilldown } from '@/components/Dashboard/drilldown'
import ErrorState from '@/components/ui/ErrorState.vue'
import SkeletonTable from '@/components/ui/SkeletonTable.vue'
import ViewBreadcrumbs from '@/components/ViewBreadcrumbs.vue'
import LayoutHeader from '@/components/LayoutHeader.vue'
import Link from '@/components/Controls/Link.vue'
import { usersStore } from '@/stores/users'
import { ALL_REPS, useVisibleReps } from '@/composables/visibleReps'
import { getSettings } from '@/stores/settings'
import { isNarrowGrid } from '@/composables/settings'
import { EMPTY_CELL, formatCell } from '@/utils/reportExport'
import { copy } from '@/utils'
import { describeError } from '@/utils/describeError'
import { latestOnly } from '@/utils/latestOnly'
import { quiet } from '@/utils/quiet'
import {
  activitySummary,
  adherencePercent,
  applyPanelPreference,
  axisChartEmpty,
  groupRisksByRecord,
  planBreakdown,
  reorderVisiblePanel,
  riskReason,
  toISODate,
  withFreshFigures,
} from '@/utils/dashboardHome'
import {
  ACTIVITY_TYPES,
  activityLabel,
  mondayOf,
  todayInTimeZone,
} from '@/utils/planner'
import * as suggestionsModule from '@/stores/suggestions'
import { displayReferenceLabel, urgencyBand } from '@/utils/suggestions'
import {
  getLastXDays,
  formatter,
  parseDateRange,
  type DashboardDateRange,
} from '@/utils/dashboard'
import {
  usePageMeta,
  createResource,
  getConfig,
  Badge,
  DateRangePicker,
  Dropdown,
  Select,
  toast,
} from 'frappe-ui'
import { ref, reactive, computed, provide } from 'vue'
import { useRouter } from 'vue-router'

const { getUser, isManager, isAdmin } = usersStore()
const { filterOptions: repFilterOptions } = useVisibleReps()
const { settings, brand } = getSettings()
const router = useRouter()

const baseCurrency = computed(
  () => settings.value?.currency || window.sysdefaults?.currency || 'USD',
)
const { drillInto, canDrillInto } = useDrilldown()

const editing = ref(false)
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

function chartResource(name: string, teamOnly = false) {
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
    // every resource on this page refetches on a filter change; only the
    // answer to the latest one may land (see latestOnly)
    resourceFetcher: latestOnly(),
    // A team-only tile is never rendered for a rep, so it never fetches for
    // one either — same gate as reportResource below.
    auto: !teamOnly || isTeamView.value,
  })
}

/* `showHint` renders the server's explanation as the tile's second line
   instead of hover-only: "R 12,000 of R 50,000 closed-won against quota" is
   the difference between a percentage and an answer, and a hover tooltip is
   an affordance nobody finds on a stat card. */
const TILE_CATALOGUE = [
  { name: 'total_leads', label: __('Leads'), teamOnly: true },
  { name: 'ongoing_deals', label: __('Open deals'), teamOnly: false },
  { name: 'won_deals', label: __('Won deals'), teamOnly: false },
  // Reps see this too now: the count sits directly above the "Needs your
  // attention" panel that lists the deals behind it.
  { name: 'deals_at_risk', label: __('Critical deals'), teamOnly: false },
  {
    name: 'plan_adherence',
    label: __('Plan adherence'),
    teamOnly: false,
    showHint: true,
  },
  {
    name: 'quota_attainment',
    label: __('Quota attainment'),
    teamOnly: false,
    showHint: true,
  },
]

const tileResources = Object.fromEntries(
  TILE_CATALOGUE.map((t) => [t.name, chartResource(t.name, t.teamOnly)]),
)

const tiles = computed(() =>
  TILE_CATALOGUE.filter((t) => isTeamView.value || !t.teamOnly).map((t) => ({
    ...t,
    resource: tileResources[t.name],
  })),
)

/* Command Center split: the four counting tiles form the KPI band; the two
   percentage tiles render as radial gauges in the hero rail. One catalogue,
   two presentations — the resources, role gating, and drilldowns are shared
   unchanged. */
const GAUGE_NAMES = ['plan_adherence', 'quota_attainment']
const kpiTiles = computed(() =>
  tiles.value.filter((t) => !GAUGE_NAMES.includes(t.name)),
)
const gaugeTiles = computed(() =>
  tiles.value.filter((t) => GAUGE_NAMES.includes(t.name)),
)

const drilldownContext = computed(() => ({
  user: scopeUser.value,
  territory: scopeTerritory.value,
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

/* "Today" is a calendar day in the site's timezone, the one the Planner opens
   on and the server matches plans in; the browser's clock put a rep outside
   that zone on the wrong day, and in the wrong week, around midnight. A ref
   re-read on every plan fetch, not a computed over `new Date()`: with no
   reactive dependency that was evaluated once, so a tab left open overnight
   fetched the new week on Refresh but kept filtering it on yesterday. */
const siteToday = () => todayInTimeZone(getConfig('systemTimezone'))
const today = ref(siteToday())

/* Badge's warning theme is still named `amber` in frappe-ui; the band itself
   decides the cut-off (URGENCY_HIGH in utils/suggestions), not this page. */
function riskBadgeTheme(band: string) {
  return band === 'high' ? 'red' : 'amber'
}

const myPlan = createResource({
  url: 'crm.api.rep_plan.get_plan',
  makeParams: () => {
    today.value = siteToday()
    return { week_start: mondayOf(today.value) }
  },
  resourceFetcher: latestOnly(),
  // Only the rep home renders today's plan; the team view reloads what it
  // shows through reloadAll, the same way reportResource gates on the role.
  auto: !isTeamView.value,
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
    resourceFetcher: latestOnly(),
    auto: isTeamView.value,
  })
}

const teamAdherence = reportResource('plan_adherence_by_rep')
const teamQuota = reportResource('quota_attainment_by_rep')
const teamVisits = reportResource('visits_by_rep')
const teamSummary = reportResource('rep_summary')
const teamActivity = reportResource('activities_by_type')
const teamPipeline = reportResource('pipeline_by_stage')
/* One list, so reloadAll cannot miss one: the Rep summary and Activity summary
   panels were added after reloadAll was written, never joined it, and kept the
   first load's figures under whatever period or rep was chosen next. */
const teamReports = [
  teamAdherence,
  teamQuota,
  teamVisits,
  teamSummary,
  teamActivity,
  teamPipeline,
]

/* The rep chart strip. Same endpoint as the manager grid's charts; the server
   pins a plain Sales User to their own records, so these are personal trends
   without a separate aggregate existing anywhere. */
function repChartResource(name: string) {
  return createResource({
    url: 'crm.api.dashboard.get_chart',
    makeParams: () => ({
      name,
      type: 'axis_chart',
      from_date: fromDate.value,
      to_date: toDate.value,
      user: scopeUser.value,
      territory: scopeTerritory.value,
    }),
    resourceFetcher: latestOnly(),
    auto: !isTeamView.value,
  })
}

const repCharts = [
  {
    name: 'funnel_conversion',
    resource: repChartResource('funnel_conversion'),
    emptyDescription: __(
      'Conversion through the funnel appears once records move in this period.',
    ),
  },
]

/* The hero: the same sales_trend chart the rep strip used to render, now the
   page's centerpiece for both roles. The server scopes it by role exactly as
   it does for the grid and the strip. */
const heroTrend = createResource({
  url: 'crm.api.dashboard.get_chart',
  makeParams: () => ({
    name: 'sales_trend',
    type: 'axis_chart',
    from_date: fromDate.value,
    to_date: toDate.value,
    user: scopeUser.value,
    territory: scopeTerritory.value,
  }),
  resourceFetcher: latestOnly(),
  auto: true,
})

function repName(user: string) {
  return getUser(user)?.full_name || user
}

/* Bar width for the pipeline panel: share of the largest stage, floored at
   2% so a tiny stage still draws a visible sliver rather than nothing. */
function pipelineShare(rows, row) {
  if (!row.deals) return 0
  const max = Math.max(...rows.map((r) => r.deals || 0), 1)
  return Math.max(2, Math.round(((row.deals || 0) / max) * 100))
}

const activity = computed(() =>
  activitySummary(
    teamActivity.data?.rows || [],
    ACTIVITY_TYPES.map((t) => t.value),
  ),
)

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
      id: 'summary',
      wide: true,
      title: __('Rep summary'),
      subtitle: __(
        'Visits, calls and emails done in the period, beside the quotes and orders, per rep',
      ),
      loading: computed(() => teamSummary.loading),
      error: computed(() => teamSummary.error),
      retry: () => teamSummary.reload(),
      empty: computed(
        () => !teamSummary.loading && !(teamSummary.data?.rows || []).length,
      ),
      emptyTitle: __('Nothing done in this period'),
      emptyDescription: __(
        'Visits, quotes and orders appear here as the reps log them.',
      ),
      rows: computed(() => teamSummary.data?.rows || []),
      note: computed(() => teamSummary.data?.notice || ''),
      columns: [
        { key: 'visits', label: __('Visits'), type: 'number' },
        { key: 'unplanned', label: __('Unplanned'), type: 'number' },
        { key: 'deliveries', label: __('Deliveries'), type: 'number' },
        { key: 'calls', label: __('Calls'), type: 'number' },
        { key: 'emails', label: __('Emails'), type: 'number' },
        { key: 'quotes', label: __('Quotes'), type: 'number' },
        { key: 'quote_value', label: __('Quote value'), type: 'currency' },
        { key: 'orders', label: __('Orders'), type: 'number' },
        { key: 'order_value', label: __('Order value'), type: 'currency' },
      ],
      cell: () => '',
    },
    {
      id: 'activity',
      wide: true,
      title: __('Activity summary'),
      subtitle: __(
        'Every planned and logged activity in the period, by type and what became of it',
      ),
      loading: computed(() => teamActivity.loading),
      error: computed(() => teamActivity.error),
      retry: () => teamActivity.reload(),
      empty: computed(
        () => !teamActivity.loading && !activity.value.types.length,
      ),
      emptyTitle: __('No activities in this period'),
      emptyDescription: __(
        'Planned visits, calls and the rest appear here as reps plan and log them.',
      ),
      stats: computed(() => [
        {
          key: 'scheduled',
          label: __('Total'),
          value: activity.value.totals.scheduled,
        },
        {
          key: 'done',
          label: __('Completed'),
          value: activity.value.totals.done,
        },
        {
          key: 'overdue',
          label: __('Overdue'),
          value: activity.value.totals.overdue,
          tone: activity.value.totals.overdue ? 'text-ink-orange-9' : '',
        },
        {
          key: 'missed',
          label: __('Missed'),
          value: activity.value.totals.missed,
        },
        {
          key: 'cancelled',
          label: __('Cancelled'),
          value: activity.value.totals.cancelled,
        },
        {
          key: 'open',
          label: __('Still planned'),
          value: activity.value.totals.open,
        },
      ]),
      rowHeader: __('Type'),
      rowLabel: (row) => __(activityLabel(row.activity_type)),
      rows: computed(() => activity.value.types),
      columns: [
        { key: 'scheduled', label: __('Total'), type: 'number' },
        { key: 'done', label: __('Completed'), type: 'number' },
        { key: 'overdue', label: __('Overdue'), type: 'number' },
        { key: 'missed', label: __('Missed'), type: 'number' },
        { key: 'cancelled', label: __('Cancelled'), type: 'number' },
        { key: 'open', label: __('Still planned'), type: 'number' },
      ],
      cell: () => '',
    },
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
      cell: (row) => (row.adherence == null ? EMPTY_CELL : `${row.adherence}%`),
      tone: (row) =>
        row.adherence != null && row.adherence < 60 ? 'text-ink-orange-9' : '',
    },
    {
      id: 'visits',
      title: __('Visits against target'),
      subtitle: __(
        "Completed planned visits in the period, against each rep's weekly target",
      ),
      loading: computed(() => teamVisits.loading),
      error: computed(() => teamVisits.error),
      retry: () => teamVisits.reload(),
      empty: computed(
        () => !teamVisits.loading && !(teamVisits.data?.rows || []).length,
      ),
      emptyTitle: __('No visits or targets in this period'),
      emptyDescription: __(
        'Set weekly visit targets in Settings → Visit Targets.',
      ),
      rows: computed(() => teamVisits.data?.rows || []),
      // No target is not behind on one, the same rule as the quota panel.
      cell: (row) =>
        row.target == null
          ? `${row.completed} · ${__('No target')}`
          : `${row.completed} / ${row.target}`,
      // the status is judged against the target due so far, not the period's
      tone: (row) => (row.on_track === 'Behind' ? 'text-ink-orange-9' : ''),
    },
    {
      id: 'pipeline',
      title: __('Pipeline by stage'),
      subtitle: __('Open deals right now — count and expected value'),
      loading: computed(() => teamPipeline.loading),
      error: computed(() => teamPipeline.error),
      retry: () => teamPipeline.reload(),
      empty: computed(
        () => !teamPipeline.loading && !(teamPipeline.data?.rows || []).length,
      ),
      emptyTitle: __('No open deals'),
      emptyDescription: __('The pipeline appears here as deals are created.'),
      rows: computed(() => teamPipeline.data?.rows || []),
      rowLabel: (row) => row.stage,
      note: computed(() => teamPipeline.data?.notice || ''),
      // With forecasting off every expected value is 0 by construction; the
      // note above the table says so, and the cell stops repeating "$0".
      cell: (row) =>
        teamPipeline.data?.notice
          ? `${row.deals}`
          : `${row.deals} · ${formatCell(
              row.total_value,
              'currency',
              baseCurrency.value,
            )}`,
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
      // No target is not 0% of one: the report sends null for a rep with
      // nothing set, and 0% in orange ranked them as the worst performer.
      cell: (row) =>
        row.attainment == null ? __('No target') : `${row.attainment}%`,
      tone: (row) =>
        row.attainment != null && row.attainment < 80
          ? 'text-ink-orange-9'
          : '',
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

/* frappe-ui v1's DateRangePicker reports a cleared or half-typed period as
   `[]`, which is truthy: it used to be stored as the period, so the label read
   "Invalid Date to Invalid Date" and every panel sent null dates, which the
   server answers with the current calendar month. A range missing either end
   falls back to the default instead. */
function onPeriodChange(value: DashboardDateRange) {
  const [from, to] = parseDateRange(value)
  updateFilter('period', value, () => {
    if (from && to) {
      preset.value = formatter(value)
    } else {
      filters.period = getLastXDays()
      preset.value = 'Last 30 Days'
    }
  })
}

function reloadAll() {
  quiet(heroTrend.reload())
  // the tiles this role sees: a rep has no Leads tile to refresh
  tiles.value.forEach((tile) => quiet(tile.resource.reload()))
  quiet(suggestions.reload())
  if (isTeamView.value) {
    // the manager grid; a rep's page never renders it, so never computes it
    quiet(dashboardItems.reload())
    teamReports.forEach((report) => quiet(report.reload()))
  } else {
    quiet(myPlan.reload())
    repCharts.forEach((chart) => quiet(chart.resource.reload()))
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
    /* Only opens the picker; the period and its label change once a range is
       picked (onPeriodChange), the way Reports.vue does it. Nulling the period
       here left it null when the picker was dismissed unpicked -- frappe-ui
       emits nothing then -- so every later reload sent null dates, which the
       server answers with the current calendar month. A click in a full range
       starts a new one, so there is nothing to clear for the pick either. */
    onClick: () => {
      setTimeout(() => datePickerRef.value?.open(), 0)
    },
  },
])

const oldItems = ref([])

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
  resourceFetcher: latestOnly(),
  /* While the grid is being arranged, the arrangement on screen is unsaved
     work and the server's layout is the one it is replacing: a filter change
     takes each chart's new figures and leaves where the charts sit alone. The
     Edit-time copy that Cancel restores takes them too, or cancelling would
     bring back the previous period's numbers. */
  transform(fresh) {
    if (!editing.value) return fresh
    oldItems.value = withFreshFigures(oldItems.value, fresh)
    return withFreshFigures(dashboardItems.data, fresh)
  },
  // the grid is managers' only: a rep's page never renders it
  auto: isTeamView.value,
})

const dirty = computed(() => {
  if (!editing.value) return false
  return JSON.stringify(dashboardItems.data) !== JSON.stringify(oldItems.value)
})

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
  return { title: __('Dashboard'), icon: brand.favicon }
})
</script>
