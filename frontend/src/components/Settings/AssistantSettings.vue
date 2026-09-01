<template>
  <div class="flex h-full flex-col gap-5 overflow-y-auto p-8">
    <div class="flex flex-col gap-1">
      <h2 class="v-title text-ink-gray-8">{{ __('Assistant') }}</h2>
      <p class="text-p-sm text-ink-gray-5">
        {{
          __(
            'One model endpoint behind the Mentor, the Assistant, the Analyst, thread summaries and reply drafts. Everything else — signals, deal health, the planner, digests and automation rules — keeps working with it switched off.',
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

        <!-- Tests the *saved* settings: base_url is the target of a server-side
             POST carrying the API key, so the endpoint reads it from the
             database rather than accepting one over the wire. -->
        <div class="flex flex-wrap items-center gap-3">
          <Button
            :label="__('Test connection')"
            :loading="testing"
            :disabled="dirty"
            @click="testConnection"
          />
          <span v-if="dirty" class="text-sm text-ink-gray-5">
            {{ __('Save your changes first — this tests the saved endpoint.') }}
          </span>
          <span
            v-else-if="testResult"
            class="text-sm"
            :class="testResult.ok ? 'text-ink-green-9' : 'text-ink-red-9'"
          >
            {{ testResult.message }}
          </span>
        </div>
        <p class="text-p-sm text-ink-gray-5">
          {{
            __(
              'Sends one real request and checks the reply follows the schema. Reaching the endpoint is not enough — a model that cannot do structured output connects fine and returns nothing usable. Works with the assistant switched off.',
            )
          }}
        </p>
      </section>

      <!-- What each chat surface may read. The Mentor reads the manual and
           needs no switch; these two are the grants an admin makes. -->
      <section class="flex flex-col gap-4 border-t border-outline-gray-1 pt-5">
        <div class="flex flex-col gap-1">
          <h3 class="text-base font-medium text-ink-gray-8">
            {{ __('Assistant & Analyst') }}
          </h3>
          <p class="text-p-sm text-ink-gray-5">
            {{
              __(
                'The Assistant answers reps from Settings → Knowledge. The Analyst answers administrators from Vectora’s own calculations, and from a connected ERP’s invoices and payments.',
              )
            }}
          </p>
        </div>
        <div class="flex flex-col gap-3">
          <Switch
            :model-value="!!draft.assistant_reads_products"
            size="sm"
            :label="__('Let the Assistant read the product catalogue')"
            :description="
              __(
                'Enabled products (name, code, description, standard rate) join the knowledge base when a rep asks.',
              )
            "
            @update:model-value="
              draft.assistant_reads_products = $event ? 1 : 0
            "
          />
          <Switch
            :model-value="!!draft.analyst_enabled"
            size="sm"
            :label="__('Allow the Analyst to read CRM and ERP data')"
            :description="
              __(
                'Administrators only. Off, the Analyst page answers nothing. It never writes, and every figure it shows is computed by Vectora, not by the model.',
              )
            "
            @update:model-value="draft.analyst_enabled = $event ? 1 : 0"
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
          <FormControl
            v-model.number="draft.max_open_per_user"
            type="number"
            :label="__('Most open suggestions per rep')"
            :description="
              __(
                'The inbox is a worklist, not a backlog. Lower-scoring suggestions past this limit expire instead of piling up.',
              )
            "
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
   Written as one call: the settings are a Single, and saving them field by
   field would leave the tier half-configured if the fourth write failed.
   api_key is deliberately absent — a Password field reads back masked, so
   round-tripping it would write the mask.

   Read through crm.agent.api.get_settings rather than frappe.client.get_value,
   which returns {} for a Single nobody has saved yet. That left every field
   here undefined, so the page showed "signals off" with four blank thresholds
   while the job was running on its defaults — and saving wrote that fiction
   back, zeroing the lot. */
const FIELDS = [
  'enabled',
  'base_url',
  'model',
  'timeout',
  'max_tokens',
  'daily_call_budget',
  'assistant_reads_products',
  'analyst_enabled',
  'signals_enabled',
  'idle_deal_days',
  'close_horizon_days',
  'suggestion_ttl_days',
  'dismiss_cooldown_days',
  'max_open_per_user',
]

const draft = reactive({})
const apiKey = ref('')
const saving = ref(false)
const saveNotice = ref('')
const testing = ref(false)
const testResult = ref(null)
let saved = {}

const settings = createResource({
  url: 'crm.agent.api.get_settings',
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

async function testConnection() {
  testing.value = true
  testResult.value = null
  try {
    testResult.value = await call('crm.agent.api.test_connection')
  } catch (error) {
    /* A rejection here is the call itself failing — permission, rate limit, a
       worker timeout. The endpoint reports a *reachability* failure as a normal
       result, so these are different problems and must not read alike. */
    testResult.value = {
      ok: false,
      message:
        describeError(error).message ||
        __('Could not run the test. Try again in a moment.'),
    }
  } finally {
    testing.value = false
  }
}

async function save() {
  saving.value = true
  saveNotice.value = ''
  testResult.value = null
  try {
    /* Never send a field we have no value for. set_value writes undefined to a
       Check or an Int as 0, so one field missing from the read is enough to
       switch signals off behind the admin's back. */
    const payload = Object.fromEntries(
      FIELDS.filter((f) => draft[f] !== undefined && draft[f] !== null).map(
        (f) => [f, draft[f]],
      ),
    )
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
