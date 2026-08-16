<template>
  <Transition name="panel-slide">
    <div
      v-if="suggestionsVisible"
      ref="target"
      class="absolute z-20 h-screen bg-surface-base"
      :style="{
        'box-shadow': 'var(--elevation-lg)',
        'max-width': 'min(400px, 100vw)',
        'min-width': 'min(400px, 100vw)',
        left: 'calc(100% + 1px)',
      }"
    >
      <div class="flex h-screen flex-col text-ink-gray-9">
        <div class="flex items-center justify-between">
          <div class="v-title-sm text-ink-gray-8 px-4 pt-[15px] pb-3">
            {{ __('Suggestions') }}
          </div>
          <Button
            class="mr-3"
            :tooltip="__('Refresh')"
            :aria-label="__('Refresh')"
            icon="lucide-refresh-cw"
            variant="ghost"
            :loading="suggestions.loading"
            @click="reload()"
          />
        </div>

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

            <div
              class="divide-y divide-outline-elevation-2 overflow-auto text-base"
            >
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
      </div>
    </div>
  </Transition>
</template>
<script setup>
import LucideSparkles from '~icons/lucide/sparkles'
import EmptyState from '@/components/ListViews/EmptyState.vue'
import ErrorState from '@/components/ui/ErrorState.vue'
import Skeleton from '@/components/ui/Skeleton.vue'
import {
  suggestionsVisible,
  suggestions,
  openCount,
  suggestionsStore,
} from '@/stores/suggestions'
import { globalStore } from '@/stores/global'
import { formatDate, timeAgo } from '@/utils'
import {
  acceptLabel,
  parseFactors,
  referenceTypeLabel,
  suggestionRoute,
  urgencyBand,
} from '@/utils/suggestions'
import { onClickOutside } from '@vueuse/core'
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { RouterLink } from 'vue-router'

const {
  toggle,
  reload,
  acceptSuggestion,
  dismissSuggestion,
  referenceLabelFor,
} = suggestionsStore()
const { $socket } = globalStore()

const target = ref(null)
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

onClickOutside(
  target,
  () => {
    if (suggestionsVisible.value) toggle()
  },
  {
    ignore: ['#suggestions-btn', '.field-layout-dialog', '[role="dialog"]'],
  },
)

/* The signal engine publishes one event per affected user per run
   (crm.agent.signals.publish_new_suggestions), so the inbox refreshes itself
   instead of being right only when clicked. The handler is passed to `off` by
   reference because RecordSuggestions listens to the same event — a bare
   `off('crm_suggestion')` would unsubscribe both. */
function onSuggestionEvent() {
  reload()
}

onMounted(() => $socket.on('crm_suggestion', onSuggestionEvent))
onBeforeUnmount(() => $socket.off('crm_suggestion', onSuggestionEvent))

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
  if (rowLink(suggestion).is === RouterLink) toggle()
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

<style scoped>
/* The panel used to carry `transition-all` on a v-if element, which animates
   nothing — an element that does not exist has no property to transition from.
   A real transition needs the element wrapped. */
.panel-slide-enter-active,
.panel-slide-leave-active {
  transition:
    transform var(--motion-slow) var(--motion-ease-out),
    opacity var(--motion-slow) var(--motion-ease-out);
}

.panel-slide-enter-from,
.panel-slide-leave-to {
  transform: translateX(-8px);
  opacity: 0;
}
</style>
