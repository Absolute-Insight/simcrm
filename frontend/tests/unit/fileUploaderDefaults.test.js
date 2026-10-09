import { describe, expect, it } from 'vitest'
import {
  uploaderRestrictions,
  uploaderMakesAttachmentsPublic,
} from '@/utils/fileUploaderDefaults'

const serverDefaults = {
  allowed_file_types: 'pdf\npng',
  max_file_size: 1000,
  max_number_of_files: 3,
  make_attachments_public: true,
}

describe('uploaderRestrictions', () => {
  it('uses the passed-in restrictions until the server answers', () => {
    expect(uploaderRestrictions(null)).toEqual({})
    expect(
      uploaderRestrictions(null, {
        restrictions: { allowedFileTypes: ['.csv'] },
      }),
    ).toEqual({ allowedFileTypes: ['.csv'] })
  })

  it('turns the server defaults into dotted extensions and limits', () => {
    expect(uploaderRestrictions(serverDefaults)).toEqual({
      allowedFileTypes: ['.pdf', '.png'],
      maxFileSize: 1000,
      maxNumberOfFiles: 3,
    })
  })

  it('allows any type when the server lists none', () => {
    expect(
      uploaderRestrictions({ ...serverDefaults, allowed_file_types: '' })
        .allowedFileTypes,
    ).toEqual([])
  })

  it('lets passed-in restrictions override the server, key by key', () => {
    expect(
      uploaderRestrictions(serverDefaults, {
        restrictions: { maxNumberOfFiles: 1 },
      }),
    ).toEqual({
      allowedFileTypes: ['.pdf', '.png'],
      maxFileSize: 1000,
      maxNumberOfFiles: 1,
    })
  })
})

describe('uploaderMakesAttachmentsPublic', () => {
  it('follows the passed-in option until the server answers', () => {
    expect(uploaderMakesAttachmentsPublic(null)).toBe(false)
    expect(
      uploaderMakesAttachmentsPublic(null, { makeAttachmentsPublic: true }),
    ).toBe(true)
  })

  it("follows the doctype's make_attachments_public once loaded", () => {
    expect(uploaderMakesAttachmentsPublic(serverDefaults)).toBe(true)
    expect(
      uploaderMakesAttachmentsPublic(
        { ...serverDefaults, make_attachments_public: false },
        { makeAttachmentsPublic: true },
      ),
    ).toBe(false)
  })
})
