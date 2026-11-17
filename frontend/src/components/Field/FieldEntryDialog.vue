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
          v-if="kind === 'log' || kind === 'plan'"
          v-model="values.activity_type"
          type="select"
          :label="__('Activity')"
          :options="activityOptions"
        />

        <!-- The customer: fixed when the screen already knew it, otherwise
             searched in the copy on the device -- no server to ask. -->
        <div
          v-if="kind === 'log' || kind === 'plan'"
          class="flex flex-col gap-1.5"
        >
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

        <!-- Photos and a voice note: kept on the phone with the note and sent
             with it, so they work with no signal at all. -->
        <div v-if="kind === 'note'" class="flex flex-col gap-2">
          <div
            v-if="photos.length || voice"
            class="flex flex-wrap items-center gap-2"
          >
            <div
              v-for="photo in photos"
              :key="photo.id"
              class="relative size-20 overflow-hidden rounded-5 bg-surface-gray-2"
            >
              <img
                :src="photo.url"
                :alt="__('Photo for this note')"
                class="size-full object-cover"
              />
              <button
                type="button"
                class="absolute right-1 top-1 flex size-6 items-center justify-center rounded-full bg-surface-gray-7/80 text-ink-white focus-visible:outline focus-visible:outline-2"
                :aria-label="__('Remove photo')"
                @click="removePhoto(photo)"
              >
                <LucideX class="size-3.5" aria-hidden="true" />
              </button>
            </div>
            <div
              v-if="voice"
              class="flex min-h-10 w-full items-center gap-2 rounded-5 bg-surface-gray-2 px-2"
            >
              <audio
                :src="voice.url"
                controls
                preload="metadata"
                class="h-9 min-w-0 flex-1"
                :aria-label="__('Voice note')"
              />
              <Button
                variant="ghost"
                icon="lucide-trash-2"
                :aria-label="__('Remove voice note')"
                @click="removeVoice"
              />
            </div>
          </div>

          <div
            v-if="recorder.state.value === 'recording'"
            class="flex min-h-10 items-center justify-between gap-2 rounded-5 bg-surface-red-1 px-3"
            role="status"
          >
            <span
              class="flex items-center gap-2 whitespace-nowrap text-base tabular-nums text-ink-red-9"
            >
              <span
                class="size-2 animate-pulse rounded-full bg-surface-red-5"
                aria-hidden="true"
              />
              <span class="sr-only sm:not-sr-only">{{ __('Recording') }}</span>
              {{ clock(recorder.elapsed.value) }} /
              {{ clock(MAX_VOICE_SECONDS) }}
            </span>
            <div class="flex gap-1">
              <Button
                variant="ghost"
                :label="__('Cancel')"
                @click="recorder.cancel()"
              />
              <Button
                variant="solid"
                :label="__('Stop')"
                icon-left="lucide-square"
                @click="recorder.stop()"
              />
            </div>
          </div>
          <div v-else class="flex flex-wrap gap-2">
            <Button
              :label="__('Add photo')"
              icon-left="lucide-camera"
              :disabled="photos.length >= MAX_PHOTOS || busyPhoto"
              :loading="busyPhoto"
              @click="photoInput?.click()"
            />
            <Button
              v-if="voiceNotesSupported()"
              :label="__('Record voice note')"
              icon-left="lucide-mic"
              :disabled="!!voice || recorder.state.value === 'starting'"
              @click="recorder.start()"
            />
            <input
              ref="photoInput"
              type="file"
              accept="image/*"
              capture="environment"
              class="hidden"
              @change="addPhotos"
            />
          </div>
          <p v-if="mediaHint" class="text-p-sm text-ink-gray-6">
            {{ mediaHint }}
          </p>
        </div>

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
import LucideX from '~icons/lucide/x'
import { voiceNotesSupported, useVoiceNote } from '@/composables/useVoiceNote'
import { connectivity } from '@/offline/connectivity'
import { fieldDialog } from '@/offline/fieldDialog'
import { enqueue, forgetMedia, keepMedia } from '@/offline/outbox'
import {
  MAX_PHOTOS,
  MAX_VOICE_SECONDS,
  clock,
  scalePhoto,
} from '@/utils/noteMedia'
import { newEntryId } from '@/utils/fieldOutbox'
import { useField } from '@/offline/useField'
import { entryProblem } from '@/utils/fieldOutbox'
import { searchCustomers, shortDate, weekdayName } from '@/utils/fieldPack'
import { activityLabel, LOGGABLE_TYPES, PLANNABLE_TYPES } from '@/utils/planner'
import { Dialog, ErrorMessage, FormControl, TextInput, toast } from 'frappe-ui'
import { computed, onBeforeUnmount, reactive, ref, watch } from 'vue'

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

/* The note's photos and voice note, until it is saved: { id, blob, url }.
   The object URLs are released whenever they leave the form. */
const photos = ref([])
const voice = ref(null)
const photoInput = ref(null)
const busyPhoto = ref(false)
const mediaProblem = ref('')

