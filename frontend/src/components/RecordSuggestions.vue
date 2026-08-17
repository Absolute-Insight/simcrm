<template>
  <div class="flex flex-col gap-3 border-b px-4 py-3 sm:px-6">
    <div class="flex items-center justify-between gap-2">
      <div class="text-sm text-ink-gray-5">{{ heading }}</div>
      <Skeleton
        v-if="healthLoading"
        shape="block"
        width="4rem"
        height="0.875rem"
        :label="__('Loading deal health')"
      />
    </div>

    <!-- Deal health. A meter and a severity word, not a colour-coded integer:
         the range and its direction have to be on screen, and the severity has
         to survive greyscale and colour blindness. Note the polarity — high is
         healthy here, while a suggestion's urgency runs the other way. -->
    <div v-if="band" class="flex flex-col gap-1.5">
      <div class="flex items-baseline justify-between gap-2">
        <span class="text-sm font-medium" :class="band.ink">
          {{ band.label }}
        </span>
        <span class="text-sm text-ink-gray-6">
          <span class="font-medium text-ink-gray-8">{{ percent }}</span
          ><span class="text-ink-gray-5">/100</span>
        </span>
      </div>
      <div
        class="h-1 w-full overflow-hidden rounded-full bg-surface-gray-3"
        role="meter"
        :aria-valuenow="percent"
        aria-valuemin="0"
        aria-valuemax="100"
        :aria-label="__('Deal health')"
      >
        <div
          class="h-full rounded-full"
          :class="band.fill"
          :style="fillStyle"
        />
      </div>
      <span class="text-xs text-ink-gray-5">
        {{ __('Deal health — higher is healthier.') }}
      </span>
    </div>

    <!-- The named deductions behind the score, so the number is explainable
         rather than just asserted. -->
    <ul v-if="healthFactors.length" class="flex flex-col gap-1">
      <li
        v-for="factor in healthFactors"
        :key="factor.key"
        class="text-sm leading-5 text-ink-gray-6"
      >
        {{ factor.label }}
      </li>
    </ul>

    <ErrorState
      v-if="health.error && !band"
      compact
      :error="health.error"
      :title="__('Could not load deal health')"
      :retry="reloadHealth"
    />

    <!-- Thread summary. On demand rather than on load: it costs a model call
         per press, it is rate limited per user and capped by a daily budget,
         and most record visits do not want one.

         Everything the model produced is rendered as text. It is written from
         a thread a counterparty contributed to, so it is attacker-influenced
         input -- feats/agent/README.md records that every model tested follows
         instructions embedded in an email. There is no v-html here and there
         must never be one. -->
    <div class="flex flex-col gap-2">
      <div class="flex items-center justify-between gap-2">
        <span class="text-sm text-ink-gray-5">{{ __('Thread summary') }}</span>
        <Button
          :label="summary ? __('Summarise again') : __('Summarise thread')"
          :loading="summarising"
          size="sm"
          variant="subtle"
          @click="summariseThread"
        />
      </div>

      <p v-if="summaryNotice" class="text-sm leading-5 text-ink-gray-6">
        {{ summaryNotice }}
      </p>

      <template v-if="summary">
        <p class="text-sm leading-5 text-ink-gray-7">{{ summary.summary }}</p>

        <span v-if="sentiment" class="text-sm text-ink-gray-6">
          {{ sentiment }}
        </span>

        <ul
          v-if="summary.next_steps?.length"
          class="flex list-disc flex-col gap-1 pl-4"
        >
          <li
            v-for="(step, index) in summary.next_steps"
            :key="index"
            class="text-sm leading-5 text-ink-gray-6"
          >
            {{ step }}
          </li>
        </ul>

        <span class="text-xs text-ink-gray-5">
          {{
            __(
              'Written by the assistant from the emails on this record. Check it against the thread before acting on it.',
            )
          }}
        </span>
      </template>
    </div>

    <div v-if="suggestionsLoading" class="flex flex-col gap-2">
      <Skeleton
        shape="text"
        width="80%"
        :label="__('Loading suggestions for this record')"
      />
      <Skeleton shape="text" width="60%" />
    </div>

    <ErrorState
      v-else-if="recordSuggestions.error && !rows.length"
      compact
      :error="recordSuggestions.error"
      :title="__('Could not load suggestions')"
      :retry="reloadSuggestions"
    />

    <div
      v-for="s in rows"
      :key="s.name"
      class="flex flex-col gap-1.5 rounded-5 bg-surface-gray-1 px-3 py-2"
    >
      <div class="flex items-center justify-between gap-2">
        <div class="min-w-0 text-base text-ink-gray-8">{{ s.title }}</div>
        <div class="flex shrink-0 gap-1">
          <Button
            variant="subtle"
            size="sm"
            :label="acceptLabel(s.suggested_action)"
            :loading="busy === s.name"
            @click="accept(s)"
          />
          <Button
            variant="ghost"
            size="sm"
            icon="lucide-x"
            :tooltip="__('Dismiss')"
            :aria-label="__('Dismiss')"
            :disabled="busy === s.name"
            @click="dismiss(s)"
          />
        </div>
      </div>
      <div v-if="s.rationale" class="text-sm leading-5 text-ink-gray-6">
        {{ s.rationale }}
      </div>
    </div>

    <!-- Only shown once both calls have resolved with nothing. The panel used
         to hide itself whenever a call failed, which read as "no risks here". -->
    <div
      v-if="isSettledEmpty"
      class="text-sm leading-5 text-ink-gray-5"
      role="status"
    >
      {{ __('Nothing flagged on this record.') }}
    </div>
  </div>
