<template>
  <div v-if="hasContent" class="flex flex-col gap-2 border-b sm:px-6 py-3 px-4">
    <div class="flex items-center justify-between">
      <div class="text-sm text-ink-gray-5">{{ __('Needs attention') }}</div>
      <Badge
        v-if="health.data"
        :label="String(health.data.score)"
        variant="subtle"
        :theme="healthTheme"
      />
    </div>

    <div v-if="health.data?.factors?.length" class="flex flex-col gap-1">
      <div
        v-for="factor in health.data.factors"
        :key="factor.key"
        class="text-sm leading-5 text-ink-gray-6"
      >
        {{ factor.label }}
      </div>
    </div>

    <div
      v-for="s in recordSuggestions.data"
      :key="s.name"
      class="flex items-center justify-between gap-2"
    >
      <div class="text-base text-ink-gray-8 truncate">{{ s.title }}</div>
      <div class="flex shrink-0 gap-1">
        <Button
          variant="subtle"
          size="sm"
          :label="__('Do it')"
          @click="accept(s)"
        />
        <Button
          variant="ghost"
          size="sm"
          icon="x"
          :tooltip="__('Dismiss')"
          @click="dismiss(s)"
        />
      </div>
    </div>
  </div>
</template>
<script setup>
import { createResource, Badge } from 'frappe-ui'
import { computed, watch } from 'vue'
import { suggestionsStore } from '@/stores/suggestions'

const props = defineProps({
  doctype: { type: String, required: true },
  docname: { type: String, required: true },
})

const { acceptSuggestion, dismissSuggestion } = suggestionsStore()

const recordSuggestions = createResource({
  url: 'crm.api.suggestions.get_suggestions',
  makeParams: () => ({
    reference_doctype: props.doctype,
    reference_docname: props.docname,
  }),
  initialData: [],
  auto: true,
})

const health = createResource({
  url: 'crm.agent.predict.get_deal_health',
  makeParams: () => ({ name: props.docname }),
  auto: props.doctype === 'CRM Deal',
})

watch(
  () => props.docname,
  () => {
    recordSuggestions.reload()
    if (props.doctype === 'CRM Deal') health.reload()
  },
)

const hasContent = computed(
  () => recordSuggestions.data?.length || health.data?.factors?.length,
)

const healthTheme = computed(() => {
  const score = health.data?.score ?? 100
  if (score >= 70) return 'green'
  if (score >= 40) return 'orange'
  return 'red'
})

async function accept(suggestion) {
  const done = await acceptSuggestion(suggestion)
  if (done) recordSuggestions.reload()
}

async function dismiss(suggestion) {
  await dismissSuggestion(suggestion)
  recordSuggestions.reload()
}
</script>
