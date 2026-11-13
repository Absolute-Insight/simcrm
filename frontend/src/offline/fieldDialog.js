/**
 * The one capture dialog field mode has, opened from wherever the rep is.
 *
 * `kind` is what is being captured; `context` is what the screen already
 * knows (the item, the customer, the task), so the form asks only for the
 * rest. Field.vue mounts the dialog once.
 */
import { reactive } from 'vue'

export const fieldDialog = reactive({ open: false, kind: null, context: {} })

/**
 * @param {'log'|'complete'|'cancel'|'note'|'task'|'close_task'} kind
 * @param {object} [context]
 */
export function openFieldDialog(kind, context = {}) {
  fieldDialog.kind = kind
  fieldDialog.context = context
  fieldDialog.open = true
}
