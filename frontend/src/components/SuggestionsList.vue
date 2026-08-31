<template>
  <div class="flex h-full flex-col overflow-hidden">
    <!-- First paint: shaped like the rows it stands in for, so the swap
         to real content is a fade rather than a jump. -->
    <div v-if="showSkeleton" class="flex flex-col">
      <div
        v-for="n in 3"
        :key="n"
        class="flex flex-col gap-2 border-b border-outline-gray-1 px-4 py-3"
      >
        <Skeleton
          shape="text"
          width="70%"
          :label="n === 1 ? __('Loading suggestions') : ''"
        />
        <Skeleton shape="text" :lines="2" size="sm" />
        <div class="flex gap-2 pt-1">
          <Skeleton shape="block" width="6.5rem" height="1.75rem" />
          <Skeleton shape="block" width="5rem" height="1.75rem" />
        </div>
      </div>
    </div>

    <!-- A failed fetch is not an empty inbox. Saying "all clear" here is
         the one thing this panel must never do. -->
    <ErrorState
      v-else-if="suggestions.error && !hasRows"
      compact
      :error="suggestions.error"
      :title="__('Could not load your suggestions')"
      :retry="reload"
    />

    <div v-else-if="hasRows" class="flex flex-col overflow-hidden">
      <!-- Rows we already had survive a failed refresh; the strip says the
           list may be out of date rather than pretending it is not. -->
      <div
        v-if="suggestions.error"
        class="flex items-center justify-between gap-2 border-b border-outline-gray-1 bg-surface-amber-1 px-4 py-2 text-sm text-ink-gray-7"
        role="status"
      >
        <span>{{ __('This list may be out of date.') }}</span>
        <Button
          variant="ghost"
          size="sm"
          :label="__('Retry')"
          @click="reload()"
        />
      </div>

      <div class="divide-y divide-outline-elevation-2 overflow-auto text-base">
        <div
          v-for="s in suggestions.data"
          :key="s.name"
          class="flex flex-col gap-2 px-4 py-3"
        >
          <component
            :is="rowLink(s).is"
            v-bind="rowLink(s).props"
            class="group flex flex-col gap-1"
            @click="onRowClick(s)"
          >
            <div class="flex items-start justify-between gap-2">
              <div
                class="font-medium text-ink-gray-9 group-hover:text-ink-gray-7"
              >
                {{ s.title }}
              </div>
              <!-- Urgency as a word, never as the raw score: the deal
                   health number on the record panel runs the opposite
                   way, and two bare integers with opposite polarity in
                   one product is a trap. -->
              <span
                v-if="urgencyOf(s)"
                class="flex shrink-0 items-center gap-1 pt-0.5 text-xs"
                :class="urgencyOf(s).ink"
                :title="__('How urgently this needs attention')"
              >
                <span
                  class="size-1.5 rounded-full bg-current"
                  aria-hidden="true"
                />
                {{ urgencyOf(s).label }}
              </span>
            </div>
            <div class="text-sm leading-5 text-ink-gray-6">
              {{ s.rationale }}
            </div>
            <div class="text-sm text-ink-gray-5">
              {{ referenceText(s) }} ·
              <span :title="formatDate(s.creation)">
                {{ timeAgo(s.creation) }}
              </span>
            </div>
          </component>

          <!-- The named factors behind the signal. Labels only: the keys
               are the engine's vocabulary, not the reader's. -->
          <ul
            v-if="factorsOf(s).length"
            class="flex flex-col gap-0.5 text-sm text-ink-gray-5"
          >
            <li
              v-for="factor in factorsOf(s)"
              :key="factor.key"
              class="flex items-start gap-1.5"
            >
              <span
                class="mt-[7px] size-1 shrink-0 rounded-full bg-surface-gray-4"
                aria-hidden="true"
              />
              <span>{{ factor.label }}</span>
            </li>
          </ul>

          <div class="flex gap-2">
            <Button
              variant="subtle"
              :label="acceptLabel(s.suggested_action)"
              :loading="busy === s.name"
              @click="accept(s)"
            />
            <Button
              variant="ghost"
              :label="__('Dismiss')"
              :disabled="busy === s.name"
              @click="dismiss(s)"
            />
          </div>
        </div>

        <!-- The badge counts everything open, the list is capped at what
             the endpoint returns. Without this the list just stops, and a
             rep with 300 open signals reads the last card as the last
             signal. -->
        <div
          v-if="hiddenCount"
          class="px-4 py-3 text-sm text-ink-gray-5"
          role="status"
        >
          {{
            __('Showing the {0} most urgent of {1} open suggestions.', [
              suggestions.data.length,
              openCount.data,
            ])
          }}
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
</template>

<script setup>
/* The suggestion inbox itself, with no opinion about the frame around it.
   Extracted so the desktop slide-over and the mobile page are the same list:
   the accept/dismiss flow and the "not an empty inbox" error handling are the
   parts that must not diverge between them. */
import { PhSparkle as LucideSparkles } from '@phosphor-icons/vue'
import EmptyState from '@/components/ListViews/EmptyState.vue'
import ErrorState from '@/components/ui/ErrorState.vue'
import Skeleton from '@/components/ui/Skeleton.vue'
import { suggestions, openCount, suggestionsStore } from '@/stores/suggestions'
import { formatDate, timeAgo } from '@/utils'
import {
  acceptLabel,
  parseFactors,
  referenceTypeLabel,
  suggestionRoute,
  urgencyBand,
} from '@/utils/suggestions'
import { computed, ref } from 'vue'
import { RouterLink } from 'vue-router'

const props = defineProps({
  /* Called when a row navigates away. The slide-over uses it to close itself;
     the mobile page is already the destination, so it does nothing there. */
  onNavigate: { type: Function, default: () => {} },
})

const { reload, acceptSuggestion, dismissSuggestion, referenceLabelFor } =
  suggestionsStore()
const busy = ref('')

// Only the first three: the factor list explains the signal, it is not a report.
const MAX_FACTORS = 3

const hasRows = computed(() => Boolean(suggestions.data?.length))

const hiddenCount = computed(() =>
  Math.max(0, (openCount.data || 0) - (suggestions.data?.length || 0)),
)

const showSkeleton = computed(
  () => suggestions.loading && !suggestions.fetched && !suggestions.error,
)

function rowLink(suggestion) {
  const to = suggestionRoute(
    suggestion.reference_doctype,
    suggestion.reference_docname,
  )
  // An unmapped doctype has no page in this app, so the row is text. It used to
  // be a link to the Lead page regardless, which opened the wrong record.
  return to ? { is: RouterLink, props: { to } } : { is: 'div', props: {} }
}

function onRowClick(suggestion) {
  if (rowLink(suggestion).is === RouterLink) props.onNavigate()
}

function referenceText(suggestion) {
  const type = referenceTypeLabel(suggestion.reference_doctype)
  const label =
    referenceLabelFor(suggestion) || suggestion.reference_docname || ''
  return label ? `${type} · ${label}` : type
}

function factorsOf(suggestion) {
  return parseFactors(suggestion.factors).slice(0, MAX_FACTORS)
}

function urgencyOf(suggestion) {
  return urgencyBand(suggestion.score)
}

async function accept(suggestion) {
  busy.value = suggestion.name
  try {
    await acceptSuggestion(suggestion)
  } finally {
    busy.value = ''
  }
}

async function dismiss(suggestion) {
  busy.value = suggestion.name
  try {
    await dismissSuggestion(suggestion)
  } finally {
    busy.value = ''
  }
}
</script>
