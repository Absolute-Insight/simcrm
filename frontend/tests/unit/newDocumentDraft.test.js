import { readFileSync } from 'node:fs'
import { join } from 'node:path'
import { describe, expect, it } from 'vitest'
import { newDocumentDraft, resetNewDocument } from '@/utils/newDocument'

/**
 * `useDocument(doctype)` with no name hands back one buffer per doctype, shared
 * for the whole session. A creation form that does not empty it opens on the
 * last record someone typed -- for CRM Deal that meant a deal saved against the
 * previous customer's organization, silently.
 */
describe('newDocumentDraft', () => {
  it('marks the record unsaved and keeps the doctype', () => {
    expect(newDocumentDraft('CRM Deal')).toEqual({
      __newDocument: true,
      doctype: 'CRM Deal',
    })
  })

  it('hands back a fresh object every time', () => {
    const first = newDocumentDraft('CRM Lead')
    first.first_name = 'Ada'
    expect(newDocumentDraft('CRM Lead').first_name).toBeUndefined()
  })
})

describe('resetNewDocument', () => {
  it('drops every field the previous form left behind', () => {
    const document = {
      doc: {
        __newDocument: true,
        doctype: 'CRM Deal',
        organization: 'Acme',
        deal_value: 50000,
        territory: 'West',
      },
    }

    resetNewDocument(document, 'CRM Deal')

    expect(document.doc.organization).toBeUndefined()
    expect(document.doc.deal_value).toBeUndefined()
    expect(document.doc.territory).toBeUndefined()
  })

  it('leaves a record the doctype can still be read from', () => {
    // LeadModal used to reset to `{}`, which dropped the doctype and made every
    // subsequent getField() against the buffer return null.
    const document = { doc: { doctype: 'CRM Lead', first_name: 'Ada' } }

    const doc = resetNewDocument(document, 'CRM Lead')

    expect(doc).toBe(document.doc)
    expect(document.doc.doctype).toBe('CRM Lead')
    expect(document.doc.__newDocument).toBe(true)
  })

  it('replaces the object rather than mutating the old one', () => {
    // The old doc may still be referenced by an in-flight create request.
    const document = { doc: { doctype: 'CRM Deal', organization: 'Acme' } }
    const before = document.doc

    resetNewDocument(document, 'CRM Deal')

    expect(document.doc).not.toBe(before)
    expect(before.organization).toBe('Acme')
  })

  it('does nothing when there is no buffer yet', () => {
    expect(resetNewDocument(undefined, 'CRM Deal')).toBe(null)
  })
})

/**
 * The helper only helps if the creation forms call it. This is the part that
 * failed before the fix: DealModal reset the buffer nowhere at all, and
 * LeadModal reset it to a bare `{}`.
 */
describe('the creation modals', () => {
  const modal = (name) =>
    readFileSync(join(process.cwd(), 'src/components/Modals', name), 'utf8')

  it.each(['DealModal.vue', 'LeadModal.vue'])(
    '%s empties the shared buffer on mount and after a successful create',
    (name) => {
      const source = modal(name)
      expect(source).toMatch(/import \{ resetNewDocument \}/)
      expect(source.match(/resetNewDocument\(/g)?.length).toBe(2)
    },
  )

  it('never resets a draft to a doctype-less object', () => {
    for (const name of ['DealModal.vue', 'LeadModal.vue']) {
      expect(modal(name)).not.toMatch(/\.doc = \{\}/)
    }
  })
})
