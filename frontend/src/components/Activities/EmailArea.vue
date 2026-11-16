<template>
  <div
    class="v-glass v-glass-hover cursor-pointer flex flex-col rounded-[var(--v-radius-card)] px-3 py-1.5 text-base transition-all duration-300 ease-in-out"
  >
    <div
      class="-mb-0.5 flex items-center justify-between gap-2 truncate text-ink-gray-9"
    >
      <div class="flex items-center gap-2 truncate">
        <span>{{ activity.data.sender_full_name }}</span>
        <span class="sm:flex hidden text-sm text-ink-gray-5">
          {{ '<' + activity.data.sender + '>' }}
        </span>
        <Badge
          v-if="activity.communication_type == 'Automated Message'"
          :label="__('Notification')"
          variant="subtle"
          theme="green"
        />
      </div>
      <div class="flex items-center gap-2 shrink-0">
        <ToneBadge
          v-if="status.label"
          :label="__(status.label)"
          variant="subtle"
          :theme="status.color"
        />
        <!-- a scheduled email shows when it goes out, not when it was written -->
        <TimelineTimestamp
          :date="
            scheduled ? activity.data.send_after : activity.communication_date
          "
        />
        <Dropdown
          v-if="scheduled && activity.data.scheduled_by_me"
          :options="scheduledActions"
          align="end"
        >
          <Button
            variant="ghost"
            icon="lucide-ellipsis"
            :tooltip="__('Scheduled email actions')"
            :aria-label="__('Scheduled email actions')"
            :loading="busy"
          />
        </Dropdown>
        <div v-if="!scheduled && !hidden" class="flex gap-0.5">
          <Button
            :tooltip="__('Reply')"
            variant="ghost"
            class="text-ink-gray-7"
            :icon="ReplyIcon"
            @click="reply(activity.data)"
          />
          <Button
            :tooltip="__('Reply All')"
            variant="ghost"
            :icon="ReplyAllIcon"
            class="text-ink-gray-7"
            @click="reply(activity.data, true)"
          />
        </div>
      </div>
    </div>
    <!-- The summary opens and closes the email. Closed, every line is
         truncated, so a closed row is the same height however long its
         recipients or body: rows above the newest cannot grow while the
         timeline scrolls to it. -->
    <div
      v-if="hidden"
      class="flex min-w-0 flex-col gap-1 text-base leading-5 text-ink-gray-8"
      data-email-hidden
    >
      <div class="truncate">{{ activity.data.subject }}</div>
      <div class="truncate">
        <span class="mr-1 text-ink-gray-5"> {{ __('To') }}: </span>
        <span>{{ activity.data.recipients }}</span>
      </div>
      <div class="flex min-w-0 items-center gap-1.5 text-p-sm text-ink-gray-5">
        <LucideLock class="size-3.5 shrink-0" aria-hidden="true" />
        <span class="truncate">
          {{ __("You don't have access to this email's content") }}
        </span>
      </div>
    </div>
    <button
      v-else
      type="button"
      class="flex min-w-0 items-start gap-2 rounded text-left text-base leading-5 text-ink-gray-8 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-outline-gray-3"
      :aria-expanded="expanded ? 'true' : 'false'"
      :aria-label="
        expanded
          ? __('Collapse email: {0}', [activity.data.subject])
          : __('Expand email: {0}', [activity.data.subject])
      "
      data-email-toggle
      @click="toggle"
    >
      <div class="flex min-w-0 flex-1 flex-col gap-1">
        <div :class="{ truncate: !expanded }">
          {{ activity.data.subject }}
        </div>
        <div :class="{ truncate: !expanded }">
          <span class="mr-1 text-ink-gray-5"> {{ __('To') }}: </span>
          <span>{{ activity.data.recipients }}</span>
          <span v-if="activity.data.cc">, </span>
          <span v-if="activity.data.cc" class="mr-1 text-ink-gray-5">
            {{ __('CC') }}:
          </span>
          <span v-if="activity.data.cc">{{ activity.data.cc }}</span>
          <span v-if="activity.data.bcc">, </span>
          <span v-if="activity.data.bcc" class="mr-1 text-ink-gray-5">
            {{ __('BCC') }}:
          </span>
          <span v-if="activity.data.bcc">{{ activity.data.bcc }}</span>
        </div>
        <div
          v-if="!expanded"
          class="flex min-w-0 items-center gap-2 text-p-sm text-ink-gray-6"
          data-email-snippet
        >
          <span class="truncate">{{ activity.data.snippet }}</span>
          <span
            v-if="attachments.length"
            class="ml-auto flex shrink-0 items-center gap-1 text-ink-gray-5"
          >
            <LucidePaperclip class="size-3.5" aria-hidden="true" />
            {{ attachments.length }}
          </span>
        </div>
      </div>
      <LucideChevronDown
        class="mt-0.5 size-4 shrink-0 text-ink-gray-5 transition-transform"
        :class="{ 'rotate-180': expanded }"
        aria-hidden="true"
      />
    </button>
    <template v-if="expanded">
      <div class="border-0 border-t mt-3 mb-1 border-outline-elevation-2" />
      <EmailContent v-if="body != null" :content="body" />
      <div
        v-else-if="failed"
        role="alert"
        class="flex min-h-10 flex-wrap items-center gap-2 py-1 text-p-sm text-ink-red-9"
        data-email-error
      >
        <span>{{ __('Could not load this email.') }}</span>
        <Button
          variant="subtle"
          size="sm"
          :label="__('Retry')"
          data-email-retry
          @click="loadBody"
        />
      </div>
      <div
        v-else
        class="flex min-h-10 items-center gap-2 text-p-sm text-ink-gray-5"
        aria-live="polite"
        data-email-loading
      >
        <LoadingIndicator class="size-4" />
        <span>{{ __('Loading email...') }}</span>
      </div>
      <div v-if="attachments.length" class="flex flex-wrap gap-2">
        <AttachmentItem
          v-for="a in attachments"
          :key="a.file_url"
          :label="a.file_name"
          :url="a.file_url"
        />
      </div>
    </template>
  </div>
