import { describe, expect, it, vi } from 'vitest'

/**
 * useDocument creates a record's document resource once per session, and its
 * onError closure wrote a fresh `error` ref made by that first call. Every
 * later useDocument of the same record handed back a ref nothing wrote, and
 * the cached resource was not fetched again either: a forbidden or deleted
 * record showed its ErrorPage on the first visit and a blank page on the next.
 */
vi.mock('@/data/script', () => ({
  getScript: () => ({ setupScript: vi.fn(async () => []), scripts: {} }),
}))
vi.mock('@/stores/global', () => ({ globalStore: () => ({}) }))
vi.mock('@/stores/meta', () => ({ getMeta: () => ({}) }))
vi.mock('@/composables/useAttachments', () => ({
  useAttachments: () => ({
    trackOldFile: vi.fn(),
    processPendingDeletions: vi.fn(),
  }),
}))
vi.mock('@/composables/settings', () => ({
  showSettings: { value: false },
  activeSettingsPage: { value: '' },
}))
vi.mock('@/utils', () => ({
  runSequentially: vi.fn(),
  parseAssignees: (d) => d,
  sanitizeText: (t) => t,
}))
vi.mock('@/utils/fieldTransforms', () => ({ findMissingMandatory: () => [] }))
vi.mock('@/utils/newDocument', () => ({ newDocumentDraft: () => ({}) }))
vi.mock('@/utils/formScriptErrors', () => ({
  validationErrorMessage: () => '',
}))

const { created } = vi.hoisted(() => ({ created: {} }))
vi.mock('frappe-ui', () => ({
  call: vi.fn(),
  toast: { error: vi.fn(), success: vi.fn() },
  createResource: () => ({}),
  createDocumentResource: (options) => {
    const resource = {
      doc: null,
      options,
      reload: vi.fn(),
      save: { submit: vi.fn() },
    }
    created[options.name] = resource
    return resource
  },
}))

import { useDocument } from '@/data/document'

const forbidden = {
  exc_type: 'PermissionError',
  messages: ['You do not have enough permissions to access this resource.'],
}

describe('a record whose load failed', () => {
  it('still has its error on the next visit, and is asked for again', () => {
    const first = useDocument('CRM Deal', 'CRM-DEAL-77')
    created['CRM-DEAL-77'].options.onError(forbidden) // the GET answers 403
    expect(first.error.value).toEqual(forbidden)

    // the rep goes back to the list and opens the same deal again
    const second = useDocument('CRM Deal', 'CRM-DEAL-77')
    expect(second.error.value).toEqual(forbidden)
    expect(created['CRM-DEAL-77'].reload).toHaveBeenCalledOnce()
  })

  it('clears the error when a later load succeeds', async () => {
    useDocument('CRM Deal', 'CRM-DEAL-78')
    const resource = created['CRM-DEAL-78']
    resource.options.onError(forbidden)

    // access granted in the meantime: the revisit's reload comes back fine
    const second = useDocument('CRM Deal', 'CRM-DEAL-78')
    resource.doc = { name: 'CRM-DEAL-78' }
    await resource.options.onSuccess()
    expect(second.error.value).toBe('')
  })

  it('reaches the page on screen when a realtime refetch fails', () => {
    const first = useDocument('CRM Deal', 'CRM-DEAL-79')
    const resource = created['CRM-DEAL-79']
    resource.doc = { name: 'CRM-DEAL-79' } // loaded fine
    const later = useDocument('CRM Deal', 'CRM-DEAL-79')
    expect(resource.reload).not.toHaveBeenCalled() // nothing to retry

    // a colleague deletes it; doc_update refetches and frappe-ui nulls the doc
    resource.doc = null
    resource.options.onError({
      exc_type: 'DoesNotExistError',
      messages: ['CRM Deal CRM-DEAL-79 not found'],
    })
    expect(later.error.value).toMatchObject({ exc_type: 'DoesNotExistError' })
    expect(first.error).toBe(later.error)
  })
})
