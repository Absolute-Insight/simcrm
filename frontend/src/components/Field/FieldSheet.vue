<!--
  One reference sheet, page under page. From the copy on the device when it is
  kept; from the server otherwise, while there is one.
-->
<template>
  <div class="flex flex-col gap-4">
    <router-link
      :to="{ name: 'FieldSheets' }"
      class="-ml-1 flex min-h-9 w-fit items-center gap-1 rounded-5 pr-2 text-sm text-ink-gray-6 hover:text-ink-gray-8 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2"
    >
      <LucideChevronLeft class="size-4" aria-hidden="true" />
      {{ __('Sheets') }}
    </router-link>

    <div class="flex items-start justify-between gap-3">
      <h2
        class="font-display text-xl font-semibold leading-tight tracking-tight text-ink-gray-9"
      >
        {{ meta?.title || sheet }}
      </h2>
      <Button
        v-if="pages.length"
        class="shrink-0"
        :label="zoomed ? __('Fit page') : __('Zoom in')"
        @click="zoomed = !zoomed"
      />
    </div>

    <Skeleton
      v-if="loading"
      shape="block"
      height="24rem"
      rounded="10px"
      :label="__('Opening the sheet')"
    />

    <div
      v-else-if="!pages.length"
      class="flex flex-col items-center gap-1 rounded-5 border border-dashed px-4 py-10 text-center"
    >
      <span class="text-base font-medium text-ink-gray-8">
        {{ __('This sheet is not on this device') }}
      </span>
      <span class="text-p-base text-ink-gray-6">
        {{ __('Connect, then keep it from the list to open it anywhere.') }}
      </span>
    </div>

    <!-- Scrolls both ways when zoomed; the page keeps its own shape so the
         layout does not jump as each image arrives. -->
    <div v-else class="flex flex-col gap-3">
      <div
        v-for="page in pages"
        :key="page.page"
        class="overflow-auto rounded-5 border bg-white"
      >
        <img
          :src="page.src"
          :alt="__('{0}, page {1}', [meta?.title || sheet, page.page])"
          :width="page.width || undefined"
          :height="page.height || undefined"
          class="block h-auto max-w-none"
          :style="{ width: zoomed ? '250%' : '100%' }"
          loading="lazy"
          decoding="async"
        />
      </div>
    </div>
  </div>
</template>

<script setup>
import Skeleton from '@/components/ui/Skeleton.vue'
import { connectivity } from '@/offline/connectivity'
import { savedPages } from '@/offline/sheets'
import { useField } from '@/offline/useField'
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import LucideChevronLeft from '~icons/lucide/chevron-left'

const props = defineProps({ sheet: { type: String, required: true } })

const { pack } = useField()
const pages = ref([])
const loading = ref(true)
const zoomed = ref(false)
const objectUrls = []

const meta = computed(() =>
  (pack.value?.sheets ?? []).find((row) => row.name === props.sheet),
)

onMounted(async () => {
  const kept = await savedPages(props.sheet)
  if (kept?.length) {
    pages.value = kept.map((page) => {
      const src = URL.createObjectURL(page.blob)
      objectUrls.push(src)
      return { page: page.page, width: page.width, height: page.height, src }
    })
  } else if (connectivity.online) {
    pages.value = (meta.value?.pages ?? []).map((page) => ({
      page: page.page,
      width: page.width,
      height: page.height,
      src: page.image,
    }))
  }
  loading.value = false
})

// a blob URL holds its blob in memory until it is revoked
onBeforeUnmount(() => objectUrls.forEach((url) => URL.revokeObjectURL(url)))
</script>
