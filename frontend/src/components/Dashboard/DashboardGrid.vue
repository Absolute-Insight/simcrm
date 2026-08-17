<template>
  <div class="flex-1 overflow-y-auto p-3">
    <!-- Below WIDE_GRID_BREAKPOINT_PX the twenty-column grid stops dividing
         into readable columns: a panel laid out four wide gets a fifth of the
         viewport, ~140px at 700px, and a number card truncates to nothing.
         Stacked full-width in layout order instead — the same way every other
         grid in the app degrades. Editing stays on the wide layout only; there
         is nothing to drag when everything is one column, and dragging is how
         the stored layout is written. -->
    <div v-if="isNarrowGrid && items.length > 0" class="flex flex-col gap-3">
      <div
        v-for="(item, index) in stackedItems"
        :key="item.key"
        class="flex text-ink-gray-8"
        :style="{ height: `${stackedHeight(item)}px` }"
      >
        <DashboardItem :index="item.index" :item="items[item.index]" />
      </div>
    </div>

    <GridLayout
      v-else-if="items.length > 0"
      class="h-fit w-full"
      :class="[editing ? 'mb-[20rem] !select-none' : '']"
      :cols="20"
      :rowHeight="ROW_HEIGHT"
      :disabled="!editing"
      :modelValue="items.map((item) => item.layout)"
      @update:modelValue="
        (newLayout) => {
          items.forEach((item, idx) => {
            item.layout = newLayout[idx]
          })
        }
      "
    >
      <template #item="{ index }">
        <div class="group relative flex h-full w-full p-2 text-ink-gray-8">
          <div
            class="flex h-full w-full items-center justify-center"
            :class="
              editing
                ? 'pointer-events-none  [&>div:first-child]:rounded-4 [&>div:first-child]:group-hover:ring-2 [&>div:first-child]:group-hover:ring-outline-gray-2'
                : ''
            "
          >
            <DashboardItem
              :index="index"
              :item="items[index]"
              :editing="editing"
            />
          </div>
          <div
            v-if="editing"
            class="flex absolute right-0 top-0 bg-surface-gray-9 rounded-4 cursor-pointer opacity-0 group-hover:opacity-100"
          >
            <div
              class="rounded-4 p-1 hover:bg-surface-gray-8"
              @click="items.splice(index, 1)"
            >
              <span
                class="lucide-trash-2 size-3 text-ink-base"
                aria-hidden="true"
              />
            </div>
          </div>
        </div>
      </template>
    </GridLayout>
  </div>
</template>
<script setup>
import GridLayout from '@/components/Dashboard/GridLayout.vue'
import DashboardItem from '@/components/Dashboard/DashboardItem.vue'
import { isNarrowGrid } from '@/composables/settings'
import { computed } from 'vue'

const ROW_HEIGHT = 42

defineProps({
  editing: { type: Boolean, default: false },
})

const items = defineModel({ type: Array, default: () => [] })

/* Reading order, which is what the stored layout means once the columns are
   gone: top to bottom, then left to right. Sorting by `y` alone would leave two
   panels on the same row in whatever order the array happened to hold them. */
const stackedItems = computed(() =>
  items.value
    .map((item, index) => ({
      index,
      key: item.layout?.i ?? `${item.name ?? 'panel'}-${index}`,
      y: item.layout?.y ?? 0,
      x: item.layout?.x ?? 0,
      h: item.layout?.h ?? 3,
    }))
    .sort((a, b) => a.y - b.y || a.x - b.x),
)

/* Keep each panel's own height. A chart laid out three rows tall is three rows
   tall because that is what it needs to be legible; flattening every panel to
   one height would trade a width problem for a height one. */
const stackedHeight = (item) => item.h * ROW_HEIGHT
</script>
