<template>
  <Dialog v-model:open="show" :title="__('Add Chart')" @close="show = false">
    <template #default>
      <div class="flex flex-col gap-4">
        <FormControl
          v-model="chartType"
          type="select"
          :label="__('Chart Type')"
          :options="chartTypes"
        />
        <FormControl
          v-if="chartType === 'number_chart'"
          v-model="numberChart"
          type="select"
          :label="__('Number Chart')"
          :options="numberCharts"
        />
        <FormControl
          v-if="chartType === 'axis_chart'"
          v-model="axisChart"
          type="select"
          :label="__('Axis Chart')"
          :options="axisCharts"
        />
        <FormControl
          v-if="chartType === 'donut_chart'"
          v-model="donutChart"
          type="select"
          :label="__('Donut Chart')"
          :options="donutCharts"
        />
      </div>
    </template>
    <template #actions>
      <div class="flex items-center justify-end gap-2">
        <Button variant="outline" :label="__('Cancel')" @click="show = false" />
        <Button variant="solid" :label="__('Add')" @click="addChart" />
      </div>
    </template>
  </Dialog>
</template>

<script setup lang="ts">
import { getRandom } from '@/utils'
import { describeError } from '@/utils/describeError'
import { quiet } from '@/utils/quiet'
import { createResource, Dialog, FormControl, toast } from 'frappe-ui'
import { ref, reactive, inject } from 'vue'

const show = defineModel({
  type: Boolean,
  default: false,
})

const items = defineModel('items', {
  type: Array,
  default: () => [],
})

const fromDate = inject('fromDate', ref(''))
const toDate = inject('toDate', ref(''))
const filters = inject('filters', reactive({ period: '', user: '' }))

const chartType = ref('spacer')
const chartTypes = [
  { label: __('Spacer'), value: 'spacer' },
  { label: __('Number Chart'), value: 'number_chart' },
  { label: __('Axis Chart'), value: 'axis_chart' },
  { label: __('Donut Chart'), value: 'donut_chart' },
]

const numberChart = ref('')
// Metrics the curated tile row already shows (CURATED_TILE_METRICS in
// crm_dashboard.py) are deliberately not offered here: the picker adding them
// back to the grid is how the same number ends up answered twice on one page.
// Saved layouts that still carry one keep rendering — this list only gates
// what can be newly added.
const numberCharts = [
  { label: __('Avg Ongoing Deal Value'), value: 'average_ongoing_deal_value' },
  { label: __('Avg Won Deal Value'), value: 'average_won_deal_value' },
  { label: __('Avg Deal Value'), value: 'average_deal_value' },
  {
    label: __('Avg Time to Close a Lead'),
    value: 'average_time_to_close_a_lead',
  },
  {
    label: __('Avg Time to Close a Deal'),
    value: 'average_time_to_close_a_deal',
  },
]

const axisChart = ref('sales_trend')
const axisCharts = [
  { label: __('Sales Trend'), value: 'sales_trend' },
  { label: __('Forecasted Revenue'), value: 'forecasted_revenue' },
  { label: __('Funnel Conversion'), value: 'funnel_conversion' },
  { label: __('Deals by Ongoing & Won Stage'), value: 'deals_by_stage_axis' },
  { label: __('Lost Deal Reasons'), value: 'lost_deal_reasons' },
  { label: __('Deals by Territory'), value: 'deals_by_territory' },
  { label: __('Deals by Industry'), value: 'deals_by_industry' },
  { label: __('Deals by Company Size'), value: 'deals_by_company_size' },
  { label: __('Deals by Salesperson'), value: 'deals_by_salesperson' },
  { label: __('Forecast Accuracy'), value: 'forecast_accuracy' },
]

const donutChart = ref('deals_by_stage_donut')
const donutCharts = [
  { label: __('Deals by Stage'), value: 'deals_by_stage_donut' },
  { label: __('Leads by Source'), value: 'leads_by_source' },
  { label: __('Deals by Source'), value: 'deals_by_source' },
]

async function addChart() {
  if (chartType.value == 'spacer') {
    items.value.push({
      name: 'spacer',
      type: 'spacer',
      layout: { x: 0, y: 0, w: 4, h: 2, i: 'spacer_' + getRandom(4) },
    })
    show.value = false
    return
  }
  // The modal only closes once the chart is in the grid: closing first left
  // a failed fetch with nowhere to report to, and nothing on screen.
  if (await getChart(chartType.value)) show.value = false
}

/* Resolves true once the chart is pushed, false if the server said no. The
   resource's own rejection is swallowed here because onError already told the
   user (frappe-ui rethrows after onError). */
function getChart(type: string): Promise<boolean> {
  let name =
    type == 'number_chart'
      ? numberChart.value
      : type == 'axis_chart'
        ? axisChart.value
        : donutChart.value

  return new Promise((resolve) => {
    const chart = createResource({
      url: 'crm.api.dashboard.get_chart',
      params: {
        name,
        type,
        from_date: fromDate.value,
        to_date: toDate.value,
        user: filters.user,
        // Same scope the rest of the dashboard sends (Dashboard.vue
        // chartResource) — a chart added under a territory filter should
        // show that territory, not the whole site.
        territory: filters.territory || null,
      },
      onError: (e) => {
        toast.error(describeError(e).message || __('Could not add that chart'))
        resolve(false)
      },
      onSuccess: (data = {}) => {
        let width = 4
        let height = 2

        if (['axis_chart', 'donut_chart'].includes(type)) {
          width = 10
          height = 7
        }

        items.value.push({
          name,
          type,
          layout: {
            x: 0,
            y: 0,
            w: width,
            h: height,
            i: name + '_' + getRandom(4),
          },
          data: data,
        })
        resolve(true)
      },
    })
    quiet(chart.fetch())
  })
}
</script>
