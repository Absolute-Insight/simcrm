<!-- eslint-disable vue/no-v-html -->
<template>
  <div
    v-if="reply?.message"
    class="flex items-center justify-around gap-2 px-3 pt-2 sm:px-10"
  >
    <div
      class="mb-1 ml-13 flex-1 cursor-pointer rounded-[var(--v-radius-control)] border-0 border-l-4 border-green-500 bg-surface-gray-2 p-2 text-base text-ink-gray-5"
      :class="reply.type == 'Incoming' ? 'border-green-500' : 'border-blue-400'"
    >
      <div
        class="mb-1 text-sm-bold"
        :class="
          reply.type == 'Incoming' ? 'text-ink-green-5' : 'text-ink-blue-link'
        "
      >
        {{ reply.from_name || __('You') }}
      </div>
      <div
        class="max-h-12 overflow-hidden"
        v-html="sanitizeHTML(reply.message)"
      />
    </div>

    <Button variant="ghost" icon="lucide-x" @click="reply = {}" />
  </div>
  <div
    v-if="!whatsappCanSend"
    class="px-3 py-2.5 text-p-sm text-ink-gray-5 sm:px-10"
    role="status"
    v-bind="$attrs"
  >
    {{
      __('You have no WhatsApp number yet. Ask your administrator to add one.')
    }}
  </div>
  <div v-else class="flex items-end gap-2 px-3 py-2.5 sm:px-10" v-bind="$attrs">
    <div class="flex h-8 items-center gap-2">
      <FileUploader @success="(file) => uploadFile(file)">
        <template #default="{ openFileSelector }">
          <div class="flex items-center space-x-2">
            <Dropdown :options="uploadOptions(openFileSelector)">
              <span
                class="lucide-plus size-4.5 cursor-pointer text-ink-gray-5"
                aria-hidden="true"
              />
            </Dropdown>
          </div>
        </template>
      </FileUploader>
      <IconPicker
        v-model="emoji"
        @update:modelValue="
          () => {
            content += emoji
            $refs.textareaRef.el.focus()
            capture('whatsapp_emoji_added')
          }
        "
      >
        <SmileIcon
          class="flex size-4.5 cursor-pointer rounded-[var(--v-radius-control)] text-2xl leading-none text-ink-gray-4"
        />
      </IconPicker>
    </div>
    <Textarea
      ref="textareaRef"
      v-model="content"
      type="textarea"
      class="min-h-8 w-full"
      :rows="rows"
      :placeholder="placeholder"
      @focus="rows = 6"
      @blur="rows = 1"
      @keydown.enter.exact.stop.prevent="sendTextMessage"
    />
  </div>
</template>

<script setup>
import IconPicker from '@/components/IconPicker.vue'
import SmileIcon from '@/components/Icons/SmileIcon.vue'
import { whatsappCanSend } from '@/composables/whatsapp'
import { sanitizeHTML } from '@/utils'
import { canSendMessage } from '@/utils/whatsappMessage'
import { useTelemetry } from '@framework/ui/telemetry'
import {
  createResource,
  Textarea,
  FileUploader,
  Dropdown,
  toast,
} from 'frappe-ui'
import { ref, nextTick, watch } from 'vue'

const props = defineProps({
  doctype: { type: String, default: '' },
})

const doc = defineModel({ type: Object, default: () => ({}) })
const whatsapp = defineModel('whatsapp', { type: Object, default: () => ({}) })
const reply = defineModel('reply', { type: Object, default: () => ({}) })

const { capture } = useTelemetry()

const rows = ref(1)
const textareaRef = ref(null)
const emoji = ref('')

const content = ref('')
const placeholder = ref(__('Type your message here...'))
const fileType = ref('')
const sending = ref(false)

function show() {
  nextTick(() => textareaRef.value?.el?.focus())
}

function uploadFile(file) {
  whatsapp.value.attach = file.file_url
  whatsapp.value.content_type = fileType.value
  sendWhatsAppMessage()
  capture('whatsapp_upload_file')
}

function sendTextMessage() {
  if (sending.value || !canSendMessage(content.value)) return
  sendWhatsAppMessage()
  capture('whatsapp_send_message')
}

function sendWhatsAppMessage() {
  sending.value = true
  createResource({
    url: 'crm.api.whatsapp.create_whatsapp_message',
    params: {
      reference_doctype: props.doctype,
      reference_name: doc.value.name,
      message: content.value,
      to: doc.value.mobile_no,
      attach: whatsapp.value.attach || '',
      reply_to: reply.value?.name || '',
      content_type: whatsapp.value.content_type,
    },
    auto: true,
    // Cleared only here: a send that fails keeps what the rep typed, and the
    // reply they were answering, so they can try again.
    onSuccess: () => {
      sending.value = false
      content.value = ''
      fileType.value = ''
      reply.value = {}
      whatsapp.value.attach = ''
      whatsapp.value.content_type = 'text'
      whatsapp.value.reload()
    },
    onError: (error) => {
      sending.value = false
      whatsapp.value.attach = ''
      whatsapp.value.content_type = 'text'
      toast.error(error.messages?.[0] || __('Failed to send WhatsApp message'))
    },
  })
}

function uploadOptions(openFileSelector) {
  return [
    {
      label: __('Upload Document'),
      icon: 'lucide-file',
      onClick: () => {
        fileType.value = 'document'
        openFileSelector()
      },
    },
    {
      label: __('Upload Image'),
      icon: 'lucide-image',
      onClick: () => {
        fileType.value = 'image'
        openFileSelector('image/*')
      },
    },
    {
      label: __('Upload Video'),
      icon: 'lucide-video',
      onClick: () => {
        fileType.value = 'video'
        openFileSelector('video/*')
      },
    },
  ]
}

watch(reply, (value) => {
  if (value?.message) {
    show()
  }
})

defineExpose({ show })
</script>
