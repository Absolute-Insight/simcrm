<template>
  <Dialog v-model:open="show" :title="title" :size="'5xl'">
    <template #default>
      <div v-if="reference" class="flex flex-col gap-4">
        <div
          class="flex flex-wrap items-center justify-between gap-x-4 gap-y-2"
        >
          <p class="text-sm text-ink-gray-6">
            {{ reference.sheet_title }}
            <span class="text-ink-gray-4">·</span>
            {{ __('Page {0}', [page.page]) }}
            <template v-if="reference.section && !browsing">
              <span class="text-ink-gray-4">·</span>
              {{ reference.section }}
            </template>
          </p>
          <div class="flex flex-wrap items-center gap-2">
            <template v-if="browsing && pageCount > 1">
              <Button
                size="sm"
                variant="ghost"
                icon="lucide-chevron-left"
                :aria-label="__('Previous page')"
                :disabled="pageIndex === 0"
                @click="pageIndex--"
              />
              <span class="text-sm tabular-nums text-ink-gray-6">
                {{ pageIndex + 1 }} / {{ pageCount }}
              </span>
              <Button
                size="sm"
                variant="ghost"
                icon="lucide-chevron-right"
                :aria-label="__('Next page')"
                :disabled="pageIndex === pageCount - 1"
                @click="pageIndex++"
              />
            </template>
            <Button
              size="sm"
              variant="subtle"
              :label="zoomed ? __('Fit page') : __('Zoom in')"
              @click="toggleZoom"
            />
            <a
              v-if="pdfUrl"
              :href="pdfUrl"
              target="_blank"
              rel="noopener"
              class="inline-flex h-7 items-center gap-1.5 rounded-6 border border-outline-gray-2 px-2.5 text-sm text-ink-gray-8 hover:bg-surface-gray-2 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-outline-gray-3"
            >
              <PhArrowSquareOut class="size-4" aria-hidden="true" />
              {{ __('Open the PDF') }}
            </a>
          </div>
        </div>

        <div
          class="grid gap-4"
          :class="
            browsing ? '' : 'md:grid-cols-[minmax(0,17rem)_minmax(0,1fr)]'
          "
        >
          <!-- The row exactly as the sheet gives it: what the answer was
               checked against, readable without the page. -->
          <dl
            v-if="!browsing"
            class="flex flex-col divide-y divide-outline-gray-1 self-start rounded-6 border border-outline-gray-1"
          >
            <div
              v-for="(cell, index) in reference.cells"
              :key="index"
              class="flex flex-col gap-0.5 px-3 py-2"
              :class="quoted.has(index) ? 'bg-surface-gray-2' : ''"
            >
              <dt class="text-xs text-ink-gray-5">{{ cell.label }}</dt>
              <dd
                v-if="cellValue(cell) !== null"
                class="text-base tabular-nums text-ink-gray-9"
              >
                {{ cellValue(cell) || '—' }}
              </dd>
              <dd v-else class="flex flex-col gap-0.5">
                <span class="text-base text-ink-orange-9">
                  {{ __('Awaiting confirmation') }}
                </span>
                <span v-if="cell.note" class="text-xs text-ink-gray-5">
                  {{ cell.note }}
                </span>
              </dd>
            </div>
          </dl>

          <div
            ref="viewport"
            class="max-h-[65vh] overflow-auto rounded-6 border border-outline-gray-2 bg-white"
            :class="browsing ? 'max-h-[72vh]' : ''"
          >
            <div class="relative" :style="{ width: zoomed ? '220%' : '100%' }">
              <img
                v-if="imageUrl && !imageFailed"
                :key="imageUrl"
                :src="imageUrl"
                :alt="__('Page {0} of {1}', [page.page, reference.sheet_title])"
                class="block w-full select-none"
                draggable="false"
                @load="onImageLoad"
                @error="imageFailed = true"
              />
              <template v-if="imageLoaded && !browsing">
                <div
                  v-for="box in boxes"
                  :key="box.key"
                  class="reference-box pointer-events-none absolute"
                  :class="`reference-box--${box.kind}`"
                  :style="box.style"
                />
              </template>
              <div
                v-if="!imageLoaded && !imageFailed && imageUrl"
                class="flex aspect-[1/1.41] w-full animate-pulse items-center justify-center bg-surface-gray-1 text-sm text-ink-gray-5"
              >
                {{ __('Loading the page…') }}
              </div>
              <div
                v-if="imageFailed || !imageUrl"
                class="flex aspect-[1/1.41] w-full flex-col items-center justify-center gap-2 bg-surface-gray-1 p-6 text-center text-sm text-ink-gray-6"
              >
                {{ __('The page image could not be loaded.') }}
                <a
                  v-if="pdfUrl"
                  :href="pdfUrl"
                  target="_blank"
                  rel="noopener"
                  class="text-ink-gray-8 underline"
                >
                  {{ __('Open the PDF instead') }}
                </a>
              </div>
            </div>
          </div>
        </div>
      </div>
    </template>
  </Dialog>
