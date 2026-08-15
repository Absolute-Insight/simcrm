<!--
  PanelCard — the shell every dashboard panel sits in.

  It owns the four states a panel can be in so no panel has to re-invent them:
  loading (skeleton slot), failed (ErrorState with retry), resolved-but-empty
  (EmptyState), and resolved. Panels pass `resource`-shaped flags rather than a
  resource, so a panel built from two calls can still say "loading" once.
-->
<template>
  <section
    class="flex min-w-0 flex-col rounded-lg border border-outline-gray-1 bg-surface-elevation-2"
    :aria-labelledby="headingId"
  >
    <header
      class="flex items-center justify-between gap-3 border-b border-outline-gray-1 px-4 py-3"
    >
      <div class="flex min-w-0 flex-col">
        <h2
          :id="headingId"
          class="font-display text-base font-medium tracking-tight text-ink-gray-8"
        >
          {{ title }}
        </h2>
        <p v-if="subtitle" class="truncate text-sm text-ink-gray-5">
          {{ subtitle }}
        </p>
      </div>
      <div class="flex shrink-0 items-center gap-1">
        <slot name="actions" />
      </div>
    </header>

    <div class="min-w-0 flex-1 p-4">
      <div v-if="loading">
        <slot name="loading">
          <Skeleton
            shape="text"
            :lines="3"
            :label="__('Loading {0}', [title])"
          />
        </slot>
      </div>

      <ErrorState
        v-else-if="error"
        compact
        :error="error"
        :title="errorTitle"
        :retry="retry"
      />

      <!-- EmptyState positions itself absolutely against its container, so it
           needs a height to sit inside; without one it collapses to nothing. -->
      <div v-else-if="empty" class="relative min-h-[9rem]">
        <EmptyState
          :icon="emptyIcon"
          :title="emptyTitle"
          :description="emptyDescription"
          top="10%"
          width="lg"
        />
      </div>

      <slot v-else />
    </div>
  </section>
</template>

<script setup>
import EmptyState from '@/components/ListViews/EmptyState.vue'
import ErrorState from '@/components/ui/ErrorState.vue'
import Skeleton from '@/components/ui/Skeleton.vue'
import { useId } from 'vue'

defineProps({
  title: { type: String, required: true },
  subtitle: { type: String, default: '' },
  loading: { type: Boolean, default: false },
  error: { type: [Object, String, Error], default: null },
  errorTitle: { type: String, default: '' },
  retry: { type: Function, default: null },
  empty: { type: Boolean, default: false },
  emptyTitle: { type: String, default: '' },
  emptyDescription: { type: String, default: '' },
  emptyIcon: { type: [String, Object], default: 'check-circle' },
})

const headingId = useId()
</script>