</template>
<script setup>
import ReplyIcon from '@/components/Icons/ReplyIcon.vue'
import ReplyAllIcon from '@/components/Icons/ReplyAllIcon.vue'
import AttachmentItem from '@/components/AttachmentItem.vue'
import EmailContent from '@/components/Activities/EmailContent.vue'
import LoadingIndicator from '@/components/Icons/LoadingIndicator.vue'
import { createDialog } from '@/utils/dialogs'
import {
  cachedEmailBody,
  claimReply,
  fetchEmailBody,
  isLatestReply,
  rememberEmailBody,
} from '@/composables/useEmailBody'
import { Badge, Dropdown, call, dayjsLocal, toast } from 'frappe-ui'
import TimelineTimestamp from '@/components/Activities/TimelineTimestamp.vue'
import ToneBadge from '@/components/ui/ToneBadge.vue'
import { computed, ref, watch } from 'vue'

const props = defineProps({
  activity: { type: Object, default: () => ({}) },
  emailBox: { type: Object, default: () => ({}) },
})

const emit = defineEmits(['reload'])

const attachments = computed(() => props.activity.data?.attachments || [])

// Listed on this record through a timeline link, but referenced to a record
// the reader cannot see: the server sends who, to whom and when, and nothing
// of what -- so there is nothing to open, retry or quote.
const hidden = computed(() => !!props.activity.data?.hidden)

// The timeline sends the body only with the newest emails, which open by
// default and so paint at full height at once; any other is a snippet until
// the rep opens it. See crm.api.activities.get_email_body.
const inlineBody = () => props.activity.data?.content
const expanded = ref(typeof inlineBody() === 'string')
const body = ref(inlineBody() ?? cachedEmailBody(props.activity.name) ?? null)
const failed = ref(false)
if (typeof inlineBody() === 'string') {
  rememberEmailBody(props.activity.name, inlineBody())
}

// A reload keeps this card (it is keyed by name) and may bring the body along.
watch(inlineBody, (content) => {
  if (typeof content !== 'string') return
  rememberEmailBody(props.activity.name, content)
  body.value = content
})

async function loadBody() {
  if (body.value != null) return body.value
  failed.value = false
  try {
    body.value = await fetchEmailBody(props.activity.name)
  } catch {
    failed.value = true
  }
  return body.value
}

function toggle() {
  if (hidden.value) return
  expanded.value = !expanded.value
  if (expanded.value) loadBody()
}

const scheduled = computed(() => {
  const { delivery_status, send_after } = props.activity.data
  return delivery_status === 'Scheduled' && !!send_after
})

const busy = ref(false)

const scheduledActions = [
  { label: __('Send now'), icon: 'lucide-send', onClick: sendNow },
  { label: __('Edit'), icon: 'lucide-pencil', onClick: edit },
  {
    label: __('Delete'),
    icon: 'lucide-trash-2',
    theme: 'red',
    onClick: deleteScheduled,
  },
]

function confirm(title, message, label, onConfirm, theme = 'gray') {
  createDialog({
    title,
    message,
    actions: [
      {
        label,
        theme,
        variant: 'solid',
        onClick: ({ close }) => {
          close()
          onConfirm()
        },
      },
    ],
  })
}

async function run(method, success, error) {
  busy.value = true
  try {
    const result = await call(method, { name: props.activity.name })
    toast.success(success)
    emit('reload')
    return result
  } catch (e) {
    toast.error(e?.messages?.[0] || error)
    // A failed send may still have left the queue, and a refused change means
    // the card is out of date. Either way, show what the server has now.
    emit('reload')
  } finally {
    busy.value = false
  }
}

