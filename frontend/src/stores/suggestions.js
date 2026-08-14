import { defineStore } from 'pinia'
import { call, createResource } from 'frappe-ui'
import { computed, ref } from 'vue'
import { formatCompactNumber } from '@/utils/numberFormat.js'
import { renderFieldLayoutDialog } from '@/utils/renderFieldLayoutDialog'

export const suggestionsVisible = ref(false)

export const suggestions = createResource({
  url: 'crm.api.suggestions.get_suggestions',
  initialData: [],
  auto: true,
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

export const suggestionsStore = defineStore('crm-suggestions', () => {
  function reload() {
    suggestions.reload()
    openCount.reload()
  }

  function toggle() {
    suggestionsVisible.value = !suggestionsVisible.value
    if (suggestionsVisible.value) reload()
  }

  /**
   * The accept gate: the rep sees and edits exactly what will be created
   * before anything is written. Suggestion payloads are data, not commands —
   * nothing is inserted without this confirmation.
   */
  async function acceptSuggestion(suggestion) {
    let payload
    try {
      payload = JSON.parse(suggestion.action_payload || '{}')
    } catch {
      payload = {}
    }

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

    await call('frappe.client.insert', {
      doc: {
        doctype: 'CRM Task',
        reference_doctype: suggestion.reference_doctype,
        reference_docname: suggestion.reference_docname,
        status: 'Todo',
        ...data,
      },
    })
    await call('crm.api.suggestions.accept', { name: suggestion.name })
    reload()
    return true
  }

  async function dismissSuggestion(suggestion, reason = null) {
    await call('crm.api.suggestions.dismiss', {
      name: suggestion.name,
      reason: reason,
    })
    reload()
  }

  return {
    suggestions,
    openSuggestionsCount,
    toggle,
    acceptSuggestion,
    dismissSuggestion,
  }
})
