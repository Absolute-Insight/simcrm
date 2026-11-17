<template>
  <Dialog v-model:open="show" bare :size="'xl'">
    <template #default>
      <div class="bg-surface-elevation-2 px-4 pb-6 pt-5 sm:px-6">
        <div class="mb-5 flex items-center justify-between">
          <div class="flex gap-2 items-center">
            <!-- `__('Edit ' + name)` translated a string built at runtime, so
                 the key was "Edit Note", "Edit Call Log" and so on -- keys no
                 extractor can see, because none of them appear in the source.
                 A placeholder makes "Edit {0}" the one visible key, and the
                 name is translated on its own. -->
            <DialogTitle as-child>
              <h3 class="text-3xl-semibold leading-6 text-ink-gray-9">
                {{
                  editMode
                    ? __('Edit {0}', [__(doctypeTitle || doctype)])
                    : __('Create {0}', [__(doctypeTitle || doctype)])
                }}
              </h3>
            </DialogTitle>
            <VisuallyHidden>
              <DialogDescription>{{
                __('Create or edit this record')
              }}</DialogDescription>
            </VisuallyHidden>
          </div>
          <div class="flex items-center gap-1">
            <CustomActions
              v-if="document.actions?.length"
              :actions="document.actions"
              :close="() => (show = false)"
            />
            <Button
              v-if="isManager() && !isMobileView"
              variant="ghost"
              class="w-7"
              :tooltip="__('Edit Fields Layout')"
              :icon="EditIcon"
              @click="openQuickEntryModal"
            />
            <Button
              variant="ghost"
              class="w-7"
              icon="lucide-x"
              @click="show = false"
            />
          </div>
        </div>
        <div>
          <FieldLayout
            v-if="layout.data"
            :tabs="layout.data"
            :data="doc"
            :doctype="doctype"
            :docname="docname"
          />
          <div v-if="doctype === 'CRM Task' && docname" class="mt-6">
            <div class="mb-2 text-sm font-medium text-ink-gray-7">
              {{ __('History') }}
            </div>
            <div
              v-if="history.data?.length"
              class="max-h-48 space-y-2 overflow-y-auto text-sm"
            >
              <div v-for="(entry, i) in history.data" :key="i">
                <div class="text-ink-gray-5">
                  {{ entry.owner }} · {{ formatDate(entry.creation) }}
                </div>
                <div
                  v-for="change in entry.changes"
                  :key="change.field"
                  class="text-ink-gray-8"
                >
                  <span class="font-medium">{{ change.label }}</span
                  >:
                  <span
                    v-if="change.old != null && change.old !== ''"
                    class="text-ink-gray-5 line-through"
                    >{{ change.old }}</span
                  >
                  {{ change.new }}
                </div>
              </div>
            </div>
            <div v-else class="text-sm text-ink-gray-5">
              {{ __('No history for this task yet.') }}
            </div>
          </div>
          <!-- A note's photos and voice note: what it holds already, and
               room to add up to the limit. -->
          <div v-if="isNote" class="mt-4 flex flex-col gap-3">
            <NoteMedia v-if="docname" :note="docname" />
            <NoteMediaPicker
              ref="media"
              :max-photos="photoRoom"
              :allow-voice="voiceRoom"
            />
          </div>
          <ErrorMessage v-if="error" class="mt-4" :message="__(error)" />
        </div>
      </div>
      <div class="px-4 pb-7 pt-4 sm:px-6">
        <div class="flex flex-row-reverse gap-2">
          <Button
            variant="solid"
            :label="editMode ? __('Update') : __('Create')"
            :loading="
              (editMode ? document.save.loading : creating) || attaching
            "
            @click="editMode ? update() : create()"
          />
        </div>
      </div>
    </template>
  </Dialog>
</template>

<script setup>
import { DialogTitle, DialogDescription, VisuallyHidden } from 'reka-ui'
import EditIcon from '@/components/Icons/EditIcon.vue'
import FieldLayout from '@/components/FieldLayout/FieldLayout.vue'
import CustomActions from '@/components/CustomActions.vue'
import { useDocument } from '@/data/document'
import { globalStore } from '@/stores/global'
import { usersStore } from '@/stores/users'
import { showQuickEntryModal, quickEntryProps } from '@/composables/modals'
import { isMobileView } from '@/composables/settings'
import { setupCustomizations, formatDate } from '@/utils'
import { resetNewDocument } from '@/utils/newDocument'
import NoteMedia from '@/components/Notes/NoteMedia.vue'
import NoteMediaPicker from '@/components/Notes/NoteMediaPicker.vue'
import { noteMedia } from '@/composables/useNoteMedia'
import { MAX_PHOTOS, MAX_RECORDINGS } from '@/utils/noteMedia'
import { attachNoteMedia } from '@/utils/noteMediaUpload'
import { call, createResource, toast } from 'frappe-ui'
import { ref, computed, watch, nextTick, onMounted } from 'vue'
import { useRouter } from 'vue-router'

const props = defineProps({
  doctypeTitle: { type: String, default: '' },
  doctype: { type: String, default: '' },
  docname: { type: String, default: '' },
  defaults: { type: Object, default: () => ({}) },
})

