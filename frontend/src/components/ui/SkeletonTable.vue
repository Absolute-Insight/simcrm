<!--
  SkeletonTable — the loading state for the report, quota and planner tables.

  Reach for it instead of a bare <Skeleton> whenever the thing loading is a
  table: it lays out a real <table> with the same chrome and density as the
  ones in Reports/Quotas, so the header rules and column edges are already
  drawn in the right places and nothing shifts when the rows arrive.

  Pass `columns` as a count when you do not know the shape yet, or as the
  report's own column spec (`[{ type: 'text' | 'currency', ... }]`) once you
  do — alignment then matches the real table cell for cell.

    <SkeletonTable v-if="report.loading" :columns="6" :rows="8" />
    <SkeletonTable :columns="report.data.columns" density="compact" />
-->
<template>
  <div
    class="w-full overflow-x-auto"
    role="status"
    aria-busy="true"
    :aria-label="label || __('Loading table')"
  >
    <table class="w-full border-collapse text-base">
      <thead v-if="header">
        <tr>
          <th
            v-for="(col, i) in columnSpecs"
            :key="i"
            class="border-b-2 border-outline-gray-2 px-3 py-2"
          >
            <Skeleton
              shape="block"
              height="0.5rem"
              :width="col.headWidth"
              :style="alignStyle(col)"
            />
          </th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="row in rowCount" :key="row">
          <td
            v-for="(col, i) in columnSpecs"
            :key="i"
            class="border-b border-outline-gray-1 px-3"
            :class="density === 'compact' ? 'py-1.5' : 'py-2'"
          >
            <Skeleton
              shape="block"
              :height="density === 'compact' ? '0.625rem' : '0.6875rem'"
              :width="skeletonCellWidth(col, row - 1)"
              :style="alignStyle(col)"
            />
          </td>
        </tr>
      </tbody>
    </table>
  </div>
</template>

<script setup>
import Skeleton from './Skeleton.vue'
import { skeletonCellWidth, skeletonTableColumns } from '@/utils/skeletonShapes'
import { computed } from 'vue'

const props = defineProps({
  // A column count, or the real column spec so alignment matches.
  columns: { type: [Number, Array], default: 4 },
  rows: { type: Number, default: 6 },
  header: { type: Boolean, default: true },
  // 'compact' is the quota/planner row height; 'default' is the report one.
  density: {
    type: String,
    default: 'default',
    validator: (v) => ['default', 'compact'].includes(v),
  },
  label: { type: String, default: '' },
})

const columnSpecs = computed(() => skeletonTableColumns(props.columns))

const rowCount = computed(() => Math.max(1, Math.floor(props.rows) || 1))

/* The bar sits where the text will: measures are right-aligned against the
   tabular figures, so their placeholders have to be too. */
function alignStyle(col) {
  return col.align === 'right' ? { marginLeft: 'auto' } : null
}
</script>
