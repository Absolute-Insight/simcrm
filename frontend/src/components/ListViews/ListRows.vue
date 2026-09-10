<template>
  <div
    v-if="showGroupedRows"
    ref="groupedScrollContainer"
    class="v-list h-full overflow-y-auto"
  >
    <div v-for="group in reactivieRows" :key="group.group">
      <ListGroupHeader :group="group">
        <div
          class="my-2 flex items-center gap-2 text-base-medium text-ink-gray-8"
        >
          <div>{{ __(group.label) }} -</div>
          <div class="flex items-center gap-1">
            <component :is="group.icon" v-if="group.icon" />
            <div v-if="group.group == ' '" class="text-ink-gray-4">
              {{ __('Empty') }}
            </div>
            <div v-else>{{ group.group }}</div>
          </div>
        </div>
      </ListGroupHeader>
      <ListGroupRows :group="group">
        <ListRow
          v-for="row in group.rows"
          :key="row.name"
          v-slot="{ idx, column, item }"
          :row="row"
        >
          <slot v-bind="{ idx, column, item, row }" />
        </ListRow>
      </ListGroupRows>
    </div>
  </div>
  <ListRows v-else ref="scrollContainer" class="v-list">
    <ListRow
      v-for="row in reactivieRows"
      :key="row.name"
      v-slot="{ idx, column, item }"
      :row="row"
    >
      <slot v-bind="{ idx, column, item, row }" />
    </ListRow>
  </ListRows>
</template>

<script setup>
import { useStorage } from '@vueuse/core'
// parked in experimental for v1 (frappe-ui migration doc)
import {
  ListRows,
  ListRow,
  ListGroupHeader,
  ListGroupRows,
} from 'frappe-ui/experimental'
import { ref, computed, watch, onBeforeUnmount } from 'vue'

const props = defineProps({
  rows: { type: Array, required: true },
  doctype: { type: String, default: 'CRM Lead' },
})

const reactivieRows = ref(props.rows)

watch(
  () => props.rows,
  (val) => (reactivieRows.value = val),
)

let showGroupedRows = computed(() => {
  return props.rows.every(
    (row) => row.group && row.rows && Array.isArray(row.rows),
  )
})

const scrollPosition = useStorage(`scrollPosition${props.doctype}`, 0)
const scrollContainer = ref(null)
const groupedScrollContainer = ref(null)

const handleScroll = (e) => {
  scrollPosition.value = e.target.scrollTop
}

// Grouping toggles at runtime as props.rows reshapes, without this component
// remounting, so wiring the listener once in onMounted lost it on every switch
// and the grouped container -- which had no ref at all -- never saved or
// restored anything. Track whichever container is currently in the DOM.
let activeScrollEl = null

watch(
  [scrollContainer, groupedScrollContainer],
  () => {
    const el =
      scrollContainer.value?.$el || groupedScrollContainer.value || null
    if (el === activeScrollEl) return

    if (activeScrollEl) {
      activeScrollEl.removeEventListener('scroll', handleScroll)
    }
    activeScrollEl = el
    if (activeScrollEl) {
      activeScrollEl.addEventListener('scroll', handleScroll)
      activeScrollEl.scrollTop = scrollPosition.value
    }
  },
  { immediate: true, flush: 'post' },
)

onBeforeUnmount(() => {
  if (activeScrollEl) {
    activeScrollEl.removeEventListener('scroll', handleScroll)
  }
})
</script>
