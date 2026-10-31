<template>
  <Dialog v-model:open="show" bare :size="'xl'">
    <template #default>
      <div class="bg-surface-elevation-2 px-4 pb-6 pt-5 sm:px-6">
        <div class="mb-6 flex items-center justify-between">
          <div>
            <DialogTitle as-child>
              <h3 class="text-3xl-semibold leading-6 text-ink-gray-9">
                {{ __('Delete') }}
              </h3>
            </DialogTitle>
            <VisuallyHidden>
              <DialogDescription>{{
                __(
                  'Confirm deleting the selected records and everything linked to them',
                )
              }}</DialogDescription>
            </VisuallyHidden>
          </div>
          <div class="flex items-center gap-1">
            <Button variant="ghost" icon="lucide-x" @click="show = false" />
          </div>
        </div>
        <div>
          <div class="text-ink-gray-5 text-base">
            {{
              __('Are you sure you want to delete {0} items?', [
                props.items?.length,
              ])
            }}
          </div>
        </div>
      </div>
      <div class="px-4 pb-7 pt-0 sm:px-6">
        <div class="flex flex-row-reverse gap-2">
          <Button
            :label="__('Delete {0} items', [props.items.length])"
            icon-left="lucide-trash-2"
            variant="solid"
            theme="red"
            @click="confirmDelete()"
          />
          <Button
            :label="__('Unlink & Delete {0} items', [props.items.length])"
            icon-left="lucide-unlock"
            variant="solid"
            @click="confirmUnlink()"
          />
        </div>
      </div>
      <div
        v-if="confirmDeleteInfo.show"
        class="bg-surface-elevation-2 px-4 pb-6 pt-5 sm:px-6"
      >
        <div class="mb-6 flex items-center justify-between">
          <div>
            <h3 class="text-3xl-semibold leading-6 text-ink-gray-9">
              {{ __('Delete') }}
            </h3>
          </div>
          <div class="flex items-center gap-1">
            <Button variant="ghost" icon="lucide-x" @click="show = false" />
          </div>
        </div>
        <div>
          <div class="text-ink-gray-5 text-base">
            {{
              confirmDeleteInfo.delete
                ? __(
                    'This will delete selected items and items linked to it, are you sure?',
                  )
                : __(
                    'This will delete selected items and unlink linked items to it, are you sure?',
                  )
            }}
          </div>
        </div>
      </div>
      <div v-if="confirmDeleteInfo.show" class="px-4 pb-7 pt-0 sm:px-6">
        <div class="flex flex-row-reverse gap-2">
          <Button
            :label="
              confirmDeleteInfo.delete ? __('Delete') : __('Unlink & Delete')
            "
            :icon-left="confirmDeleteInfo.delete ? 'trash-2' : 'unlock'"
            variant="solid"
            theme="red"
            @click="deleteDocs()"
          />
          <Button
            :label="__('Cancel')"
            variant="subtle"
            @click="confirmDeleteInfo.show = false"
          />
        </div>
      </div>
    </template>
  </Dialog>
</template>

<script setup>
import { DialogTitle, DialogDescription, VisuallyHidden } from 'reka-ui'
import { describeError } from '@/utils/describeError'
import { call, toast } from 'frappe-ui'
import { ref } from 'vue'

const show = defineModel({ type: Boolean })
const props = defineProps({
  doctype: { type: String, required: true },
  items: { type: Array, required: true },
  reload: { type: Function, required: true },
})

const confirmDeleteInfo = ref({
  show: false,
  title: '',
  message: '',
  delete: false,
})

const confirmDelete = () => {
  confirmDeleteInfo.value = {
    show: true,
    title: __('Delete'),
    message: __('Are you sure you want to delete {0} linked doc(s)?', [
      props.items.length,
    ]),
    delete: true,
  }
}

const confirmUnlink = () => {
  confirmDeleteInfo.value = {
    show: true,
    title: __('Unlink'),
    message: __('Are you sure you want to unlink {0} linked doc(s)?', [
      props.items.length,
    ]),
    delete: false,
  }
}

// A record that would not go (a link the unlink cannot remove, a permission)
// used to be counted as deleted, and the toast said so over a list that then
// reloaded with it still there. Name the survivors and the first reason.
function notDeletedMessage({ count, failed }) {
  const total = count + failed.length
  const [first] = failed
  if (failed.length == 1) {
    return __('Deleted {0} of {1}. {2} was not deleted: {3}', [
      count,
      total,
      first.docname,
      first.reason,
    ])
  }
  return __('Deleted {0} of {1}. Not deleted: {2}. {3}: {4}', [
    count,
    total,
    failed.map((row) => row.docname).join(', '),
    first.docname,
    first.reason,
  ])
}

const deleteDocs = async () => {
  try {
    // Over ten records frappe deletes in a worker, so the list will not have
    // caught up by the time this returns. Saying "deleted" then is how a rep
    // ends up staring at rows that are supposedly gone.
    const result = await call('crm.api.doc.delete_bulk_docs', {
      items: props.items,
      doctype: props.doctype,
      delete_linked: confirmDeleteInfo.value.delete,
    })
    if (result?.queued) {
      toast.success(__('Deleting {0} in the background', [result.count]))
    } else if (result?.failed?.length) {
      toast.error(notDeletedMessage(result))
    } else {
      toast.success(__('Deleted {0}', [result?.count ?? props.items.length]))
    }
  } catch (error) {
    toast.error(describeError(error).message || __('Could not delete.'))
  } finally {
    confirmDeleteInfo.value = {
      show: false,
      title: '',
    }
    show.value = false
    props.reload()
  }
}
</script>
