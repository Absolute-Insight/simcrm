<!--
  Adding photos and a voice note to a note that is being written: the
  thumbnails, the recorder, and the two buttons. It only holds them -- the
  form that owns the note decides where they go (the offline outbox in field
  mode, straight to the server from the note dialog) and reads them with
  `items()`.
-->
<template>
  <div class="flex flex-col gap-2">
    <div
      v-if="photos.length || voice"
      class="flex flex-wrap items-center gap-2"
    >
      <div
        v-for="photo in photos"
        :key="photo.id"
        class="relative size-20 overflow-hidden rounded-5 bg-surface-gray-2"
      >
        <img
          :src="photo.url"
          :alt="__('Photo for this note')"
          class="size-full object-cover"
        />
        <button
          type="button"
          class="absolute right-1 top-1 flex size-6 items-center justify-center rounded-full bg-surface-gray-7/80 text-ink-white focus-visible:outline focus-visible:outline-2"
          :aria-label="__('Remove photo')"
          @click="removePhoto(photo)"
        >
          <LucideX class="size-3.5" aria-hidden="true" />
        </button>
      </div>
      <div
        v-if="voice"
        class="flex min-h-10 w-full items-center gap-2 rounded-5 bg-surface-gray-2 px-2"
      >
        <audio
          :src="voice.url"
          controls
          preload="metadata"
          class="h-9 min-w-0 flex-1"
          :aria-label="__('Voice note')"
        />
        <Button
          variant="ghost"
          icon="lucide-trash-2"
          :aria-label="__('Remove voice note')"
          @click="removeVoice"
        />
      </div>
    </div>

    <div
      v-if="recorder.state.value === 'recording'"
      class="flex min-h-10 items-center justify-between gap-2 rounded-5 bg-surface-red-1 px-3"
      role="status"
    >
      <span
        class="flex items-center gap-2 whitespace-nowrap text-base tabular-nums text-ink-red-9"
      >
        <span
          class="size-2 animate-pulse rounded-full bg-surface-red-5"
          aria-hidden="true"
        />
        <span class="sr-only sm:not-sr-only">{{ __('Recording') }}</span>
        {{ clock(recorder.elapsed.value) }} /
        {{ clock(MAX_VOICE_SECONDS) }}
      </span>
      <div class="flex gap-1">
        <Button
          variant="ghost"
          :label="__('Cancel')"
          @click="recorder.cancel()"
        />
        <Button
          variant="solid"
          :label="__('Stop')"
          icon-left="lucide-square"
          @click="recorder.stop()"
        />
      </div>
    </div>
    <div v-else class="flex flex-wrap gap-2">
      <Button
        :label="__('Add photo')"
        icon-left="lucide-camera"
        :disabled="photos.length >= maxPhotos || busyPhoto"
        :loading="busyPhoto"
        @click="photoInput?.click()"
      />
      <Button
        v-if="voiceNotesSupported()"
        :label="__('Record voice note')"
        icon-left="lucide-mic"
        :disabled="
          !allowVoice || !!voice || recorder.state.value === 'starting'
        "
        @click="recorder.start()"
      />
      <!-- `capture` opens the camera straight away, which is what a rep on
           site wants; without it the device offers the camera and the
           gallery, and a desktop its files. -->
      <input
        ref="photoInput"
        type="file"
        accept="image/*"
        :capture="camera ? 'environment' : undefined"
        :multiple="!camera"
        class="hidden"
        @change="addPhotos"
      />
    </div>
    <p v-if="hint" class="text-p-sm text-ink-gray-6">
      {{ hint }}
    </p>
  </div>
</template>

<script setup>
import LucideX from '~icons/lucide/x'
import { voiceNotesSupported, useVoiceNote } from '@/composables/useVoiceNote'
import {
  MAX_PHOTOS,
  MAX_VOICE_SECONDS,
  clock,
  scalePhoto,
} from '@/utils/noteMedia'
import { newEntryId } from '@/utils/fieldOutbox'
import { computed, onBeforeUnmount, ref } from 'vue'

const props = defineProps({
  // how many more photos the note can take, and whether it can take a recording
  maxPhotos: { type: Number, default: MAX_PHOTOS },
  allowVoice: { type: Boolean, default: true },
  // open the camera directly instead of offering the gallery too
  camera: { type: Boolean, default: false },
})

/* What has been added, until the note is saved: { id, blob, url }. The object
   URLs are released whenever they leave the form. */
const photos = ref([])
const voice = ref(null)
const photoInput = ref(null)
const busyPhoto = ref(false)
const problem = ref('')

const release = (item) => item?.url && URL.revokeObjectURL(item.url)
const withUrl = (blob) => ({
  id: newEntryId(),
  blob,
  url: URL.createObjectURL(blob),
})

const recorder = useVoiceNote({
  onRecorded: ({ blob }) => {
    release(voice.value)
    voice.value = withUrl(blob)
  },
})

const hint = computed(() => {
  if (problem.value) return problem.value
  switch (recorder.error.value) {
    case 'denied':
      return __('Allow the microphone for this site to record a voice note.')
    case 'unsupported':
      return __('This browser cannot record a voice note.')
    case 'nothing':
      return __('Nothing was recorded. Try again.')
    case 'large':
      return __('That recording is too large. Keep it under {0} minutes.', [
        MAX_VOICE_SECONDS / 60,
      ])
    default:
      return ''
  }
})

async function addPhotos(event) {
  const files = [...(event.target.files || [])]
  event.target.value = ''
  problem.value = ''
  busyPhoto.value = true
  try {
    for (const file of files) {
      if (photos.value.length >= props.maxPhotos) {
        problem.value = __('A note takes up to {0} photos.', [MAX_PHOTOS])
        break
      }
      try {
        photos.value = [...photos.value, withUrl(await scalePhoto(file))]
      } catch (error) {
        problem.value = error?.message || __('That photo could not be read.')
      }
    }
  } finally {
    busyPhoto.value = false
  }
}

function removePhoto(photo) {
  release(photo)
  photos.value = photos.value.filter((other) => other !== photo)
}

function removeVoice() {
  release(voice.value)
  voice.value = null
}

/** What to send with the note: `[{ id, kind, blob }]`. */
function items() {
  return [
    ...photos.value.map(({ id, blob }) => ({ id, kind: 'photo', blob })),
    ...(voice.value
      ? [{ id: voice.value.id, kind: 'voice', blob: voice.value.blob }]
      : []),
  ]
}

/** Let go of everything: after a save, or when the form opens afresh. */
function clear() {
  photos.value.forEach(release)
  release(voice.value)
  photos.value = []
  voice.value = null
  problem.value = ''
}

onBeforeUnmount(clear)

defineExpose({
  items,
  clear,
  /** A recording still going, which a save must not silently drop. */
  recording: computed(() => recorder.state.value === 'recording'),
  cancelRecording: () => recorder.cancel(),
  count: computed(() => photos.value.length + (voice.value ? 1 : 0)),
})
</script>