const history = createResource({
  url: 'crm.api.task.get_history',
  params: { name: props.docname },
  auto: props.doctype === 'CRM Task' && !!props.docname,
})

const show = defineModel({ type: Boolean })

const emit = defineEmits(['afterInsert', 'afterUpdate'])

const router = useRouter()

const { isManager } = usersStore()
const { $dialog, $socket } = globalStore()

const { document, scripts, triggerOnRender, triggerOnBeforeCreate } =
  useDocument(props.doctype, props.docname || null)

const doc = computed(() => document.doc || {})

const layout = createResource({
  url: 'crm.fcrm.doctype.crm_fields_layout.crm_fields_layout.get_fields_layout',
  cache: ['Quick Entry', props.doctype],
  params: { doctype: props.doctype, type: 'Quick Entry' },
  auto: true,
})

const error = ref(null)
const editMode = computed(() => Boolean(document.doc?.name))

/* A note takes photos and a voice note (NoteMediaPicker). They are sent once
   the note itself is saved, because they are filed against its name. */
const isNote = computed(() => props.doctype === 'FCRM Note')
const media = ref(null)
const attaching = ref(false)
const held = computed(() => (props.docname ? noteMedia(props.docname) : []))
const photoRoom = computed(
  () => MAX_PHOTOS - held.value.filter((m) => m.kind === 'photo').length,
)
const voiceRoom = computed(
  () => held.value.filter((m) => m.kind === 'voice').length < MAX_RECORDINGS,
)

function stillRecording() {
  if (!media.value?.recording) return false
  error.value = __('Stop the recording first.')
  return true
}

/* True when there was nothing to send or it all went. A failure leaves the
   dialog open on the saved note, with the files still in it to send again. */
async function sendMedia(note) {
  const items = media.value?.items() ?? []
  if (!items.length) return true
  attaching.value = true
  try {
    await attachNoteMedia(note, items)
    media.value?.clear()
    return true
  } catch (err) {
    error.value =
      err.messages?.[0] ||
      __('The note was saved, but its photos or voice note were not.')
    return false
  } finally {
    attaching.value = false
  }
}

const _create = createResource({
  url: 'frappe.client.insert',
  onSuccess: async (d) => {
    const sent = await sendMedia(d.name)
    resetNewDocument(document, props.doctype)
    emit('afterInsert', d)
    if (sent) {
      show.value = false
      return
    }
    // the note exists now: say so, rather than leave a form that would
    // create it a second time
    toast.warning(
      __(
        'The note was saved without its photos or voice note. Open it to add them again.',
      ),
    )
    show.value = false
  },
  onError: (err) => {
    if (err.exc_type == 'MandatoryError') {
      const fieldName = err.messages
        .map((msg) => {
          let arr = msg.split(': ')
          return arr[arr.length - 1].trim()
        })
        .join(', ')
      error.value = __('Mandatory field error: {0}', [fieldName])
      return
    }
    error.value = err.messages?.[0] || 'Could not create document'
  },
})

// Set before the first await, so a second click that lands while the Form
// Script's onBeforeCreate or the insert is still running sends nothing.
const creating = ref(false)

async function create() {
  if (creating.value || stillRecording()) return
  creating.value = true
  try {
    await triggerOnBeforeCreate?.()
    await _create
      .submit({
        doc: {
          doctype: props.doctype,
          ...document.doc,
        },
      })
      // _create's onError has already shown the failure
      .catch(() => {})
  } finally {
    creating.value = false
  }
}

async function update() {
  if (attaching.value || stillRecording()) return
  // frappe-ui skips saving an unchanged doc without calling back, so handle it here
  if (!document.isDirty) {
    if (media.value?.count) {
      // only photos or a recording were added to the note
      if (await sendMedia(props.docname)) {
        emit('afterUpdate', document.doc)
        show.value = false
      }
      return
    }
    toast.info(__('Nothing to update'))
    show.value = false
    return
  }
  document.save.submit(null, {
    onSuccess: async (d) => {
      const sent = await sendMedia(props.docname)
      emit('afterUpdate', d)
      if (sent) show.value = false
    },
    onError: (err) => {
      error.value = err.messages?.[0] || 'Could not update document'
    },
  })
}

function openQuickEntryModal() {
  showQuickEntryModal.value = true
  quickEntryProps.value = { doctype: props.doctype }
  nextTick(() => (show.value = false))
}

watch(
  () => document.doc,
  async (_doc) => {
    if (scripts.data?.length) {
      setupCustomizations(scripts.data, {
        doc: _doc,
        $dialog,
        $socket,
        router,
        toast,
        call,
      })
    }
  },
  { once: true },
)

onMounted(async () => {
  // Create mode shares one buffer per doctype for the session, so it still
  // holds whatever a form closed unsaved left in it -- such as the deal a
  // New Task was opened from. Start from an empty record.
  if (!props.docname) resetNewDocument(document, props.doctype)
  document.doc = {
    ...document.doc,
    ...props.defaults,
  }
  await triggerOnRender()
})
</script>
