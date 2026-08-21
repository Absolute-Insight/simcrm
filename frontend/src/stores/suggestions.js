import { defineStore } from 'pinia'
import { call, createResource, toast } from 'frappe-ui'
import { neverLoaded } from '@/utils/resourceState'
import { quiet } from '@/utils/quiet'
import { computed, reactive, ref } from 'vue'
import { formatCompactNumber } from '@/utils/numberFormat.js'
import { renderFieldLayoutDialog } from '@/utils/renderFieldLayoutDialog'
import {
  buildCallEventDoc,
  buildEmailArgs,
  buildTaskDoc,
  composeDismissReason,
  dismissReasonOptions,
  displayReferenceLabel,
  draftStatusMessage,
  fieldUpdateSpec,
  isDraftUsable,
  labelFieldsFor,
  nextMorning,
  parseActionPayload,
  pendingReferences,
  pickReferenceLabel,
  referenceKey,
} from '@/utils/suggestions'

export const suggestionsVisible = ref(false)

export const suggestions = createResource({
  url: 'crm.api.suggestions.get_suggestions',
  initialData: [],
  auto: true,
  onSuccess: (rows) => resolveReferenceLabels(rows),
})

// the list caps at 50 rows, so the badge gets its own accurate count
export const openCount = createResource({
  url: 'crm.api.suggestions.get_open_count',
  initialData: 0,
  auto: true,
})

export const openSuggestionsCount = computed(() => {
  const count = openCount.data || 0
  return count ? formatCompactNumber(count) : 0
})

/* A count that never loaded is not a count of zero. `initialData` is 0 and
   frappe-ui leaves it there when the first fetch fails, so the badge above
   collapses to 0, the sidebar hides it, and the inbox reads as empty -- the
   product telling a rep there is nothing waiting when it never managed to ask.
   See utils/resourceState. */
export const openCountUnavailable = computed(() => neverLoaded(openCount))

/**
 * Resolved human names for the records suggestions point at, keyed
 * `"<doctype>:<docname>"`.
 *
 * `get_suggestions` returns the primary key only, and "Deal CRM-DEAL-2026-0043"
 * is not something a rep recognises. Resolving client-side keeps the fix inside
 * this tier; a `reference_label` on the payload would be better and is noted for
 * the backend.
 */
export const referenceLabels = reactive({})

export function referenceLabelFor(suggestion) {
  // display form: appends the short record id when two records of the same
  // doctype resolve to the same name (three deals at one org, most commonly)
  return displayReferenceLabel(
    referenceLabels,
    suggestion.reference_doctype,
    suggestion.reference_docname,
  )
}

/* A label is a nicety: if the lookup 403s or the doctype is one we have no
   label field for, the row still renders with its docname. So this never
   rejects and never blocks the list. */
async function resolveReferenceLabels(rows) {
  const pending = pendingReferences(rows, referenceLabels)
  await Promise.all(
    Object.entries(pending).map(async ([doctype, names]) => {
      try {
        const records = await call('frappe.client.get_list', {
          doctype,
          filters: { name: ['in', names] },
          fields: ['name', ...labelFieldsFor(doctype)],
          limit_page_length: 0,
        })
        for (const record of records || []) {
          referenceLabels[referenceKey(doctype, record.name)] =
            pickReferenceLabel(doctype, record)
        }
      } catch {
        // leave the docname showing rather than blanking the reference line
      }
    }),
  )
}

/**
 * Suggestions whose action record was written but whose status flip then
 * failed. The two writes cannot share a transaction from here — there is no
 * combined endpoint — so pressing Accept again would otherwise create a second
 * task against the same suggestion. On a retry we skip straight to the flip.
 */
const halfAccepted = new Set()

/** Guards against a double click firing two inserts before the first returns. */
const inFlight = new Set()

