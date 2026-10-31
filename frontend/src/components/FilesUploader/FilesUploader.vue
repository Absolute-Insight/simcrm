<template>
  <Dialog v-model:open="show" :title="__('Attach')" :size="'xl'">
    <template #default>
      <FilesUploaderArea
        ref="filesUploaderArea"
        v-model="files"
        :doctype="doctype"
        :options="options"
      />
    </template>
    <template #actions>
      <div class="flex justify-between">
        <div class="flex gap-2">
          <Button
            v-if="files.length"
            variant="subtle"
            :label="__('Remove All')"
            :disabled="fileUploadStarted"
            @click="removeAllFiles"
          />
          <Button
            v-if="
              filesUploaderArea?.showWebLink || filesUploaderArea?.showCamera
            "
            :label="isMobileView ? __('Back') : __('Back to File Upload')"
            iconLeft="lucide-arrow-left"
            @click="
              () => {
                filesUploaderArea.showWebLink = false
                filesUploaderArea.showCamera = false
                filesUploaderArea.webLink = null
                filesUploaderArea.cameraImage = null
              }
            "
          />
          <Button
            v-if="
              filesUploaderArea?.showCamera && !filesUploaderArea?.cameraImage
            "
            :label="__('Switch Camera')"
            @click="() => filesUploaderArea.switchCamera()"
          />
          <Button
            v-if="filesUploaderArea?.cameraImage"
            :label="__('Retake')"
            @click="filesUploaderArea.cameraImage = null"
          />
        </div>
        <div class="flex gap-2">
          <Button
            v-if="isAllPrivate && files.length"
            variant="subtle"
            :label="__('Set all as public')"
            :disabled="fileUploadStarted"
            @click="setAllPublic"
          />
          <Button
            v-else-if="files.length"
            variant="subtle"
            :label="__('Set all as private')"
            :disabled="fileUploadStarted"
            @click="setAllPrivate"
          />
          <Button
            v-if="!filesUploaderArea?.showCamera"
            variant="solid"
            :label="__('Attach')"
            :loading="fileUploadStarted"
            :disabled="disableAttachButton"
            @click="attachFiles"
          />
          <Button
            v-if="
              filesUploaderArea?.showCamera && filesUploaderArea?.cameraImage
            "
            variant="solid"
            :label="__('Upload')"
            @click="() => filesUploaderArea.uploadViaCamera()"
          />
          <Button
            v-if="
              filesUploaderArea?.showCamera && !filesUploaderArea?.cameraImage
            "
            variant="solid"
            :label="__('Capture')"
            @click="() => filesUploaderArea.captureImage()"
          />
        </div>
      </div>
    </template>
  </Dialog>
</template>

<script setup>
import FilesUploaderArea from '@/components/FilesUploader/FilesUploaderArea.vue'
import FilesUploadHandler from './filesUploaderHandler'
import { isMobileView } from '@/composables/settings'
import { toast } from 'frappe-ui'
import { ref, computed } from 'vue'

const props = defineProps({
  doctype: { type: String, required: true },
  docname: { type: String, required: true },
  fieldname: { type: String, default: '' },
  options: {
    type: Object,
    default: () => ({
      folder: 'Home/Attachments',
    }),
  },
})

const emit = defineEmits(['after'])
// 'after' payload: array of uploaded file objects (each has file_url, file_name, name, ...)

const show = defineModel({ type: Boolean })

const filesUploaderArea = ref(null)
const files = ref([])

const isAllPrivate = computed(() => files.value.every((a) => a.private))

function setAllPrivate() {
  files.value.forEach((file) => (file.private = true))
}

function setAllPublic() {
  files.value.forEach((file) => (file.private = false))
}

function removeAllFiles() {
  files.value = []
}

const disableAttachButton = computed(() => {
  if (filesUploaderArea.value?.showCamera) {
    return !filesUploaderArea.value.cameraImage
  }
  if (filesUploaderArea.value?.showWebLink) {
    return !filesUploaderArea.value.webLink
  }
  return !files.value.length
})

// The uploads run in parallel and finish in size order, not list order, so
// the batch is done when every one of them has settled -- not when whichever
// file is listed last comes back. A file that failed stays listed with its
// error; the ones that made it are reported either way.
async function attachFiles() {
  if (filesUploaderArea.value.showWebLink) {
    return uploadViaWebLink()
  }
  const batch = files.value.slice()
  const results = await Promise.allSettled(batch.map(attachFile))
  const uploaded = results
    .filter((r) => r.status === 'fulfilled')
    .map((r) => r.value)
  const failed = batch.filter((_, i) => results[i].status === 'rejected')
  fileUploadStarted.value = false
  files.value = failed
  if (!failed.length) show.value = false
  if (uploaded.length) emit('after', uploaded)
}

function uploadViaWebLink() {
  let fileUrl = filesUploaderArea.value.webLink
  if (!fileUrl) {
    toast.error(__('Please enter a valid URL'))
    return
  }
  fileUrl = decodeURI(fileUrl)
  return attachFile({ fileUrl })
    .then((response) => {
      show.value = false
      emit('after', [response])
    })
    .catch((errorMessage) => {
      // a web link has no entry in the file list to show the error on
      toast.error(errorMessage)
    })
    .finally(() => (fileUploadStarted.value = false))
}

const uploader = ref(null)
const fileUploadStarted = ref(false)

// Resolves with the uploaded file, or rejects with the message it now shows.
function attachFile(file) {
  const args = {
    fileObj: file.fileObj || {},
    type: file.type,
    private: file.private,
    fileUrl: file.fileUrl,
    folder: props.options.folder,
    doctype: props.doctype,
    docname: props.docname,
    fieldname: props.fieldname,
  }

  uploader.value = new FilesUploadHandler()

  uploader.value.on('start', () => {
    file.uploading = true
    file.errorMessage = null
    fileUploadStarted.value = true
  })
  uploader.value.on('progress', (data) => {
    file.uploaded = data.uploaded
    file.total = data.total
  })
  uploader.value.on('error', (error) => {
    file.uploading = false
    file.errorMessage = error || 'Error Uploading File'
  })
  uploader.value.on('finish', () => {
    file.uploading = false
  })

  return uploader.value.upload(file, args || {}).catch((error) => {
    file.uploading = false
    let errorMessage = 'Error Uploading File'
    if (error?._server_messages) {
      errorMessage = JSON.parse(JSON.parse(error._server_messages)[0]).message
    } else if (error?.exc) {
      errorMessage = JSON.parse(error.exc)[0].split('\n').slice(-2, -1)[0]
    } else if (typeof error === 'string') {
      errorMessage = error
    }
    file.errorMessage = errorMessage
    throw errorMessage
  })
}
</script>
