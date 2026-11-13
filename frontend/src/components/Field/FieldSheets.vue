<!-- The company's reference sheets, and which of them this device holds. -->
<template>
  <div class="flex flex-col gap-3">
    <p class="text-p-base text-ink-gray-6">
      {{
        __(
          'Keep the sheets you use on site. A kept sheet opens with no connection.',
        )
      }}
    </p>

    <ul class="flex flex-col gap-2">
      <li
        v-for="sheet in sheets"
        :key="sheet.name"
        class="v-glass rounded-5 px-3.5 py-3"
      >
        <component
          :is="sheet.openable ? 'router-link' : 'div'"
          :to="
            sheet.openable
              ? { name: 'FieldSheet', params: { sheet: sheet.name } }
              : undefined
          "
          class="flex items-start justify-between gap-3 rounded-4 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2"
        >
          <div class="min-w-0">
            <div class="text-base font-medium text-ink-gray-9">
              {{ sheet.title }}
            </div>
            <div class="mt-0.5 text-sm text-ink-gray-6">{{ sheet.meta }}</div>
          </div>
          <LucideChevronRight
            v-if="sheet.openable"
            class="mt-1 size-4 shrink-0 text-ink-gray-5"
            aria-hidden="true"
          />
        </component>
        <p v-if="sheet.note" class="mt-1.5 text-p-sm text-ink-gray-7">
          {{ sheet.note }}
        </p>
        <div class="mt-2.5 flex flex-wrap items-center gap-2">
          <Button
            v-if="!sheet.kept || sheet.stale"
            :label="sheet.stale ? __('Update') : __('Keep on this device')"
            :loading="savedSheets.saving === sheet.name"
            :disabled="!connectivity.online || !!savedSheets.saving"
            @click="keep(sheet)"
          >
            <template #prefix>
              <LucideDownload class="size-4" aria-hidden="true" />
            </template>
          </Button>
          <Button
            v-if="sheet.kept"
            variant="ghost"
            :label="__('Remove')"
            :disabled="!!savedSheets.saving"
            @click="dropSheet(sheet.name)"
          />
          <span
            v-if="!sheet.kept && !connectivity.online"
            class="text-sm text-ink-gray-6"
          >
            {{ __('Connect to keep this sheet.') }}
          </span>
        </div>
        <ErrorMessage
          v-if="failed === sheet.name"
          class="mt-2"
          :message="failure"
        />
      </li>
    </ul>

    <div
      v-if="!sheets.length"
      class="flex flex-col items-center gap-1 rounded-5 border border-dashed px-4 py-10 text-center"
    >
      <LucideFileText class="mb-1 size-6 text-ink-gray-5" aria-hidden="true" />
      <span class="text-base font-medium text-ink-gray-8">
        {{ __('No reference sheets') }}
      </span>
      <span class="text-p-base text-ink-gray-6">
        {{ __('Sheets your company loads appear here.') }}
      </span>
    </div>
  </div>
</template>

<script setup>
import { connectivity } from '@/offline/connectivity'
import {
  dropSheet,
  keepSheet,
  loadSavedSheets,
  savedSheets,
} from '@/offline/sheets'
import { useField } from '@/offline/useField'
import { sizeLabel } from '@/utils/fieldPack'
import { ErrorMessage } from 'frappe-ui'
import { computed, onMounted, ref } from 'vue'
import LucideChevronRight from '~icons/lucide/chevron-right'
import LucideDownload from '~icons/lucide/download'
import LucideFileText from '~icons/lucide/file-text'

const { pack } = useField()
const failed = ref(null)
const failure = ref('')

onMounted(loadSavedSheets)

const sheets = computed(() =>
  (pack.value?.sheets ?? []).map((sheet) => {
    const held = savedSheets.byName[sheet.name]
    const stale = !!held && held.modified !== sheet.modified
    const count = sheet.pages?.length ?? 0
    const pages = count === 1 ? __('1 page') : __('{0} pages', [count])
    return {
      ...sheet,
      kept: !!held,
      stale,
      // a kept sheet opens anywhere; any other needs the server for its pages
      openable: !!held || connectivity.online,
      meta: [
        pages,
        held
          ? stale
            ? __('On this device, a newer version is available')
            : __('On this device · {0}', [sizeLabel(held.bytes)])
          : __('Not on this device'),
      ].join(' · '),
    }
  }),
)

async function keep(sheet) {
  failed.value = null
  try {
    await keepSheet(sheet)
  } catch (error) {
    failed.value = sheet.name
    failure.value = error.message
  }
}
</script>
