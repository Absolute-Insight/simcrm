<!--
  LazyLoadFailed — what a control loaded on first use leaves in its place when
  its code could not be fetched.

  Inline and the size of a field, not a page-level ErrorState: it sits inside
  a form, between other fields. It says what is missing and offers the one
  thing that helps. Retrying fetches again and nothing else -- the rest of the
  form, and what was typed into it, stays as it is.

    lazyComponent(() => import('./Editor.vue'), {
      failed: { render: () => h(LazyLoadFailed, { what: __('the editor') }) },
    })

  lazyComponent passes `error`, `retrying` and `onRetry`, and draws this by
  itself ("this part of the page") when a caller names no stand-in of its own.
-->
<template>
  <div
    class="flex min-h-[4rem] flex-wrap items-center justify-between gap-2 rounded-6 border border-outline-gray-2 bg-surface-gray-2 px-3 py-2"
    role="alert"
  >
    <span class="text-p-sm text-ink-gray-7">
      {{
        offline
          ? __('Could not load {0}: there is no connection.', [what])
          : __('Could not load {0}.', [what])
      }}
      <span class="text-ink-gray-6">
        {{ __('If trying again does not help, reload the page.') }}
      </span>
    </span>
    <Button
      size="sm"
      :label="__('Try again')"
      :loading="retrying"
      @click="emit('retry')"
    />
  </div>
</template>

<script setup>
import { Button } from 'frappe-ui'

defineProps({
  // the thing that did not load, as it reads mid-sentence: "the editor"
  what: { type: String, required: true },
  error: { type: [Object, String], default: null },
  // true while a retry is being fetched: the button stays, and stays focused
  retrying: { type: Boolean, default: false },
})
const emit = defineEmits(['retry'])

const offline = typeof navigator !== 'undefined' && navigator.onLine === false
</script>
