import { readFileSync } from 'node:fs'
import { join } from 'node:path'
import { nextTick, ref } from 'vue'
import { describe, expect, it } from 'vitest'
import {
  documentErrorCopy,
  useDocumentError,
} from '@/composables/useDocumentError'

describe('documentErrorCopy', () => {
  it('names a deleted record', () => {
    expect(documentErrorCopy({ exc_type: 'DoesNotExistError' }).title).toBe(
      'Document not found',
    )
  })

  it('names anything else generically', () => {
    expect(documentErrorCopy({ exc_type: 'PermissionError' }).title).toBe(
      'Error occurred',
    )
  })

  it("prefers the server's own sentence", () => {
    expect(
      documentErrorCopy({
        exc_type: 'PermissionError',
        messages: ['Not permitted for CRM Organization ORG-0007'],
      }).message,
    ).toBe('Not permitted for CRM Organization ORG-0007')
  })

  it('falls back when the error carried no message', () => {
    expect(documentErrorCopy({ exc_type: 'ValidationError' }).message).toBe(
      'An error occurred',
    )
    expect(documentErrorCopy({ messages: [] }).message).toBe(
      'An error occurred',
    )
  })

  it('is empty for no error at all', () => {
    expect(documentErrorCopy(null)).toEqual({ title: '', message: '' })
    expect(documentErrorCopy('')).toEqual({ title: '', message: '' })
  })
})

describe('useDocumentError', () => {
  it('starts clear and follows the error ref', async () => {
    const error = ref('')
    const { errorTitle, errorMessage } = useDocumentError(error)

    expect(errorTitle.value).toBe('')

    error.value = { exc_type: 'DoesNotExistError', messages: ['gone'] }
    await nextTick()
    expect(errorTitle.value).toBe('Document not found')
    expect(errorMessage.value).toBe('gone')

    // a reload that succeeds has to take the page back
    error.value = ''
    await nextTick()
    expect(errorTitle.value).toBe('')
    expect(errorMessage.value).toBe('')
  })
})

/**
 * The composable exists because four pages had four different answers:
 * Deal and Lead watched the error inline, Organization and Contact declared
 * `errorTitle`/`errorMessage`, rendered an ErrorPage on them and never
 * assigned them -- a dead branch -- and the mobile Organization and Contact
 * pages had no branch at all, so a record outside the rep's hierarchy was a
 * blank screen with no header and no way back.
 */
describe('the record pages that had no failure state', () => {
  const pages = [
    'Organization.vue',
    'Contact.vue',
    'MobileOrganization.vue',
    'MobileContact.vue',
  ]

  it.each(pages)('%s renders an ErrorPage the composable can reach', (page) => {
    const source = readFileSync(join(process.cwd(), 'src/pages', page), 'utf8')
    expect(source).toMatch(/import ErrorPage from/)
    expect(source).toMatch(/<ErrorPage\s+v-else-if="errorTitle"/)
    expect(source).toMatch(/useDocumentError\(loadError\)/)
    // the refs must come from the composable, not be re-declared empty
    expect(source).not.toMatch(/const errorTitle = ref\(''\)/)
  })
})
