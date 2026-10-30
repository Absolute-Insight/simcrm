<template>
  <ListView
    ref="listViewRef"
    :class="$attrs.class"
    :columns="columns"
    :rows="rows"
    :options="{
      selectable: true,
      showTooltip: true,
      resizeColumn: true,
    }"
    row-key="reference_docname"
    @update:selections="(selections) => emit('selectionsChanged', selections)"
  >
    <ListHeader @columnWidthUpdated="emit('columnWidthUpdated')">
      <ListHeaderItem
        v-for="column in columns"
        :key="column.key"
        :item="column"
        @columnWidthUpdated="(e) => onColumnWidthUpdated(e, column)"
      >
      </ListHeaderItem>
    </ListHeader>
    <div class="*:mx-0 *:sm:mx-0">
      <ListRows v-slot="{ column, item, row }" :rows="rows">
        <ListRowItem
          :item="item"
          class="!w-full"
          @click="listViewRef.toggleRow(row['reference_docname'])"
        >
          <template #default="{ label }">
            <div
              v-if="column.key === 'title'"
              class="truncate text-base flex gap-2 w-full"
            >
              <span class="max-w-[90%] truncate">
                {{ label }}
              </span>
              <span
                class="lucide-external-link h-4 w-4 cursor-pointer"
                aria-hidden="true"
                @click.stop="viewLinkedDoc(row)"
              />
            </div>
            <span
              v-if="column.key === 'reference_doctype'"
              class="truncate text-base flex gap-2"
            >
              {{ getDoctypeName(row.reference_doctype) }}
            </span>
          </template>
        </ListRowItem>
      </ListRows>
    </div>
  </ListView>
</template>

<script setup>
import ListRows from '@/components/ListViews/ListRows.vue'
// parked in experimental for v1 (frappe-ui migration doc)
import {
  ListView,
  ListHeader,
  ListHeaderItem,
  ListRowItem,
} from 'frappe-ui/experimental'
import { ref } from 'vue'

defineProps({
  rows: { type: Array, required: true },
  columns: { type: Array, required: true },
  linkedDocsResource: { type: Object, required: true },
  unlinkLinkedDoc: { type: Function, required: true },
  options: {
    type: Object,
    default: () => ({
      selectable: true,
      showTooltip: true,
      resizeColumn: false,
      totalCount: 0,
      rowCount: 0,
    }),
  },
})
const emit = defineEmits([
  'loadMore',
  'updatePageCount',
  'columnWidthUpdated',
  'applyFilter',
  'applyLikeFilter',
  'likeDoc',
  'selectionsChanged',
])

const listViewRef = ref(null)

function onColumnWidthUpdated({ width, save }, column) {
  column.width = width
  if (save) emit('columnWidthUpdated', column)
}

// Where the CRM shows a record of each doctype. Anything else -- a linked
// CRM Notification, an enrichment run -- opens in the desk, rather than at
// `/crm//` as an unlisted doctype (CRM Deal included) used to.
const crmPages = {
  'CRM Lead': (name) => `/crm/leads/${name}`,
  'CRM Deal': (name) => `/crm/deals/${name}`,
  Contact: (name) => `/crm/contacts/${name}`,
  'CRM Organization': (name) => `/crm/organizations/${name}`,
  'CRM Call Log': (name) => `/crm/call-logs/view?open=${name}`,
  'CRM Task': (name) => `/crm/tasks/view?open=${name}`,
  'FCRM Note': (name) => `/crm/notes/view?open=${name}`,
}

const viewLinkedDoc = (doc) => {
  // Names are free text ("Smith & Sons t/a #2"); a `/` or `#` in one cut the URL.
  const name = encodeURIComponent(doc.reference_docname)
  const page = crmPages[doc.reference_doctype]
  window.open(
    page
      ? page(name)
      : `/app/${doc.reference_doctype.toLowerCase().replace(/ /g, '-')}/${name}`,
  )
}

const getDoctypeName = (doctype) => {
  return doctype.replace(/^(CRM|FCRM)\s*/, '')
}
</script>
