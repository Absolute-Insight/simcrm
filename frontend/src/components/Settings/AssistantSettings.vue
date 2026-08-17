<template>
  <div class="flex h-full flex-col gap-5 overflow-y-auto">
    <div class="flex flex-col gap-1">
      <h2 class="v-title text-ink-gray-8">{{ __('Assistant') }}</h2>
      <p class="text-p-sm text-ink-gray-5">
        {{
          __(
            'The assistant drafts replies and summarises threads. Everything else — signals, deal health, the planner, digests and automation rules — keeps working with it switched off.',
          )
        }}
      </p>
    </div>

    <div v-if="settings.loading" class="flex flex-col gap-3">
      <Skeleton shape="text" width="70%" :label="__('Loading settings')" />
      <Skeleton shape="block" width="100%" height="6rem" />
    </div>

    <ErrorState
      v-else-if="settings.error"
      :error="settings.error"
      :title="__('Could not load assistant settings')"
      :retry="() => settings.reload()"
    />

    <template v-else>
      <!-- Model tier -->
      <section class="flex flex-col gap-4">
        <div class="flex items-center gap-3">
          <Switch
            :model-value="!!draft.enabled"
            size="sm"
            :label="__('Enable the assistant')"
            @update:model-value="draft.enabled = $event ? 1 : 0"
          />
        </div>

        <div class="grid grid-cols-1 gap-4 sm:grid-cols-2">
          <FormControl
            v-model="draft.base_url"
            type="text"
            :label="__('Endpoint')"
            :description="
              __('An OpenAI-compatible base URL. Local models included.')
            "
            placeholder="http://ollama:11434/v1"
          />
          <FormControl
            v-model="draft.model"
            type="text"
            :label="__('Model')"
            :description="__('Exactly as the endpoint names it.')"
          />
          <FormControl
            v-model="apiKey"
            type="password"
            :label="__('API key')"
            :description="
              __(
                'Only if the endpoint needs one. Leave blank to keep the existing key.',
              )
            "
          />
          <FormControl
            v-model.number="draft.timeout"
            type="number"
            :label="__('Timeout (seconds)')"
            :description="timeoutHint"
          />
          <FormControl
            v-model.number="draft.max_tokens"
            type="number"
            :label="__('Max tokens')"
          />
          <FormControl
            v-model.number="draft.daily_call_budget"
            type="number"
            :label="__('Daily call budget')"
            :description="
              __('Calls per day across the whole site. 0 means no cap.')
            "
          />
        </div>
      </section>

      <!-- Signals: deliberately on the same page, and deliberately separate.
           These run with the assistant off, so an admin who never enables the
           model still owns these numbers. -->
      <section class="flex flex-col gap-4 border-t border-outline-gray-1 pt-5">
        <div class="flex flex-col gap-1">
          <h3 class="text-base font-medium text-ink-gray-8">
            {{ __('Signals') }}
          </h3>
          <p class="text-p-sm text-ink-gray-5">
            {{
              __(
                'What puts a suggestion in a rep’s inbox. These run whether or not the assistant is on.',
              )
            }}
          </p>
        </div>

        <div class="flex items-center gap-3">
          <Switch
            :model-value="!!draft.signals_enabled"
            size="sm"
            :label="__('Generate suggestions')"
            @update:model-value="draft.signals_enabled = $event ? 1 : 0"
          />
        </div>

        <div class="grid grid-cols-1 gap-4 sm:grid-cols-2">
          <FormControl
            v-model.number="draft.idle_deal_days"
            type="number"
            :label="__('Idle after (days)')"
            :description="__('Silence on a deal before it is worth a nudge.')"
          />
          <FormControl
            v-model.number="draft.close_horizon_days"
            type="number"
            :label="__('Closing soon (days)')"
          />
          <FormControl
            v-model.number="draft.suggestion_ttl_days"
            type="number"
            :label="__('Suggestions expire after (days)')"
          />
          <FormControl
            v-model.number="draft.dismiss_cooldown_days"
            type="number"
            :label="__('Cooldown after dismissal (days)')"
          />
        </div>
      </section>

      <!-- The evidence for the numbers above. A threshold reps keep rejecting
           is the one worth changing, and guessing at which is exactly what
           this endpoint was built to stop. -->
      <section class="flex flex-col gap-3 border-t border-outline-gray-1 pt-5">
        <div class="flex flex-col gap-1">
          <h3 class="text-base font-medium text-ink-gray-8">
            {{ __('What reps are rejecting') }}
          </h3>
          <p class="text-p-sm text-ink-gray-5">
            {{
              __(
                'Dismissals by signal, most-rejected first. A signal near the top is one to retune or switch off — the numbers above are the knobs.',
              )
            }}
          </p>
        </div>

        <Skeleton
          v-if="dismissals.loading"
          shape="block"
          width="100%"
          height="4rem"
          :label="__('Loading dismissals')"
        />

        <ErrorState
          v-else-if="dismissals.error"
          compact
          :error="dismissals.error"
          :title="__('Could not load dismissals')"
          :retry="() => dismissals.reload()"
        />

        <p v-else-if="!dismissalRows.length" class="text-sm text-ink-gray-5">
          {{
            __(
              'Nothing dismissed yet. This fills in as reps work the inbox — it is the feedback loop for the thresholds above.',
            )
          }}
        </p>

        <ul v-else class="flex flex-col gap-3">
          <li
            v-for="row in dismissalRows"
            :key="row.signal"
            class="flex flex-col gap-1"
          >
            <div class="flex items-baseline justify-between gap-3">
              <span class="text-sm font-medium text-ink-gray-8">
                {{ row.signal }}
              </span>
              <span class="shrink-0 text-sm tabular-nums text-ink-gray-6">
                {{ __('{0} dismissed', [row.dismissals]) }}
              </span>
            </div>
            <!-- Reasons are free text a rep typed. Rendered as text. -->
            <p
              v-for="(reason, index) in row.reasons"
              :key="index"
              class="text-sm leading-5 text-ink-gray-5"
            >
              {{ reason }}
            </p>
          </li>
        </ul>
      </section>

      <div
        class="flex items-center justify-end gap-3 border-t border-outline-gray-1 pt-4"
      >
        <span v-if="saveNotice" class="text-sm text-ink-gray-6">
          {{ saveNotice }}
        </span>
        <Button
          :label="__('Save')"
          variant="solid"
          :loading="saving"
          :disabled="!dirty"
          @click="save"
        />
      </div>
    </template>
  </div>
