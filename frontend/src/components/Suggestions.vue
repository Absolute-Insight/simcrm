<template>
  <div
    v-if="suggestionsVisible"
    ref="target"
    class="absolute z-20 h-screen bg-surface-base transition-all duration-300 ease-in-out"
    :style="{
      'box-shadow': '8px 0px 8px rgba(0, 0, 0, 0.1)',
      'max-width': '400px',
      'min-width': '400px',
      left: 'calc(100% + 1px)',
    }"
  >
    <div class="flex h-screen flex-col text-ink-gray-9">
      <div class="flex justify-between items-center">
        <div class="text-lg-medium text-ink-gray-8 px-4 pt-[15px] pb-3">
          {{ __('Suggestions') }}
        </div>
        <Button
          class="mr-3"
          :tooltip="__('Refresh')"
          icon="refresh-cw"
          variant="ghost"
          @click="suggestions.reload()"
        />
      </div>
      <div class="flex h-full flex-col overflow-hidden">
        <div
          v-if="suggestions.data?.length"
          class="divide-y divide-outline-elevation-2 overflow-auto text-base"
        >
          <div
            v-for="s in suggestions.data"
            :key="s.name"
            class="flex flex-col gap-2 px-4 py-3"
          >
            <RouterLink
              :to="getRoute(s)"
              class="group flex flex-col gap-1"
              @click="toggle()"
            >
              <div
                class="font-medium text-ink-gray-9 group-hover:text-ink-gray-7"
              >
                {{ s.title }}
              </div>
              <div class="text-sm leading-5 text-ink-gray-6">
                {{ s.rationale }}
              </div>
              <div class="text-sm text-ink-gray-5">
                {{ referenceLabel(s) }} · {{ __(timeAgo(s.creation)) }}
              </div>
            </RouterLink>
            <div class="flex gap-2">
              <Button
                variant="subtle"
                :label="acceptLabel(s)"
                @click="accept(s)"
              />
              <Button
                variant="ghost"
                :label="__('Dismiss')"
                @click="dismiss(s)"
              />
            </div>
          </div>
        </div>
        <EmptyState
          v-else
          :title="__('All clear')"
          :description="
            __(
              'Nothing needs your attention right now. New suggestions appear as deals and leads change.',
            )
          "
          :icon="LucideSparkles"
          width="lg"
        />
      </div>
    </div>
  </div>
</template>
<script setup>
import LucideSparkles from '~icons/lucide/sparkles'
import EmptyState from '@/components/ListViews/EmptyState.vue'
import {
  suggestionsVisible,
  suggestions,
  suggestionsStore,
} from '@/stores/suggestions'
import { timeAgo } from '@/utils'
import { onClickOutside } from '@vueuse/core'
import { ref } from 'vue'

const { toggle, acceptSuggestion, dismissSuggestion } = suggestionsStore()

const target = ref(null)

onClickOutside(
  target,
  () => {
    if (suggestionsVisible.value) toggle()
  },
  {
    ignore: ['#suggestions-btn', '.field-layout-dialog', '[role="dialog"]'],
  },
)

function getRoute(suggestion) {
  if (suggestion.reference_doctype === 'CRM Deal') {
    return { name: 'Deal', params: { dealId: suggestion.reference_docname } }
  }
  return { name: 'Lead', params: { leadId: suggestion.reference_docname } }
}

function referenceLabel(suggestion) {
  const doctype =
    suggestion.reference_doctype === 'CRM Deal' ? __('Deal') : __('Lead')
  return `${doctype} ${suggestion.reference_docname}`
}

function acceptLabel(suggestion) {
  return suggestion.suggested_action === 'create_task'
    ? __('Create task')
    : __('Accept')
}

async function accept(suggestion) {
  await acceptSuggestion(suggestion)
}

async function dismiss(suggestion) {
  await dismissSuggestion(suggestion)
}
</script>
