<template>
  <Dialog
    v-model:open="show"
    :title="
      editMode
        ? __('Edit View')
        : duplicateMode
          ? __('Duplicate View')
          : __('Create View')
    "
  >
    <template #default>
      <div class="flex flex-col gap-4">
        <div>
          <div class="mb-1.5 block text-base text-ink-gray-5">
            {{ __('View Name') }}
          </div>
          <FormControl
            v-model="draft.label"
            size="md"
            type="text"
            :placeholder="__('My Open Deals')"
          />
        </div>
        <div>
          <div class="mb-1.5 block text-base text-ink-gray-5">
            {{ __('Icon') }}
          </div>
          <div class="flex items-center gap-2">
            <!-- legacy views may store an emoji; the lucide picker can't render
                 it, so show it alongside until a lucide icon is picked -->
            <div
              v-if="currentIsEmoji"
              class="grid size-8 shrink-0 place-items-center rounded-[var(--v-radius-control)] bg-surface-gray-3 text-lg leading-none"
              :title="__('Current icon')"
            >
              {{ draft.icon }}
            </div>
            <!-- the picker lists the sprite's symbols when it mounts -->
            <IconPicker
              v-if="lucideSpriteReady"
              v-model="pickerIcon"
              class="flex-1"
              :max-icons="1000"
              :placeholder="
                currentIsEmoji
                  ? __('Replace with an icon...')
                  : __('Select an icon...')
              "
            />
            <div v-else class="h-7 flex-1" />
          </div>
        </div>
      </div>
    </template>
    <template #actions>
      <div class="flex justify-end">
        <Button
          variant="solid"
          :disabled="!draft.label?.trim()"
          :label="
            editMode
              ? __('Save Changes')
              : duplicateMode
                ? __('Duplicate')
                : __('Create')
          "
          @click="() => (editMode ? update() : create())"
        />
      </div>
    </template>
  </Dialog>
</template>

<script setup>
// parked in experimental for v1 (frappe-ui migration doc)
import { IconPicker } from 'frappe-ui/experimental'
import { isEmoji } from '@/utils'
import { ensureLucideSprite, lucideSpriteReady } from '@/utils/lucideSprite'
import { call } from 'frappe-ui'
import { ref, computed, watch } from 'vue'

const props = defineProps({
  doctype: { type: String, required: true },
  options: {
    type: Object,
    default: () => ({ afterCreate: () => {}, afterUpdate: () => {} }),
  },
})

const show = defineModel({ type: Boolean })
const view = defineModel('view', { type: Object, default: () => ({}) })

ensureLucideSprite().catch(() => {})

// The form edits a copy taken when the dialog opens; only Create or Save
// Changes sends it. Bound to `view` itself, a dismissed rename stayed on the
// caller's object -- the views store's own, which the sidebar renders.
const draft = ref({})

// frappe-ui's IconPicker is lucide-only. Legacy views may store an emoji, which
// the picker can't render — hide non-lucide values from it (showing the
// placeholder) while keeping the stored icon, so a no-op edit preserves the
// emoji and picking a lucide icon migrates it.
const currentIsEmoji = computed(() => isEmoji(draft.value?.icon || ''))
const pickerIcon = computed({
  get: () => {
    const icon = draft.value?.icon
    return !icon || isEmoji(icon) ? '' : icon
  },
  set: (value) => {
    draft.value.icon = value || ''
  },
})

const editMode = computed(() => draft.value.mode === 'edit')
const duplicateMode = computed(() => draft.value.mode === 'duplicate')

async function create() {
  draft.value.doctype = props.doctype
  let v = await call(
    'crm.fcrm.doctype.crm_view_settings.crm_view_settings.create',
    { view: draft.value },
  )
  show.value = false
  props.options.afterCreate?.(v)
}

async function update() {
  draft.value.doctype = props.doctype
  await call('crm.fcrm.doctype.crm_view_settings.crm_view_settings.update', {
    view: draft.value,
  })
  show.value = false
  props.options.afterUpdate?.(draft.value)
}

// The caller sets the view and opens the dialog in the same tick, so `view`
// already holds the one to edit when this runs.
watch(
  show,
  (value) => {
    if (value) draft.value = { ...view.value }
  },
  { immediate: true },
)
</script>
