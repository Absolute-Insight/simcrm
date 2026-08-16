<!--
  ErrorState — what a page renders when a resource it needs failed to load.

  Reach for it in the `v-else-if="resource.error"` branch, ahead of the empty
  branch. A list that could not load is not an empty list, and telling someone
  "nothing needs your attention" when the fetch 500'd is a lie the interface
  tells with a straight face.

  It says what happened in plain language, keeps the traceback folded away
  behind a disclosure, and gives the one action that actually helps: retry.

    <ErrorState v-if="report.error" :error="report.error" :retry="report.reload" />
    <ErrorState :error="suggestions.error" compact @retry="suggestions.reload()" />
-->
<template>
  <div
    class="grid h-full w-full place-items-center px-4"
    :class="compact ? 'py-6' : 'py-10'"
    role="alert"
  >
    <!-- Two measures on purpose: the sentences stay at a readable line length
         while the detail panel below gets the full width a traceback needs. -->
    <div
      class="flex w-full flex-col items-center gap-3 text-center"
      :class="compact ? 'max-w-xs' : 'max-w-xl'"
    >
      <div
        class="grid place-items-center rounded-full"
        :class="[compact ? 'size-9' : 'size-11', tint.surface]"
      >
        <component
          :is="resolvedIcon"
          :class="[compact ? 'size-4' : 'size-5', tint.ink]"
          aria-hidden="true"
        />
      </div>

      <div class="flex max-w-md flex-col gap-1">
        <span class="text-lg-medium text-ink-gray-8">{{ heading }}</span>
        <span class="text-p-base text-ink-gray-6">{{ body }}</span>
      </div>

      <div v-if="showRetry || $slots.actions" class="flex items-center gap-2">
        <Button
          v-if="showRetry"
          variant="solid"
          :loading="retrying"
          :label="retryLabel || __('Try again')"
          @click="runRetry"
        >
          <template #prefix>
            <LucideRotateCw class="size-4" />
          </template>
        </Button>
        <slot name="actions" />
      </div>

      <!-- The detail is opt-in on purpose. A traceback in the face reads as
           "this application is broken"; folded away it reads as "here is what
           to paste to your administrator". -->
      <details v-if="described.detail" class="v-error-detail w-full text-left">
        <summary
          class="flex cursor-pointer list-none items-center justify-center gap-1 rounded-4 py-1 text-sm text-ink-gray-5 hover:text-ink-gray-7 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2"
        >
          <LucideChevronRight class="v-error-detail__caret size-3.5" />
          {{ __('Technical details') }}
        </summary>
        <div
          class="mt-2 flex items-start gap-2 rounded-5 bg-surface-gray-2 p-3"
        >
          <pre
            class="max-h-40 min-w-0 flex-1 overflow-auto whitespace-pre-wrap break-words font-mono text-xs leading-5 text-ink-gray-6"
            >{{ described.detail }}</pre
          >
          <Button
            class="shrink-0"
            size="sm"
            variant="ghost"
            :tooltip="__('Copy details')"
            :aria-label="__('Copy details')"
            @click="copyToClipboard(described.detail)"
          >
            <template #icon>
              <LucideCopy class="size-3.5" />
            </template>
          </Button>
        </div>
      </details>
    </div>
  </div>
</template>

<script setup>
import LucideChevronRight from '~icons/lucide/chevron-right'
import LucideCloudOff from '~icons/lucide/cloud-off'
import LucideCopy from '~icons/lucide/copy'
import LucideLock from '~icons/lucide/lock'
import LucideRotateCw from '~icons/lucide/rotate-cw'
import LucideSearchX from '~icons/lucide/search-x'
import LucideTriangleAlert from '~icons/lucide/alert-triangle'
import { describeError } from '@/utils/describeError'
import { copyToClipboard } from '@/utils'
import { Button } from 'frappe-ui'
import { computed, getCurrentInstance, ref } from 'vue'

const props = defineProps({
  // Whatever the resource rejected with — an Error, a Frappe error payload,
  // or a plain string. Parsing is ErrorState's job, not the caller's.
  error: { type: [Object, String, Error], default: null },
  // Overrides for the generated copy. Pass them when the page can say
  // something more useful than "could not load this".
  title: { type: String, default: '' },
  description: { type: String, default: '' },
  // The thing to run again. May return a promise; the button waits on it.
  retry: { type: Function, default: null },
  retryLabel: { type: String, default: '' },
  icon: { type: [String, Object, Function], default: null },
  // Tighter layout for side panels and rails rather than a full page.
  compact: { type: Boolean, default: false },
})

const emit = defineEmits(['retry'])

/* Declaring `retry` in defineEmits strips `onRetry` out of `$attrs`, so a
   listener-only call site (`@retry="..."` with no `:retry` prop) is invisible
   there. The instance vnode still has it, and listener presence never changes
   over a component's life, so reading it once is enough. */
const hasRetryListener = Boolean(getCurrentInstance()?.vnode?.props?.onRetry)

const retrying = ref(false)

const described = computed(() => describeError(props.error))

/* Built at render time, not at module load, so a language change re-resolves
   and so the extractor sees each string inside a __() call. */
const copyForKind = computed(() => {
  switch (described.value.kind) {
    case 'offline':
      return {
        title: __('Cannot reach the server'),
        body: __(
          'The connection dropped, or the server is restarting. Nothing you have entered is lost.',
        ),
        icon: LucideCloudOff,
        tone: 'neutral',
      }
    case 'permission':
      return {
        title: __('You do not have access to this'),
        body: __('Ask an administrator to give you access, then try again.'),
        icon: LucideLock,
        tone: 'neutral',
      }
    case 'notfound':
      return {
        title: __('This is not here any more'),
        body: __('It may have been deleted or renamed since you last looked.'),
        icon: LucideSearchX,
        tone: 'neutral',
      }
    default:
      return {
        title: __('Could not load this'),
        body: __(
          'Something went wrong on the server. Try again — if it keeps happening, send the details below to your administrator.',
        ),
        icon: LucideTriangleAlert,
        tone: 'alert',
      }
  }
})

const heading = computed(() => props.title || copyForKind.value.title)

/* The server's own sentence beats the generic one when it wrote a human
   sentence at all — describeError only promotes text meant for a person. */
const body = computed(
  () => props.description || described.value.message || copyForKind.value.body,
)

const resolvedIcon = computed(() => props.icon || copyForKind.value.icon)

/* ink-red-6 rather than a lower step: on surface-red-1 it measures 4.2:1 in
   light and 3.0:1 in dark, the only step that clears the 3:1 graphical-object
   floor in both. ink-red-3..5 are pale tints on this ramp and ink-red-7
   collapses to 1.3:1 against the dark disc. */
const tint = computed(() =>
  copyForKind.value.tone === 'alert'
    ? { surface: 'bg-surface-red-1', ink: 'text-ink-red-6' }
    : { surface: 'bg-surface-gray-2', ink: 'text-ink-gray-5' },
)

const showRetry = computed(() => Boolean(props.retry) || hasRetryListener)

async function runRetry() {
  if (retrying.value) return
  retrying.value = true
  try {
    emit('retry')
    await props.retry?.()
  } finally {
    retrying.value = false
  }
}
</script>

<style scoped>
/* `list-none` on the summary kills the modern marker; older WebKit needs this
   pseudo-element too. The rotating caret is the affordance instead. */
.v-error-detail summary::-webkit-details-marker {
  display: none;
}

.v-error-detail__caret {
  transition: transform var(--motion-fast) var(--motion-ease);
}

.v-error-detail[open] .v-error-detail__caret {
  transform: rotate(90deg);
}
</style>