export const suggestionsStore = defineStore('crm-suggestions', () => {
  function reload() {
    quiet(suggestions.reload())
    quiet(openCount.reload())
  }

  function toggle() {
    suggestionsVisible.value = !suggestionsVisible.value
    if (suggestionsVisible.value) reload()
  }

  /**
   * The accept gate: the rep sees and edits exactly what will be created
   * before anything is written. Suggestion payloads are data, not commands —
   * nothing is inserted without this confirmation.
   *
   * Which record gets created depends on `suggested_action`. Every declared
   * action has a handler; an action with none refuses out loud rather than
   * quietly creating a task, which is what the single hardcoded task dialog
   * used to do for all four.
   */
  async function acceptSuggestion(suggestion) {
    if (inFlight.has(suggestion.name)) return false
    inFlight.add(suggestion.name)
    try {
      return await runAccept(suggestion)
    } catch (error) {
      toast.error(errorMessage(error))
      return false
    } finally {
      inFlight.delete(suggestion.name)
    }
  }

  async function runAccept(suggestion) {
    if (halfAccepted.has(suggestion.name)) {
      // the record already exists from a previous attempt; only the flip is left
      await closeSuggestion(suggestion)
      return true
    }

    const payload = parseActionPayload(suggestion.action_payload)
    const performed = await performAction(suggestion, payload)
    if (!performed) return false

    halfAccepted.add(suggestion.name)
    await closeSuggestion(suggestion)
    return true
  }

  async function closeSuggestion(suggestion) {
    try {
      await call('crm.api.suggestions.accept', { name: suggestion.name })
    } catch (error) {
      // the work landed, the bookkeeping did not — say so, because the rep is
      // about to decide whether to press the button again
      toast.error(
        __('Done, but the suggestion could not be closed: {0}', [
          errorMessage(error),
        ]),
      )
      reload()
      return
    }
    halfAccepted.delete(suggestion.name)
    reload()
  }

  /** Runs the typed action. Returns false when the rep cancels the dialog. */
  async function performAction(suggestion, payload) {
    switch (suggestion.suggested_action) {
      case 'create_task':
        return createTask(suggestion, payload)
      case 'schedule_call':
        return scheduleCall(suggestion, payload)
      case 'send_reply':
        return sendReply(suggestion, payload)
      case 'update_field':
        return updateField(suggestion, payload)
      default:
        throw new Error(__('This suggestion type cannot be accepted yet.'))
    }
  }

  async function createTask(suggestion, payload) {
    const data = await renderFieldLayoutDialog({
      title: __('Create task'),
      size: 'md',
      fields: [
        { fieldname: 'title', fieldtype: 'Data', label: __('Title') },
        {
          fieldname: 'priority',
          fieldtype: 'Select',
          label: __('Priority'),
          options: 'Low\nMedium\nHigh',
        },
        { fieldname: 'due_date', fieldtype: 'Datetime', label: __('Due Date') },
        {
          fieldname: 'description',
          fieldtype: 'Small Text',
          label: __('Description'),
        },
      ],
      required: ['title'],
      defaults: {
        title: payload.title || suggestion.title,
        priority: payload.priority || 'Medium',
        description: suggestion.rationale,
      },
      submitLabel: __('Create task'),
      cancelLabel: __('Cancel'),
    })
    if (!data) return false

    await call('frappe.client.insert', { doc: buildTaskDoc(suggestion, data) })
    return true
  }

  async function scheduleCall(suggestion, payload) {
    const data = await renderFieldLayoutDialog({
      title: __('Schedule call'),
      size: 'md',
      fields: [
        { fieldname: 'subject', fieldtype: 'Data', label: __('Subject') },
        {
          fieldname: 'starts_on',
          fieldtype: 'Datetime',
          label: __('Starts on'),
        },
        {
          fieldname: 'description',
          fieldtype: 'Small Text',
          label: __('Notes'),
        },
      ],
      required: ['subject', 'starts_on'],
      defaults: {
        subject: payload.title || suggestion.title,
        starts_on: payload.starts_on || nextMorning(),
        description: suggestion.rationale,
      },
      submitLabel: __('Schedule call'),
      cancelLabel: __('Cancel'),
    })
    if (!data) return false

    await call('frappe.client.insert', {
      doc: buildCallEventDoc(suggestion, data),
    })
    return true
  }

  /**
   * Ask the agent tier for a draft, then hand it to the rep to edit and send.
   *
   * The draft is attacker-influenced text (it is written from a thread the
   * counterparty contributed to), so it is never sent without the rep reading
   * it. When the tier is off or unreachable the same dialog opens empty with a
   * line saying why — a suggestion that cannot be actioned because a model is
   * down should still be actionable by hand.
   */
  async function sendReply(suggestion, payload) {
    let draft = null
    let degraded = ''
    try {
      const result = await call('crm.agent.api.draft_reply', {
        reference_doctype: suggestion.reference_doctype,
        reference_name: suggestion.reference_docname,
      })
      if (isDraftUsable(result)) draft = result.draft
      else degraded = draftStatusMessage(result?.status)
    } catch {
      // rate limit, permission, anything: the reply is still writable by hand
      degraded = draftStatusMessage('unavailable')
    }

    const data = await renderFieldLayoutDialog({
      title: __('Send reply'),
      size: 'lg',
      fields: [
        {
          fieldname: 'recipients',
          fieldtype: 'Data',
          label: __('To'),
          description: degraded || undefined,
        },
        { fieldname: 'subject', fieldtype: 'Data', label: __('Subject') },
        {
          fieldname: 'content',
          fieldtype: 'Text Editor',
          label: __('Message'),
        },
      ],
      required: ['recipients', 'subject', 'content'],
      defaults: {
        recipients: payload.recipients || '',
        subject: draft?.subject || payload.title || suggestion.title,
        content: draft?.body || '',
      },
      submitLabel: __('Send email'),
      cancelLabel: __('Cancel'),
    })
    if (!data) return false

    await call(
      'frappe.core.doctype.communication.email.make',
      buildEmailArgs(suggestion, data),
    )
    return true
  }

  async function updateField(suggestion, payload) {
    const spec = fieldUpdateSpec(payload)
    if (!spec)
      throw new Error(__('This suggestion type cannot be accepted yet.'))

    const data = await renderFieldLayoutDialog({
      title: __('Update field'),
      size: 'md',
      fields: [
        {
          fieldname: spec.fieldname,
          fieldtype: spec.fieldtype,
          label: spec.label,
          options: spec.options,
        },
      ],
      required: [spec.fieldname],
      defaults: { [spec.fieldname]: spec.value },
      submitLabel: __('Update'),
      cancelLabel: __('Cancel'),
    })
    if (!data) return false

    await call('frappe.client.set_value', {
      doctype: suggestion.reference_doctype,
      name: suggestion.reference_docname,
      fieldname: spec.fieldname,
      value: data[spec.fieldname],
    })
    return true
  }

  /**
   * Dismissing asks why, because the answer is load-bearing: the signal engine
   * reads a rep's dismissal history to stretch the cooldown on a signal they
   * keep rejecting, and an administrator reads the reasons back to find which
   * threshold is wrong. Sending null taught it nothing.
   */
  async function dismissSuggestion(suggestion) {
    if (inFlight.has(suggestion.name)) return false
    const options = dismissReasonOptions()
    const data = await renderFieldLayoutDialog({
      title: __('Dismiss suggestion'),
      size: 'md',
      fields: [
        {
          fieldname: 'reason',
          fieldtype: 'Select',
          label: __('Why is this not useful?'),
          options: options.map((o) => ({ label: o.label, value: o.value })),
        },
        {
          fieldname: 'note',
          fieldtype: 'Small Text',
          label: __('Anything to add? (optional)'),
        },
      ],
      required: ['reason'],
      defaults: { reason: options[0].value },
      submitLabel: __('Dismiss'),
      cancelLabel: __('Cancel'),
    })
    if (!data) return false

    inFlight.add(suggestion.name)
    try {
      await call('crm.api.suggestions.dismiss', {
        name: suggestion.name,
        reason: composeDismissReason(data.reason, data.note),
      })
      reload()
      return true
    } catch (error) {
      toast.error(errorMessage(error))
      return false
    } finally {
      inFlight.delete(suggestion.name)
    }
  }

  return {
    suggestions,
    openSuggestionsCount,
    referenceLabelFor,
    reload,
    toggle,
    acceptSuggestion,
    dismissSuggestion,
  }
})

function errorMessage(error) {
  return error?.messages?.[0] || error?.message || __('Something went wrong.')
}