</template>

<script setup>
/**
 * One row of a reference sheet, shown where it lives: its cells as the sheet
 * gives them, and its page with the row and the quoted cells highlighted.
 * Opened from a source chip under an Assistant answer, or from Settings →
 * Knowledge to browse a whole sheet (pass `pages` and no cells).
 */
import { PhArrowSquareOut } from '@phosphor-icons/vue'
import {
  boxCentre,
  cellValue,
  highlightBoxes,
  pdfPageUrl,
  safeFileUrl,
} from '@/utils/referenceSheet'
import { Button, Dialog } from 'frappe-ui'
import { computed, nextTick, ref, watch } from 'vue'

const props = defineProps({
  /** A reference from ask_assistant, or `{ sheet_title, file_url, pages }`. */
  reference: { type: Object, default: null },
})

const show = defineModel({ type: Boolean, default: false })

const viewport = ref(null)
const zoomed = ref(false)
const imageLoaded = ref(false)
const imageFailed = ref(false)
const pageIndex = ref(0)

const browsing = computed(() => Array.isArray(props.reference?.pages))
const pageCount = computed(() =>
  browsing.value ? props.reference.pages.length : 1,
)

const page = computed(() => {
  const r = props.reference || {}
  if (browsing.value) {
    const p = r.pages[pageIndex.value] || {}
    return { page: p.page, image: p.image, width: p.width, height: p.height }
  }
  return {
    page: r.page,
    image: r.page_image,
    width: r.page_width,
    height: r.page_height,
  }
})

const title = computed(() =>
  browsing.value ? props.reference?.sheet_title : props.reference?.label,
)
const imageUrl = computed(() => safeFileUrl(page.value.image))
const pdfUrl = computed(() =>
  pdfPageUrl(props.reference?.file_url, page.value.page),
)
const boxes = computed(() =>
  browsing.value ? [] : highlightBoxes(props.reference),
)
const quoted = computed(() => new Set(props.reference?.highlight || []))

watch(
  () => [show.value, props.reference],
  ([open]) => {
    if (!open) return
    zoomed.value = false
    pageIndex.value = 0
    imageLoaded.value = false
    imageFailed.value = false
  },
)

watch(imageUrl, () => {
  imageLoaded.value = false
  imageFailed.value = false
})

function onImageLoad() {
  imageLoaded.value = true
  nextTick(scrollToRow)
}

function toggleZoom() {
  zoomed.value = !zoomed.value
  nextTick(scrollToRow)
}

/** Bring the highlighted row to the middle of the viewport. */
function scrollToRow() {
  const el = viewport.value
  if (!el || browsing.value) return
  const content = el.firstElementChild
  if (!content) return
  const reference = props.reference || {}
  const y = boxCentre(reference.bbox, page.value.height) * content.clientHeight
  el.scrollTop = Math.max(0, y - el.clientHeight / 2)
  if (zoomed.value && Array.isArray(reference.bbox) && page.value.width > 0) {
    const x =
      (Number(reference.bbox[0]) / page.value.width) * content.clientWidth
    el.scrollLeft = Math.max(0, x - el.clientWidth / 6)
  }
}
</script>

<style scoped>
/* The page image is paper whatever the theme, so the marks are a pen and a
   highlighter on paper -- fixed colours, not theme tokens. */
.reference-box--guide {
  background: rgb(37 99 235 / 0.07);
}
.reference-box--row {
  border: 2px solid rgb(37 99 235 / 0.9);
  background: rgb(37 99 235 / 0.06);
  border-radius: 2px;
}
.reference-box--cell {
  background: rgb(250 204 21 / 0.45);
  mix-blend-mode: multiply;
  border-radius: 2px;
}
.reference-box--questioned {
  border: 2px dashed rgb(234 88 12 / 0.95);
  border-radius: 2px;
}
</style>
