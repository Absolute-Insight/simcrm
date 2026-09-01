<template>
  <div
    class="v-glass v-glass-hover activity group flex h-48 cursor-pointer flex-col justify-between gap-2 rounded-[var(--v-radius-card)] px-4 py-3"
  >
    <div class="flex items-center justify-between">
      <div class="truncate text-lg-medium text-ink-gray-8">
        {{ note.title }}
      </div>
      <Dropdown
        :options="[
          {
            label: __('Edit'),
            icon: 'lucide-edit-2',
            onClick: () => modalRef.showNote(note),
          },
          {
            label: __('Delete'),
            icon: 'lucide-trash-2',
            onClick: () => deleteNote(note.name),
          },
        ]"
        class="h-6 w-6"
        @click.stop
      >
        <Button
          icon="lucide-more-horizontal"
          variant="ghost"
          class="!h-6 !w-6 hover:bg-surface-gray-2"
          @click.stop.prevent
        />
      </Dropdown>
    </div>
    <TextEditor
      v-if="note.content"
      :content="note.content"
      :editable="false"
      editor-class="prose-sm text-p-sm max-w-none text-ink-gray-5 focus:outline-none"
      class="flex-1 overflow-hidden"
    />
    <div class="mt-1 flex items-center justify-between gap-2">
      <div class="flex items-center gap-2 truncate">
        <UserAvatar :user="note.owner" size="xs" />
        <div
          class="truncate text-sm text-ink-gray-8"
          :title="getUser(note.owner).full_name"
        >
          {{ getUser(note.owner).full_name }}
        </div>
      </div>
      <TimelineTimestamp
        :date="note.modified"
        class-name="truncate text-sm text-ink-gray-7"
      />
    </div>
  </div>
</template>
<script setup>
import UserAvatar from '@/components/UserAvatar.vue'
import TimelineTimestamp from '@/components/Activities/TimelineTimestamp.vue'
import { Dropdown, call, toast } from 'frappe-ui'
// parked in experimental for v1 (frappe-ui migration doc)
import { TextEditor } from 'frappe-ui/experimental'
import { usersStore } from '@/stores/users'

defineProps({
  note: { type: Object, default: () => ({}) },
  modalRef: { type: Object, default: () => ({}) },
})

const notes = defineModel({ type: Object })

const { getUser } = usersStore()

async function deleteNote(name) {
  await toast.promise(
    call('frappe.client.delete', {
      doctype: 'FCRM Note',
      name,
    }),
    {
      loading: __('Deleting note...'),
      success: __('Note deleted'),
      error: __('Failed to delete note'),
    },
  )
  notes.value?.reload()
}
</script>
