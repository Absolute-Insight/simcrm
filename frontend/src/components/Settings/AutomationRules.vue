<template>
  <div class="flex h-full flex-col gap-4">
    <div class="flex items-start justify-between gap-4">
      <div class="flex flex-col gap-1">
        <h2 class="v-title text-ink-gray-8">
          {{ __('Automation Rules') }}
        </h2>
        <p class="text-p-sm text-ink-gray-5">
          {{
            __(
              'When something happens to a lead or deal, do something about it. Rules are deterministic — they run whether or not the agent is enabled.',
            )
          }}
        </p>
      </div>
      <Button
        variant="solid"
        :label="__('New rule')"
        class="shrink-0"
        @click="openEditor(null)"
      >
        <template #prefix><LucidePlus class="size-4" /></template>
      </Button>
    </div>

    <div v-if="rules.loading" class="flex flex-1 items-center justify-center">
      <LoadingIndicator class="size-6" />
    </div>

    <ErrorMessage v-else-if="rules.error" :message="rules.error" />

    <div
      v-else-if="!rules.data?.length"
      class="flex flex-1 flex-col items-center justify-center gap-1 text-center"
    >
      <LucideWorkflow class="size-7 text-ink-gray-4" />
      <div class="text-base text-ink-gray-6">{{ __('No rules yet') }}</div>
      <div class="max-w-sm text-sm text-ink-gray-5">
        {{
          __(
            'A first rule worth having: when a deal reaches Negotiation, create a follow-up task for its owner.',
          )
        }}
      </div>
    </div>

    <div v-else class="min-h-0 flex-1 overflow-y-auto">
      <div
        v-for="rule in rules.data"
        :key="rule.name"
        class="group flex items-center gap-3 border-b border-outline-gray-1 px-1 py-2.5 last:border-b-0"
      >
        <Switch
          :model-value="!!rule.enabled"
          size="sm"
          @update:model-value="toggle(rule, $event)"
        />
        <button
          class="flex min-w-0 flex-1 flex-col items-start text-left"
          @click="openEditor(rule)"
        >
          <span class="truncate text-base text-ink-gray-8">
            {{ rule.title }}
          </span>
          <span class="truncate text-sm text-ink-gray-5">
            {{ describe(rule) }}
          </span>
        </button>
        <Badge
          v-if="!rule.enabled"
          :label="__('Paused')"
          variant="subtle"
          theme="gray"
        />
        <Button
          class="opacity-0 transition group-hover:opacity-100"
          variant="ghost"
          icon="lucide-trash-2"
          :aria-label="__('Delete rule')"
          @click="confirmDelete(rule)"
        />
      </div>
    </div>

    <Dialog
      v-model="editorOpen"
      :title="draft.name ? __('Edit rule') : __('New rule')"
      size="2xl"
    >
      <template #default>
        <div class="flex flex-col gap-4">
          <FormControl
            v-model="draft.title"
            :label="__('Name')"
            :placeholder="__('Follow up when a deal reaches Negotiation')"
          />

          <div class="grid grid-cols-2 gap-3">
            <FormControl
              v-model="draft.document_type"
              type="select"
              :label="__('Applies to')"
              :options="documentTypes"
            />
            <FormControl
              v-model="draft.trigger"
              type="select"
              :label="__('When')"
              :options="triggers"
            />
          </div>

          <FormControl
            v-if="draft.trigger === 'Status Changed'"
            v-model="draft.to_status"
            type="select"
            :label="__('Status becomes')"
            :options="statusOptions"
            :description="__('Leave blank to fire on any status change.')"
          />

          <FormControl
            v-model="draft.condition"
            type="textarea"
            :label="__('Only if')"
            :placeholder="`doc.expected_deal_value > 50000`"
            :description="
              __(
                'Optional Python expression over doc. Left blank, the rule always fires.',
              )
            "
          />

          <div class="border-t border-outline-gray-1 pt-4">
            <div class="grid grid-cols-2 gap-3">
              <FormControl
                v-model="draft.action"
                type="select"
                :label="__('Then')"
                :options="actions"
              />
              <FormControl
                v-if="draft.action === 'Create Task'"
                v-model="draft.task_priority"
                type="select"
                :label="__('Priority')"
                :options="priorities"
              />
              <!-- The suggestion inbox is ordered by this, so without it every
                   rule's suggestion sat at the same urgency as every other and
                   an admin had no way to float a critical one. Description
                   names two built-in scores, because a 0-100 box with no
                   reference points is a number nobody can choose well. -->
              <FormControl
                v-if="draft.action === 'Create Suggestion'"
                v-model.number="draft.suggestion_score"
                type="number"
                min="0"
                max="100"
                :label="__('Urgency')"
                :description="
                  __(
                    '0-100, highest first. No next step scores 40; a breached SLA scores 80.',
                  )
                "
              />
            </div>

            <FormControl
              v-model="draft.title_template"
              class="mt-3"
              :label="__('Title')"
              :placeholder="__('Follow up on {{ doc.organization }}')"
            />
            <FormControl
              v-model="draft.description_template"
              class="mt-3"
              type="textarea"
              :label="__('Details')"
            />

            <div class="mt-3 flex items-center gap-4">
              <FormControl
                v-if="draft.action === 'Create Task'"
                v-model="draft.due_in_days"
                type="number"
                :label="__('Due in (days)')"
                class="w-40"
              />
              <div class="flex items-center gap-2 pt-5">
                <!-- assign_to_owner is stored 0/1, and reka-ui's SwitchRoot
                     compares strictly against `true`: bound raw it looked on,
                     announced aria-checked="false", and ate the first click that
                     tried to turn it off. Coerced both ways, like the rule-list
                     switch above. `label` is what gives the control its
                     accessible name -- frappe-ui only renders the associated
                     label element when the prop is present. -->
                <Switch
                  :model-value="!!draft.assign_to_owner"
                  size="sm"
                  :label="__('Assign to the record owner')"
                  @update:model-value="draft.assign_to_owner = $event ? 1 : 0"
                />
              </div>
            </div>
          </div>

          <ErrorMessage :message="saveError" />
        </div>
      </template>
      <template #actions>
        <div class="flex justify-end gap-2">
          <Button :label="__('Cancel')" @click="editorOpen = false" />
          <Button
            variant="solid"
            :label="__('Save rule')"
            :loading="saving"
            @click="save"
          />
        </div>
      </template>
    </Dialog>
  </div>
