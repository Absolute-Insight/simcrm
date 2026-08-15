<!--
  EmptyState — a list or panel that loaded successfully and holds nothing.

  Only reach for it once the resource has resolved. While it is loading use
  Skeleton; if it failed use ErrorState — an empty state on a failed fetch
  tells the user everything is fine when it is not.
-->
<template>
  <div class="relative flex h-full w-full justify-center">
    <div
      class="absolute left-1/2 flex -translate-x-1/2 flex-col items-center gap-3"
      :class="widthClass"
      :style="{ top: top }"
    >
      <!-- size-7, not size-7.5: Tailwind v3's spacing scale has no 7.5 step,
           so the old class compiled to nothing and the icon fell back to its
           intrinsic size. -->
      <Icon :icon="icon" class="size-7 text-ink-gray-5" />
      <div class="flex flex-col items-center gap-1">
        <span class="text-lg-medium text-ink-gray-8">
          {{ computedTitle }}
        </span>
        <span class="text-center text-p-base text-ink-gray-6">
          {{ computedDescription }}
        </span>
      </div>
    </div>
  </div>
</template>
<script setup>
import Icon from '@/components/Icon.vue'
import { computed } from 'vue'

const props = defineProps({
  // The thing there are none of ("Deals"), used only to build the default
  // title. Optional: most call sites pass an explicit `title` instead, and
  // requiring it made every one of those warn on render.
  name: { type: String, default: '' },
  title: { type: String, default: '' },
  description: { type: String, default: '' },
  icon: {
    type: [String, Object],
    default: 'file-text',
  },
  top: { type: String, default: '35%' },
  width: { type: String, default: 'md' },
})

const computedTitle = computed(() => {
  if (props.title) return props.title
  // With neither a title nor a name there is nothing to interpolate, and
  // "No  yet" is worse than saying nothing specific.
  if (!props.name) return __('Nothing here yet')
  return __('No {0} yet', [__(props.name)])
})

const computedDescription = computed(() => {
  return props.description
    ? props.description
    : __('Create your first from the Create button above.')
})

const widthClass = computed(() => {
  switch (props.width) {
    case 'sm':
      return 'w-2/12'
    case 'lg':
      return 'w-8/12'
    default:
      return 'w-4/12'
  }
})
</script>