const release = (item) => item?.url && URL.revokeObjectURL(item.url)
const withUrl = (blob) => ({
  id: newEntryId(),
  blob,
  url: URL.createObjectURL(blob),
})

function clearMedia() {
  photos.value.forEach(release)
  release(voice.value)
  photos.value = []
  voice.value = null
  mediaProblem.value = ''
}

const recorder = useVoiceNote({
  onRecorded: ({ blob }) => {
    release(voice.value)
    voice.value = withUrl(blob)
  },
})

const mediaHint = computed(() => {
  if (mediaProblem.value) return mediaProblem.value
  switch (recorder.error.value) {
    case 'denied':
      return __('Allow the microphone for this site to record a voice note.')
    case 'unsupported':
      return __('This browser cannot record a voice note.')
    case 'nothing':
      return __('Nothing was recorded. Try again.')
    case 'large':
      return __('That recording is too large. Keep it under {0} minutes.', [
        MAX_VOICE_SECONDS / 60,
      ])
    default:
      return ''
  }
})

async function addPhotos(event) {
  const files = [...(event.target.files || [])]
  event.target.value = ''
  mediaProblem.value = ''
  busyPhoto.value = true
  try {
    for (const file of files) {
      if (photos.value.length >= MAX_PHOTOS) {
        mediaProblem.value = __('A note takes up to {0} photos.', [MAX_PHOTOS])
        break
      }
      try {
        photos.value = [...photos.value, withUrl(await scalePhoto(file))]
      } catch (error) {
        mediaProblem.value =
          error?.message || __('That photo could not be read.')
      }
    }
  } finally {
    busyPhoto.value = false
  }
}

function removePhoto(photo) {
  release(photo)
  photos.value = photos.value.filter((other) => other !== photo)
}

function removeVoice() {
  release(voice.value)
  voice.value = null
}

onBeforeUnmount(clearMedia)

// a fresh form each time it opens, seeded with what the screen knew
watch(
  () => fieldDialog.open,
  (open) => {
    if (!open) return
    Object.assign(values, {
      activity_type: kind.value === 'plan' ? 'Visit' : 'Unplanned Meeting',
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
    clearMedia()
  },
)

// closed without saving: a recording still going is thrown away
watch(
  () => fieldDialog.open,
  (open) => {
    if (!open) recorder.cancel()
  },
)

function customerName(name) {
  return index.value.byName.get(name)?.organization_name || name
}

/* What the server will accept as logged after the fact, in the Planner's own
   words for each (the pack carries the list; the labels are the app's). */
const activityOptions = computed(() => {
  const planning = kind.value === 'plan'
  const allowed = planning
    ? pack.value?.rules?.plannable_types
    : pack.value?.rules?.loggable_types
  return (planning ? PLANNABLE_TYPES : LOGGABLE_TYPES)
    .filter((type) => !allowed || allowed.includes(type.value))
    .map((type) => ({ label: __(type.label), value: type.value }))
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
    case 'plan':
      return {
        title: __('Plan an activity'),
        lead: __('For {0}', [
          `${weekdayName(context.value.date)} ${shortDate(context.value.date)}`,
        ]),
        textLabel: __('Note (optional)'),
        textPlaceholder: __('What it is for'),
        action: __('Add to plan'),
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
      // split once: a customer's name may itself contain the separator
      const cut = values.about.indexOf('::')
      const doctype = values.about.slice(0, cut)
      const name = values.about.slice(cut + 2)
      const media = [...photos.value, ...(voice.value ? [voice.value] : [])]
      return [
        'add_note',
        {
          reference_doctype: doctype,
          reference_docname: name,
          content: text,
          ...(media.length ? { media: media.map((item) => item.id) } : {}),
        },
      ]
    }
    case 'plan':
      return [
        'plan_item',
        {
          activity_type: values.activity_type,
          planned_date: context.value.date,
          organization: values.organization || null,
          note: text,
        },
      ]
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
  if (recorder.state.value === 'recording') {
    problem.value = __('Stop the recording first.')
    return
  }
  saving.value = true
  try {
    if (action === 'add_note') {
      // on the device before the entry that names them, so an entry never
      // points at a file the phone does not have
      await keepMedia([
        ...photos.value.map(({ id, blob }) => ({ id, kind: 'photo', blob })),
        ...(voice.value
          ? [{ id: voice.value.id, kind: 'voice', blob: voice.value.blob }]
          : []),
      ])
    }
    await enqueue(action, payload)
    // the outbox holds them now; the form lets go of its own copies
    photos.value.forEach(release)
    release(voice.value)
    photos.value = []
    voice.value = null
    fieldDialog.open = false
    toast.success(
      connectivity.online
        ? __('Saved')
        : __('Saved on this device. It will be sent when you are back online.'),
    )
  } catch (error) {
    if (action === 'add_note') forgetMedia(payload.media ?? [])
    problem.value = error.message
  } finally {
    saving.value = false
  }
}
</script>