</template>

<script setup>
import LucidePlus from '~icons/lucide/plus'
import LucideWorkflow from '~icons/lucide/workflow'
import {
  Badge,
  Button,
  Dialog,
  ErrorMessage,
  FormControl,
  LoadingIndicator,
  Switch,
  call,
  createListResource,
  createResource,
  toast,
} from 'frappe-ui'
import { computed, reactive, ref, watch } from 'vue'

/* Labels and values are separate here because the values are persisted on
   CRM Automation Rule and the labels are read by people. "CRM Deal" is the
   doctype's internal name; every other surface in the product calls it a Deal,
   and this dialog was the one place leaking the schema at the user. The value
   sent to the server is unchanged.

   Built as computeds so a language change re-resolves them, and so the
   extractor sees each string inside a literal __(). */
const documentTypes = computed(() => [
  { label: __('Deal'), value: 'CRM Deal' },
  { label: __('Lead'), value: 'CRM Lead' },
])
const documentTypeLabel = (value) =>
  documentTypes.value.find((option) => option.value === value)?.label || value

const triggers = computed(() => [
  { label: __('Created'), value: 'Created' },
  { label: __('Status Changed'), value: 'Status Changed' },
])
const actions = computed(() => [
  { label: __('Create Task'), value: 'Create Task' },
  { label: __('Create Suggestion'), value: 'Create Suggestion' },
])
const priorities = computed(() => [
  { label: __('Low'), value: 'Low' },
  { label: __('Medium'), value: 'Medium' },
  { label: __('High'), value: 'High' },
])

const EMPTY = {
  name: null,
  title: '',
  enabled: 1,
  document_type: 'CRM Deal',
  trigger: 'Status Changed',
  to_status: '',
  condition: '',
  action: 'Create Task',
  title_template: '',
  description_template: '',
  task_priority: 'Medium',
  suggestion_score: 60,
  due_in_days: 2,
  assign_to_owner: 1,
}

const rules = createListResource({
  doctype: 'CRM Automation Rule',
  fields: [
    'name',
    'title',
    'enabled',
    'document_type',
    'trigger',
    'to_status',
    'condition',
    'action',
    'title_template',
    'description_template',
    'task_priority',
    'suggestion_score',
    'due_in_days',
    'assign_to_owner',
  ],
  orderBy: 'modified desc',
  pageLength: 100,
  auto: true,
})

const editorOpen = ref(false)
const saving = ref(false)
const saveError = ref('')
const draft = reactive({ ...EMPTY })

const statuses = createResource({
  url: 'frappe.client.get_list',
  makeParams: () => ({
    doctype:
      draft.document_type === 'CRM Lead'
        ? 'CRM Lead Status'
        : 'CRM Deal Status',
    fields: ['name'],
    limit_page_length: 0,
  }),
})

watch(
  () => draft.document_type,
  () => editorOpen.value && statuses.reload(),
)

const statusOptions = computed(() => [
  { label: __('Any status'), value: '' },
  ...(statuses.data || []).map((s) => ({ label: s.name, value: s.name })),
])

function describe(rule) {
  const when =
    rule.trigger === 'Created'
      ? __('When created')
      : rule.to_status
        ? __('When status becomes {0}', [rule.to_status])
        : __('When status changes')
  const what =
    rule.action === 'Create Task'
      ? __('create a task')
      : __('raise a suggestion')
  return `${documentTypeLabel(rule.document_type)} · ${when} → ${what}`
}

function openEditor(rule) {
  Object.assign(draft, rule ? { ...EMPTY, ...rule } : { ...EMPTY })
  saveError.value = ''
  editorOpen.value = true
  statuses.reload()
}

async function save() {
  saveError.value = ''
  if (!draft.title?.trim()) {
    saveError.value = __('Give the rule a name.')
    return
  }
  saving.value = true
  const { name, ...values } = draft
  try {
    if (name) {
      await rules.setValue.submit({ name, ...values })
    } else {
      await rules.insert.submit(values)
    }
    await rules.reload()
    editorOpen.value = false
    toast.success(__('Rule saved'))
  } catch (error) {
    saveError.value = error.messages?.[0] || error.message
  } finally {
    saving.value = false
  }
}

async function toggle(rule, enabled) {
  try {
    await call('frappe.client.set_value', {
      doctype: 'CRM Automation Rule',
      name: rule.name,
      fieldname: 'enabled',
      value: enabled ? 1 : 0,
    })
    rule.enabled = enabled ? 1 : 0
  } catch (error) {
    toast.error(error.messages?.[0] || __('Could not change the rule'))
  }
}

async function confirmDelete(rule) {
  if (!window.confirm(__('Delete “{0}”? This cannot be undone.', [rule.title])))
    return
  try {
    await rules.delete.submit(rule.name)
    await rules.reload()
    toast.success(__('Rule deleted'))
  } catch (error) {
    toast.error(error.messages?.[0] || __('Could not delete the rule'))
  }
}
</script>