</template>
<script setup>
import ErrorState from '@/components/ui/ErrorState.vue'
import Skeleton from '@/components/ui/Skeleton.vue'
import { Button, call, createResource } from 'frappe-ui'
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { suggestionsStore } from '@/stores/suggestions'
import { globalStore } from '@/stores/global'
import {
  acceptLabel,
  healthBand,
  healthMeterPercent,
  isSummaryUsable,
  sentimentLabel,
  summaryStatusMessage,
} from '@/utils/suggestions'

const props = defineProps({
  doctype: { type: String, required: true },
  docname: { type: String, required: true },
})

const { acceptSuggestion, dismissSuggestion } = suggestionsStore()
const { $socket } = globalStore()

const busy = ref('')

const summary = ref(null)
const summarising = ref(false)
const summaryNotice = ref('')

const sentiment = computed(() => sentimentLabel(summary.value?.sentiment))

/* Degrades the way the rest of the agent tier does: a status, never an
   exception, and a sentence saying what to do instead. The endpoint returns
   `disabled` when the tier is off and `unavailable` when the model could not
   be reached or produced nothing schema-valid; neither is an error the rep
   caused, and the emails are still on the page either way. */
async function summariseThread() {
  summarising.value = true
  summaryNotice.value = ''
  try {
    const result = await call('crm.agent.api.summarise_thread', {
      reference_doctype: props.doctype,
      reference_name: props.docname,
    })
    if (isSummaryUsable(result)) {
      summary.value = result.summary
    } else {
      summary.value = null
      summaryNotice.value =
        summaryStatusMessage(result?.status) ||
        __('There was nothing on this record to summarise yet.')
    }
  } catch {
    // rate limit, budget, permission: all the same to a reader
    summary.value = null
    summaryNotice.value = summaryStatusMessage('unavailable')
  } finally {
    summarising.value = false
  }
}

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

const scoresDeal = computed(() => props.doctype === 'CRM Deal')

const rows = computed(() => recordSuggestions.data || [])

/**
 * The heading has to describe what is actually under it. A fixed "Needs
 * attention" sat above "Healthy 85/100" and nothing else, which contradicts
 * itself; on a lead there is no health score to head at all.
 */
const heading = computed(() => {
  if (rows.value.length) return __('Needs attention')
  return scoresDeal.value ? __('Deal health') : __('Signals')
})

const suggestionsLoading = computed(
  () =>
    recordSuggestions.loading &&
    !recordSuggestions.fetched &&
    !recordSuggestions.error,
)

const healthLoading = computed(
  () => scoresDeal.value && health.loading && !health.fetched && !health.error,
)

const band = computed(() =>
  health.data ? healthBand(health.data.score) : null,
)

const percent = computed(() => healthMeterPercent(health.data?.score))

const fillStyle = computed(() => ({ width: `${percent.value}%` }))

const healthFactors = computed(() =>
  (health.data?.factors || []).filter((factor) => factor?.label),
)

/* "Nothing flagged" is a claim, so it waits for both calls to have actually
   succeeded. An in-flight or failed call is never allowed to produce it. */
const isSettledEmpty = computed(() => {
  if (rows.value.length || band.value) return false
  const suggestionsSettled =
    recordSuggestions.fetched && !recordSuggestions.error
  const healthSettled = !scoresDeal.value || (health.fetched && !health.error)
  return suggestionsSettled && healthSettled
})

function reloadSuggestions() {
  return recordSuggestions.reload().catch(() => {})
}

function reloadHealth() {
  return health.reload().catch(() => {})
}

function refresh() {
  reloadSuggestions()
  if (scoresDeal.value) reloadHealth()
}

watch(() => props.docname, refresh)

/* Same event the inbox listens to, so an accepted or expired suggestion leaves
   the record panel without a reload. Unsubscribed by reference: the inbox is
   usually mounted at the same time on the same event name. */
function onSuggestionEvent() {
  refresh()
}

onMounted(() => $socket.on('crm_suggestion', onSuggestionEvent))
onBeforeUnmount(() => $socket.off('crm_suggestion', onSuggestionEvent))

async function accept(suggestion) {
  busy.value = suggestion.name
  try {
    const done = await acceptSuggestion(suggestion)
    if (done) refresh()
  } finally {
    busy.value = ''
  }
}

async function dismiss(suggestion) {
  busy.value = suggestion.name
  try {
    const done = await dismissSuggestion(suggestion)
    if (done) refresh()
  } finally {
    busy.value = ''
  }
}
</script>
