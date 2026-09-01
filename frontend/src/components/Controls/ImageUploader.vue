<template>
  <FileUploader
    :file-types="image_type"
    @success="(file) => emit('upload', file.file_url)"
  >
    <template #default="{ progress, uploading, openFileSelector }">
      <div class="flex items-end space-x-1">
        <Button
          :iconLeft="uploading ? 'cloud-upload' : ImageUpIcon"
          :label="
            uploading
              ? __('Uploading {0}%', [progress])
              : image_url
                ? __('Change')
                : __('Upload')
          "
          @click="openFileSelector"
        />
        <Button
          v-if="image_url"
          :label="__('Remove')"
          @click="emit('remove')"
        />
      </div>
    </template>
  </FileUploader>
</template>
<script setup>
// Phosphor has no image+arrow combo glyph; the button's own label
// ("Upload"/"Change") already carries the action, so the plain picture
// glyph — already reused for images throughout the app (FileImageIcon,
// BrandSettings) — carries the subject without a weight-mismatched Lucide
// icon next to it.
import { PhImage as ImageUpIcon } from '@phosphor-icons/vue'
import { FileUploader, Button } from 'frappe-ui'

defineProps({
  image_url: { type: String, default: '' },
  image_type: { type: String, default: 'image/*' },
})
const emit = defineEmits(['upload', 'remove'])
</script>
