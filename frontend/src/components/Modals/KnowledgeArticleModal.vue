<template>
  <Dialog
    v-model:open="show"
    :title="isNew ? __('New knowledge article') : __('Edit knowledge article')"
    :size="'3xl'"
  >
    <template #default>
      <div class="flex flex-col gap-4">
        <div class="grid grid-cols-1 gap-4 sm:grid-cols-2">
          <FormControl
            v-model="draft.title"
            type="text"
            :label="__('Title')"
            :placeholder="__('Knife gate valves')"
            required
          />
          <FormControl
            v-model="draft.category"
            type="text"
            :label="__('Category')"
            :placeholder="__('Valves')"
          />
          <FormControl
            v-model="draft.tags"
            type="text"
            :label="__('Tags')"
            :description="
              __('The words customers use for this. Comma-separated.')
            "
            :placeholder="__('knife gate, slurry, isolation')"
          />
          <div>
            <div class="mb-2 text-sm text-ink-gray-5">{{ __('Product') }}</div>
            <Link
              class="form-control flex-1 truncate"
              :value="draft.product"
              doctype="CRM Product"
              @change="(v) => (draft.product = v)"
            />
          </div>
        </div>

        <Switch
          :model-value="!!draft.available_to_assistant"
          size="sm"
          :label="__('Available to the Assistant')"
          :description="
            __('Off keeps the article but the Assistant never quotes it.')
          "
          @update:model-value="draft.available_to_assistant = $event ? 1 : 0"
        />

        <div class="flex flex-col gap-2">
          <div class="flex items-center justify-between">
            <div class="text-sm text-ink-gray-5">
              {{ __('Body (markdown)') }}
            </div>
            <Button
              size="sm"
              variant="ghost"
              :label="preview ? __('Edit') : __('Preview')"
              @click="preview = !preview"
            />
          </div>
          <!-- Admin-authored markdown, rendered through the same sanitizer
               as the help center. The Assistant only ever sees it as text. -->
          <!-- eslint-disable vue/no-v-html -->
          <div
            v-if="preview"
            class="help-article max-h-[50vh] min-h-48 overflow-y-auto rounded-lg border border-outline-gray-2 p-4"
            v-html="previewHtml"
          />
          <!-- eslint-enable vue/no-v-html -->
          <textarea
            v-else
            v-model="draft.body"
            rows="14"
            class="max-h-[50vh] min-h-48 w-full resize-y rounded-lg border-0 bg-surface-gray-2 px-3 py-2 font-mono text-sm text-ink-gray-8 placeholder-ink-gray-4 focus:ring-2 focus:ring-outline-gray-3"
            :placeholder="
              __(
                '## What it is\n\n## Typical sizes and ratings\n\n## Where it is used\n\n## Questions to ask the customer',
              )
            "
          />
        </div>
      </div>
    </template>
    <template #actions>
      <div class="flex items-center justify-between gap-2">
        <div><ErrorMessage :message="error" /></div>
        <div class="flex gap-2">
          <Button :label="__('Cancel')" @click="show = false" />
          <Button
            variant="solid"
            :label="__('Save')"
            :loading="saving"
            @click="save"
          />
        </div>
      </div>
    </template>
  </Dialog>
</template>

<script setup>
import Link from '@/components/Controls/Link.vue'
import { sanitizeHTML } from '@/utils'
import { describeError } from '@/utils/describeError'
import { renderArticleMarkdown } from '@/utils/helpCenter'
import { Dialog, ErrorMessage, FormControl, Switch, call } from 'frappe-ui'
import { computed, reactive, ref, watch } from 'vue'

const props = defineProps({
  /** The article to edit, or null for a new one. */
  article: { type: Object, default: null },
})

const show = defineModel({ type: Boolean, default: false })
const emit = defineEmits(['saved'])

const blank = () => ({
  name: null,
  title: '',
  category: '',
  tags: '',
  product: '',
  available_to_assistant: 1,
  body: '',
})

const draft = reactive(blank())
const preview = ref(false)
const saving = ref(false)
const error = ref('')

const isNew = computed(() => !draft.name)
const previewHtml = computed(() =>
  sanitizeHTML(renderArticleMarkdown(draft.body || '')),
)

watch(show, (open) => {
  if (!open) return
  Object.assign(draft, blank(), props.article || {})
  preview.value = false
  error.value = ''
})

async function save() {
  error.value = ''
  if (!draft.title.trim()) {
    error.value = __('Give the article a title.')
    return
  }
  if (!draft.body.trim()) {
    error.value = __(
      'The body is what the Assistant quotes — it cannot be empty.',
    )
    return
  }
  saving.value = true
  try {
    const saved = await call('crm.api.knowledge.save_article', {
      doc: { ...draft },
    })
    emit('saved', saved)
    show.value = false
  } catch (e) {
    error.value = describeError(e).message || __('Could not save the article.')
  } finally {
    saving.value = false
  }
}
</script>
