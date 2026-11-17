<template>
  <div
    class="v-lux-stage flex flex-col items-center justify-center min-h-screen bg-surface-gray-1 px-4"
  >
    <div class="text-center max-w-md">
      <h1 class="text-ink-gray-8 text-2xl-semibold">
        {{ __('Vectora could not load') }}
      </h1>
      <div class="border-t w-full my-[15px]" />
      <p class="text-ink-gray-6 text-p-base">
        {{
          __(
            'The list of users did not load, so this page cannot be shown yet. This is usually brief, for example while the server restarts.',
          )
        }}
      </p>
      <Button
        class="mt-5 w-full"
        variant="solid"
        :label="__('Try again')"
        :loading="retrying"
        @click="retry"
      />
    </div>
  </div>
</template>

<script setup>
import { ref } from 'vue'
import { useRoute } from 'vue-router'

const route = useRoute()
const retrying = ref(false)

/* A full reload rather than a router push: it re-runs the boot as a whole, so
   it also recovers when the failure was the session or a stale build, and the
   guard's first-load retry runs again on the way in. Only an in-app path is
   followed, so the query cannot send the person elsewhere. */
function retry() {
  retrying.value = true
  const target = route.query.redirect
  const path =
    typeof target === 'string' &&
    target.startsWith('/') &&
    !target.startsWith('//')
      ? target
      : '/'
  window.location.assign('/crm' + path)
}
</script>
