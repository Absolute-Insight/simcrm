<template>
  <!-- frappe-ui v1 deleted ConfirmDialog in favour of the imperative
       dialog.confirm()/dialog.danger(). The two settings views that used it
       are declarative and their state lives in the parent, so this keeps the
       same 5-prop contract on top of the v1 Dialog instead of rewriting the
       call sites imperatively. -->
  <Dialog v-model="open" :title="title">
    <p class="text-p-base text-ink-gray-7">{{ message }}</p>
    <template #actions="{ close }">
      <div class="flex justify-end gap-2">
        <Button :label="__('Cancel')" @click="cancel(close)" />
        <Button
          variant="solid"
          :label="__('Confirm')"
          :loading="loading"
          @click="confirm(close)"
        />
      </div>
    </template>
  </Dialog>
</template>
<script setup>
import { Dialog, Button } from 'frappe-ui'
import { computed, ref } from 'vue'

const props = defineProps({
  modelValue: { type: Boolean, default: false },
  title: { type: String, default: '' },
  message: { type: String, default: '' },
  onConfirm: { type: Function, default: null },
  onCancel: { type: Function, default: null },
})
const emit = defineEmits(['update:modelValue'])

const open = computed({
  get: () => props.modelValue,
  set: (v) => emit('update:modelValue', v),
})
const loading = ref(false)

async function confirm(close) {
  // mirror the old component: onConfirm receives {hideDialog} and may be async
  loading.value = true
  try {
    await props.onConfirm?.({ hideDialog: close })
  } finally {
    loading.value = false
  }
}

function cancel(close) {
  if (props.onCancel) props.onCancel({ hideDialog: close })
  else close()
}
</script>
