import { renderFieldLayoutDialog } from '@/utils/renderFieldLayoutDialog'

/* A CRM Task may not be left in one of these without a closing note
   (crm_task.NOTE_REQUIRED_STATUSES). Rescheduled is on the list but is not
   terminal: it also needs a new due date. The Kanban board, the task list on a
   record page and the task dialog all write status; they must all ask the same
   question the same way, or the server refuses the write on one of them with a
   toast and no field to fill -- which is what the record page did. */
export const NOTE_REQUIRED_TASK_STATUSES = ['Done', 'Canceled', 'Rescheduled']

export function needsClosingNote(status) {
  return NOTE_REQUIRED_TASK_STATUSES.includes(status)
}

export function closingNoteFields(status) {
  const fields = [
    {
      fieldname: 'closing_note',
      fieldtype: 'Small Text',
      label: __('What happened'),
    },
  ]
  if (status === 'Rescheduled') {
    fields.push({
      fieldname: 'due_date',
      fieldtype: 'Datetime',
      label: __('New due date'),
    })
  }
  return fields
}

export function closingSubmitLabel(status) {
  const labels = {
    Done: __('Mark done'),
    Canceled: __('Mark canceled'),
    Rescheduled: __('Mark rescheduled'),
  }
  return labels[status] || __('Save')
}

/**
 * Ask for the closing note (and, for Rescheduled, the new due date) a status
 * change needs. Resolves to the values to write alongside `status`, or null
 * when the person cancelled. Statuses that need nothing resolve to {}.
 */
export async function collectClosingValues(status) {
  if (!needsClosingNote(status)) return {}
  const fields = closingNoteFields(status)
  const result = await renderFieldLayoutDialog({
    title: __('Closing note'),
    size: 'md',
    fields,
    required: fields.map((field) => field.fieldname),
    submitLabel: closingSubmitLabel(status),
    cancelLabel: __('Cancel'),
  })
  if (!result) return null
  const values = { closing_note: result.closing_note }
  if (result.due_date) values.due_date = result.due_date
  return values
}