</template>

<script setup>
import ErrorState from '@/components/ui/ErrorState.vue'
import Skeleton from '@/components/ui/Skeleton.vue'
import { Button, FormControl, Switch, call, createResource } from 'frappe-ui'
import { computed, reactive, ref, watch } from 'vue'
import { describeError } from '@/utils/describeError'

/* Every field on CRM Agent Settings that an operator has a reason to change.
   Read as one call and written as one call: the settings are a Single, and
   saving them field by field would leave the tier half-configured if the
   fourth write failed. api_key is deliberately absent — a Password field
   reads back masked, so round-tripping it would write the mask. */
const FIELDS = [
  'enabled',
  'base_url',
  'model',
  'timeout',
  'max_tokens',
  'daily_call_budget',
  'signals_enabled',
  'idle_deal_days',
  'close_horizon_days',
  'suggestion_ttl_days',
  'dismiss_cooldown_days',
]

const draft = reactive({})
const apiKey = ref('')
const saving = ref(false)
const saveNotice = ref('')
let saved = {}

const settings = createResource({
  url: 'frappe.client.get_value',
  makeParams: () => ({
    doctype: 'CRM Agent Settings',
    fieldname: JSON.stringify(FIELDS),
  }),
  auto: true,
  onSuccess: (data) => {
    saved = { ...(data || {}) }
    Object.assign(draft, saved)
  },
})

const dismissals = createResource({
  url: 'crm.api.suggestions.get_dismissal_stats',
  initialData: [],
  auto: true,
})

const dismissalRows = computed(() => dismissals.data || [])

const dirty = computed(
  () =>
    Boolean(apiKey.value) ||
    FIELDS.some(
      (field) => String(draft[field] ?? '') !== String(saved[field] ?? ''),
    ),
)

/* The one setting with a constraint that lives outside this form: a call costs
   timeout x 2 (it retries once) and waits in a web worker, so a value past the
   reverse proxy's read timeout produces a failed request for the rep and a
   worker still burning afterwards. deploy/README.md carries the same warning. */
const timeoutHint = computed(() =>
  __(
    'A call may take twice this (it retries once) and holds a web worker. Keep twice this under your proxy’s read timeout — 120s by default, so roughly 55 here.',
  ),
)

watch(
  () => draft.timeout,
  () => {
    saveNotice.value = ''
  },
)

async function save() {
  saving.value = true
  saveNotice.value = ''
  try {
    const payload = Object.fromEntries(FIELDS.map((f) => [f, draft[f]]))
    if (apiKey.value) payload.api_key = apiKey.value
    await call('frappe.client.set_value', {
      doctype: 'CRM Agent Settings',
      name: 'CRM Agent Settings',
      fieldname: payload,
    })
    saved = { ...payload }
    delete saved.api_key
    apiKey.value = ''
    saveNotice.value = __('Saved.')
  } catch (error) {
    saveNotice.value =
      describeError(error).message ||
      __('Could not save. Check the values and try again.')
  } finally {
    saving.value = false
  }
}
</script>
