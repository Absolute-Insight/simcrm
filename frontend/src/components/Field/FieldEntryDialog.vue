<!--
  Capturing something in field mode: a visit, an outcome, a cancellation, a
  note, a task. One dialog, because they are one act -- say what happened and
  put it down -- and each differs only in which two or three things it asks.

  Saving puts the entry in the outbox (offline/outbox.js). It is on the device
  before this closes, whether or not there is a network to send it over.
-->
<template>
  <Dialog v-model:open="fieldDialog.open" :title="form.title">
    <template #default>
      <form class="flex flex-col gap-4" @submit.prevent="save">
        <p v-if="form.lead" class="text-p-base text-ink-gray-7">
          {{ form.lead }}
        </p>

        <FormControl
          v-if="kind === 'log'"
          v-model="values.activity_type"
          type="select"
          :label="__('Activity')"
          :options="activityOptions"
        />

        <!-- The customer: fixed when the screen already knew it, otherwise
             searched in the copy on the device -- no server to ask. -->
        <div v-if="kind === 'log'" class="flex flex-col gap-1.5">
          <span class="text-xs text-ink-gray-5">
            {{ needsCustomer ? __('Customer') : __('Customer (optional)') }}
          </span>
          <div
            v-if="values.organization"
            class="flex min-h-10 items-center justify-between gap-2 rounded-5 bg-surface-gray-2 px-3"
          >
            <span class="truncate text-base text-ink-gray-9">
              {{ customerName(values.organization) }}
            </span>
            <Button
              v-if="!context.organization"
              variant="ghost"
              icon="lucide-x"
              :aria-label="__('Choose another customer')"
              @click="values.organization = ''"
            />
          </div>
          <template v-else>
            <TextInput
              v-model="customerQuery"
              type="search"
              size="lg"
              autocomplete="off"
              :placeholder="__('Search customers')"
              :aria-label="__('Search customers')"
            />
            <ul
              v-if="customerQuery.trim()"
              class="flex max-h-48 flex-col overflow-y-auto rounded-5 border"
            >
              <li v-for="org in matches" :key="org.name">
                <button
                  type="button"
                  class="flex min-h-11 w-full items-center px-3 text-left text-base text-ink-gray-8 hover:bg-surface-gray-2 focus-visible:bg-surface-gray-2 focus-visible:outline-none"
                  @click="pickCustomer(org)"
                >
                  <span class="truncate">
                    {{ org.organization_name || org.name }}
                  </span>
                </button>
              </li>
              <li
                v-if="!matches.length"
                class="px-3 py-2.5 text-p-base text-ink-gray-6"
              >
                {{ __('No customer on this device matches.') }}
              </li>
            </ul>
          </template>
        </div>

        <FormControl
          v-if="kind === 'note' && aboutOptions.length > 1"
          v-model="values.about"
          type="select"
          :label="__('About')"
          :options="aboutOptions"
        />

        <FormControl
          v-if="kind === 'task'"
          v-model="values.title"
          type="text"
          :label="__('Task')"
          :placeholder="__('What needs doing')"
          maxlength="140"
        />
        <FormControl
          v-if="kind === 'task'"
          v-model="values.due_date"
          type="date"
          :label="__('Due (optional)')"
        />

        <FormControl
          v-model="values.text"
          type="textarea"
          :rows="5"
          :label="form.textLabel"
          :placeholder="form.textPlaceholder"
          maxlength="5000"
        />

        <ErrorMessage :message="problem" />
      </form>
    </template>
    <template #actions>
      <div class="flex items-center justify-between gap-3">
        <span class="min-w-0 text-sm text-ink-gray-6">
          {{
            connectivity.online
              ? ''
              : __(
                  'No connection. It is saved here and sent when there is one.',
                )
          }}
        </span>
        <Button
          variant="solid"
          class="shrink-0"
          :label="form.action"
          :loading="saving"
          @click="save"
        />
      </div>
    </template>
  </Dialog>
</template>

<script setup>
import { connectivity } from '@/offline/connectivity'
import { fieldDialog } from '@/offline/fieldDialog'
import { enqueue } from '@/offline/outbox'
import { useField } from '@/offline/useField'
import { entryProblem } from '@/utils/fieldOutbox'
import { searchCustomers } from '@/utils/fieldPack'
import { activityLabel, LOGGABLE_TYPES } from '@/utils/planner'
import { Dialog, ErrorMessage, FormControl, TextInput, toast } from 'frappe-ui'
import { computed, reactive, ref, watch } from 'vue'

const { pack, index } = useField()

const kind = computed(() => fieldDialog.kind)
const context = computed(() => fieldDialog.context ?? {})

const values = reactive({
  activity_type: 'Unplanned Meeting',
  organization: '',
  about: '',
  title: '',
  due_date: '',
  text: '',
})
const customerQuery = ref('')
const problem = ref('')
const saving = ref(false)

