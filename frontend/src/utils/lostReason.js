/**
 * What still blocks a record from moving to a Lost-type status, mirroring
 * validate_lost_reason on CRM Lead and CRM Deal: a reason is always required,
 * and notes are required when the reason is "Other". Returns the message to
 * show, or '' when both are satisfied.
 */
export function lostReasonError(reason, notes) {
  if (!reason) return __('Lost Reason is required')
  if (reason === 'Other' && !notes) {
    return __('Lost Notes are required when Lost Reason is "Other"')
  }
  return ''
}

/**
 * Read the result of frappe's submit_cancel_or_update_docs. Under 20 records
 * it runs inline and returns the docnames that failed to save (empty when all
 * succeeded); from 20 it enqueues the job and returns nothing, so failures
 * only reach the Error Log.
 */
export function bulkUpdateOutcome(result) {
  if (!Array.isArray(result)) return { status: 'enqueued', failed: [] }
  if (result.length) return { status: 'failed', failed: result }
  return { status: 'done', failed: [] }
}
