<template>
  <Popover bare side="bottom" align="end">
    <template #trigger>
      <div class="flex items-center">
        <component
          :is="assignees?.length == 1 ? 'Button' : 'div'"
          v-if="assignees?.length"
        >
          <MultipleAvatar :avatars="assignees" />
        </component>
        <Button v-else :label="__('Assign To')" />
      </div>
    </template>
    <template #default="{ open }">
      <AssignToBody
        v-show="open"
        v-model="assignees"
        :docname="docname"
        :doctype="doctype"
        :open="open"
        :onUpdate="ownerField && saveAssignees"
      />
    </template>
  </Popover>
</template>
<script setup>
import MultipleAvatar from '@/components/MultipleAvatar.vue'
import AssignToBody from '@/components/AssignToBody.vue'
import { useDocument } from '@/data/document'
import { call, toast, Popover } from 'frappe-ui'
import { computed } from 'vue'

const props = defineProps({
  doctype: { type: String, default: '' },
  docname: { type: String, default: '' },
})

const { document } = useDocument(props.doctype, props.docname)

const assignees = defineModel({ type: Array, default: () => [] })

const ownerField = computed(() => {
  if (props.doctype === 'CRM Lead') {
    return 'lead_owner'
  } else if (props.doctype === 'CRM Deal') {
    return 'deal_owner'
  } else {
    return null
  }
})

async function saveAssignees(
  addedAssignees,
  removedAssignees,
  addAssignees,
  removeAssignees,
) {
  if (removedAssignees.length) await removeAssignees.submit(removedAssignees)
  if (addedAssignees.length) await addAssignees.submit(addedAssignees)

  const field = ownerField.value
  const previousOwner = document.doc[field]
  const owner = field.replace('_', ' ')

  // The server moves the owner itself: every new assignee becomes the owner,
  // and removing the owner's assignment clears it. It writes the field
  // without a modified bump or a realtime event, so read it back rather than
  // guess -- the guess named the wrong person, or none, and was left on the
  // document as an unsaved edit.
  let serverOwner
  try {
    const values = await call('frappe.client.get_value', {
      doctype: props.doctype,
      filters: props.docname,
      fieldname: field,
    })
    serverOwner = values?.[field] || ''
  } catch (err) {
    // The assignment itself went through; only the owner shown may be stale.
    console.error(err)
    return
  }
  document.doc[field] = serverOwner
  if (document.originalDoc) document.originalDoc[field] = serverOwner

  const label = (name) => {
    const assignee = assignees.value.find((a) => a.name === name)
    return assignee?.label || name
  }

  if (
    !serverOwner &&
    previousOwner &&
    removedAssignees.includes(previousOwner)
  ) {
    const nextAssignee = assignees.value[0]
    if (nextAssignee) {
      document.doc[field] = nextAssignee.name
      document.save.submit()
      toast.info(
        __(
          'Since you removed {0} from the assignee, the {0} has been changed to the next available assignee {1}.',
          [owner, label(nextAssignee.name)],
        ),
      )
    } else {
      toast.info(
        __(
          'Since you removed {0} from the assignee, the {0} has also been removed.',
          [owner],
        ),
      )
    }
  } else if (serverOwner && serverOwner !== previousOwner) {
    toast.info(
      __('Since you added a new assignee, the {0} has been set to {1}.', [
        owner,
        label(serverOwner),
      ]),
    )
  }
}
</script>