// a fresh form each time it opens, seeded with what the screen knew
watch(
  () => fieldDialog.open,
  (open) => {
    if (!open) return
    Object.assign(values, {
      activity_type: 'Unplanned Meeting',
      organization: context.value.organization || '',
      about: context.value.organization
        ? `CRM Organization::${context.value.organization}`
        : '',
      title: '',
      due_date: '',
      text: '',
    })
    customerQuery.value = ''
    problem.value = ''
    saving.value = false
  },
)

function customerName(name) {
  return index.value.byName.get(name)?.organization_name || name
}

/* What the server will accept as logged after the fact, in the Planner's own
   words for each (the pack carries the list; the labels are the app's). */
const activityOptions = computed(() => {
  const allowed = pack.value?.rules?.loggable_types
  return LOGGABLE_TYPES.filter(
    (type) => !allowed || allowed.includes(type.value),
  ).map((type) => ({ label: __(type.label), value: type.value }))
})

const needsCustomer = computed(() =>
  (pack.value?.rules?.event_kinds ?? []).includes(values.activity_type),
)

const matches = computed(
  () => searchCustomers(pack.value?.organizations, customerQuery.value, 8).rows,
)

function pickCustomer(org) {
  values.organization = org.name
  customerQuery.value = ''
}

/* A note is about the customer, or about one of its open deals -- where it
   then shows on the deal's own page in the full app. */
const aboutOptions = computed(() => {
  const org = context.value.organization
  if (!org) return []
  return [
    { label: customerName(org), value: `CRM Organization::${org}` },
    ...(index.value.deals.get(org) ?? []).map((deal) => ({
      label: __('Deal {0}', [deal.name]),
      value: `CRM Deal::${deal.name}`,
    })),
  ]
})

const form = computed(() => {
  const item = context.value.item
  const what = item
    ? item.note ||
      customerName(item.organization) ||
      __(activityLabel(item.activity_type))
    : ''
  switch (kind.value) {
    case 'complete':
      return {
        title: __('Log the outcome'),
        lead: what,
        textLabel: __('What happened'),
        textPlaceholder: __('Who you saw, what was agreed, what comes next'),
        action: __('Mark as done'),
      }
    case 'cancel':
      return {
        title: __('Cancel this activity'),
        lead: what,
        textLabel: __('Why it was cancelled'),
        textPlaceholder: __('The customer moved it, the plant was shut…'),
        action: __('Cancel activity'),
      }
    case 'note':
      return {
        title: __('Add a note'),
        lead: '',
        textLabel: __('Note'),
        textPlaceholder: __('Something worth knowing next time'),
        action: __('Save note'),
      }
    case 'task':
      return {
        title: __('New task'),
        lead: '',
        textLabel: __('Details (optional)'),
        textPlaceholder: '',
        action: __('Add task'),
      }
    case 'close_task':
      return {
        title: __('Mark task as done'),
        lead: context.value.task?.title || '',
        textLabel: __('How it was finished'),
        textPlaceholder: '',
        action: __('Mark as done'),
      }
    default:
      return {
        title: __('Log activity'),
        lead: '',
        textLabel: __('What happened'),
        textPlaceholder: __('Who you saw, what was agreed, what comes next'),
        action: __('Log activity'),
      }
  }
})

/* The outbox action and payload this form stands for. */
function entry() {
  const text = values.text.trim()
  switch (kind.value) {
    case 'complete':
      return ['complete_item', { item: context.value.item.name, outcome: text }]
    case 'cancel':
      return ['cancel_item', { item: context.value.item.name, reason: text }]
    case 'note': {
      const [doctype, name] = values.about.split('::')
      return [
        'add_note',
        { reference_doctype: doctype, reference_docname: name, content: text },
      ]
    }
    case 'task':
      return [
        'create_task',
        {
          title: values.title.trim(),
          due_date: values.due_date || null,
          description: text,
        },
      ]
    case 'close_task':
      return [
        'close_task',
        { task: context.value.task.name, closing_note: text },
      ]
    default:
      return [
        'log_activity',
        {
          activity_type: values.activity_type,
          organization: values.organization || null,
          note: text,
        },
      ]
  }
}

async function save() {
  if (saving.value) return
  const [action, payload] = entry()
  problem.value = entryProblem(action, payload, pack.value?.rules)
  if (problem.value) return
  saving.value = true
  try {
    await enqueue(action, payload)
    fieldDialog.open = false
    toast.success(
      connectivity.online
        ? __('Saved')
        : __('Saved on this device. It will be sent when you are back online.'),
    )
  } catch (error) {
    problem.value = error.message
  } finally {
    saving.value = false
  }
}
</script>