function sendNow() {
  const at = dayjsLocal(props.activity.data.send_after).format(
    'ddd, D MMM, h:mm A',
  )
  confirm(
    __('Send now?'),
    __('It will be sent right away instead of on {0}.', [at]),
    __('Send now'),
    () =>
      run(
        'crm.api.email.send_scheduled_email_now',
        __('Email sent'),
        __('Failed to send email'),
      ),
  )
}

async function edit() {
  const emailBox = props.emailBox
  if (!emailBox) return
  // Editing moves the email into the composer, so don't overwrite a draft
  if (emailBox.hasDraft) {
    toast.error(__('Send or discard the email you are writing first'))
    return
  }
  const draft = await run(
    'crm.api.email.cancel_scheduled_email',
    __('Moved to the composer. Schedule it again when ready.'),
    __('Failed to edit scheduled email'),
  )
  if (draft) emailBox.restoreDraft(draft)
}

function deleteScheduled() {
  confirm(
    __('Delete scheduled email?'),
    __("It won't be sent. This can't be undone."),
    __('Delete'),
    () =>
      run(
        'crm.api.email.cancel_scheduled_email',
        __('Scheduled email deleted'),
        __('Failed to delete scheduled email'),
      ),
    'red',
  )
}

// Reply quotes the body, so a closed email's is fetched first. A body already
// here replies at once, in the same tick as the click. Only the latest Reply
// click on the page fills the composer: a slow fetch for an email clicked
// earlier must not overwrite the reply the rep has moved on to.
function reply(email, reply_all = false) {
  if (!props.emailBox || hidden.value) return
  const ticket = claimReply()
  if (body.value != null) return quoteInReply(email, body.value, reply_all)
  loadBody().then((content) => {
    if (!isLatestReply(ticket)) return
    if (content == null) {
      toast.error(__('Could not load this email to reply to it'))
      return
    }
    quoteInReply(email, content, reply_all)
  })
}

function quoteInReply(email, message, reply_all) {
  // Read at the click, not at setup: the composer is a template ref further
  // down the page, and a card mounted before it (the first render of a tab)
  // would hold null for good and throw here.
  const emailBox = props.emailBox
  if (!emailBox) return
  emailBox.show = true
  let editor = emailBox.editor
  let recipients = email.recipients.split(',').map((r) => r.trim())
  // Reply from whichever of the user's own accounts the thread went through,
  // never from the customer's address: email.sender is who wrote to us.
  let replyAddresses = []
  for (let addresses of [email.sender, email.recipients, email.cc, email.bcc]) {
    if (!addresses) continue
    for (let address of addresses.split(',')) {
      replyAddresses.push(address.trim())
    }
  }
  editor.replyAddresses = replyAddresses
  // Mail the rep sent is followed up with whoever it went to: its sender is
  // the rep's own mailbox. Only received mail is answered to its sender.
  const sent = email.sent_or_received === 'Sent'
  editor.toEmails = sent ? recipients.filter(Boolean) : [email.sender]
  editor.cc = editor.bcc = false
  editor.ccEmails = []
  editor.bccEmails = []

  if (!email.subject.startsWith('Re:')) {
    editor.subject = `Re: ${email.subject}`
  } else {
    editor.subject = email.subject
  }

  if (reply_all) {
    let cc = email.cc?.split(',').map((r) => r.trim())
    let bcc = email.bcc?.split(',').map((r) => r.trim())

    // On sent mail the recipients are already on To and CC stays as sent.
    if (!sent && cc?.length) {
      recipients = recipients.filter((r) => !cc?.includes(r))
      cc.push(...recipients)
    } else if (!sent) {
      cc = recipients
    }

    editor.cc = cc ? true : false
    editor.bcc = bcc ? true : false

    editor.ccEmails = cc || []
    editor.bccEmails = bcc || []
  }

  let repliedMessage = `<blockquote>${message}</blockquote>`
  let draft = draftBeforeQuote(editor.editor)

  editor.editor
    .chain()
    .clearContent()
    .updateAttributes('paragraph', { class: 'reply-to-content' })
    .insertContent(repliedMessage)
    .focus('all')
    .insertContentAt(0, draft.length ? draft : { type: 'paragraph' })
    .focus('start')
    .run()
}

// Keep what the user already typed, dropping any previously quoted email
function draftBeforeQuote(editor) {
  let draft = []
  let quoted = false
  editor.state.doc.forEach((node) => {
    quoted ||= node.type.name === 'blockquote'
    if (!quoted) draft.push(node.toJSON())
  })
  return draft
}

const status = computed(() => {
  let _status = props.activity?.data?.delivery_status
  let indicator_color = 'red'
  if (['Sent', 'Clicked'].includes(_status)) {
    indicator_color = 'green'
  } else if (['Sending', 'Scheduled'].includes(_status)) {
    indicator_color = 'orange'
  } else if (['Opened', 'Read'].includes(_status)) {
    indicator_color = 'blue'
  } else if (_status == 'Error') {
    indicator_color = 'red'
  }
  return { label: _status, color: indicator_color }
})
</script>
