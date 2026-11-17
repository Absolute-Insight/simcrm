<!--
  The photos and voice note on one note card: small thumbnails that open the
  photo full size, and a player for the recording. Nothing when there are none.
  Clicks stay here -- the card around it opens the note for editing.
-->
<template>
  <div
    v-if="photos.length || voices.length"
    class="flex flex-col gap-1.5"
    @click.stop
  >
    <div v-if="photos.length" class="flex gap-1.5">
      <a
        v-for="photo in photos.slice(0, 4)"
        :key="photo.name"
        :href="photo.url"
        target="_blank"
        rel="noopener"
        class="block size-12 shrink-0 overflow-hidden rounded-4 bg-surface-gray-2 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2"
        :aria-label="__('Open photo')"
      >
        <img
          :src="photo.url"
          :alt="__('Photo on this note')"
          loading="lazy"
          class="size-full object-cover"
        />
      </a>
    </div>
    <audio
      v-for="voice in voices"
      :key="voice.name"
      :src="voice.url"
      controls
      preload="none"
      class="h-8 w-full"
      :aria-label="__('Voice note')"
    />
  </div>
</template>

<script setup>
import { noteMedia } from '@/composables/useNoteMedia'
import { computed } from 'vue'

const props = defineProps({ note: { type: String, default: '' } })

const media = computed(() => noteMedia(props.note))
const photos = computed(() => media.value.filter((m) => m.kind === 'photo'))
const voices = computed(() => media.value.filter((m) => m.kind === 'voice'))
</script>
