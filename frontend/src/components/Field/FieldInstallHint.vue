<!--
  iPhone and iPad only, in a browser tab: say that the app has to be on the
  Home Screen for what is saved here to stay. Dismissed once, it stays gone.
-->
<template>
  <div v-if="show" class="shrink-0 border-b bg-surface-gray-2" role="note">
    <div
      class="mx-auto flex w-full max-w-2xl items-start justify-between gap-3 px-4 py-2.5"
    >
      <p class="text-p-sm text-ink-gray-8">
        {{
          __(
            'Add Vectora to your Home Screen: tap Share, then Add to Home Screen. Without it, this device may clear what is saved and field mode will not open offline.',
          )
        }}
      </p>
      <Button
        class="shrink-0"
        variant="ghost"
        icon="lucide-x"
        :aria-label="__('Dismiss')"
        @click="dismiss"
      />
    </div>
  </div>
</template>

<script setup>
import { needsInstallHint } from '@/utils/fieldPack'
import { ref } from 'vue'

const KEY = 'crm-field-install-hint-dismissed'

function dismissed() {
  try {
    return localStorage.getItem(KEY) === '1'
  } catch {
    return false
  }
}

const show = ref(
  !dismissed() &&
    needsInstallHint({
      userAgent: navigator.userAgent,
      platform: navigator.platform,
      maxTouchPoints: navigator.maxTouchPoints,
      standalone:
        navigator.standalone === true ||
        window.matchMedia?.('(display-mode: standalone)').matches === true,
    }),
)

function dismiss() {
  show.value = false
  try {
    localStorage.setItem(KEY, '1')
  } catch {
    // not remembered: it shows again next time, which is the cautious side
  }
}
</script>
