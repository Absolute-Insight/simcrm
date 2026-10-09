/**
 * The upload restrictions FilesUploaderArea enforces, from the server's
 * per-doctype defaults (crm.api.get_file_uploader_defaults) and the caller's
 * options. Restrictions passed in options override the server's, key by key;
 * until the server answers, only the passed-in ones apply.
 */
export function uploaderRestrictions(data, options = {}) {
  const propRestrictions = options.restrictions || {}
  if (!data) return propRestrictions

  return {
    allowedFileTypes: data.allowed_file_types
      ? data.allowed_file_types.split('\n').map((ext) => `.${ext}`)
      : [],
    maxFileSize: data.max_file_size,
    maxNumberOfFiles: data.max_number_of_files,
    ...propRestrictions,
  }
}

/**
 * Whether new files start public. The doctype's make_attachments_public wins
 * once the server has answered; before that, the caller's option applies.
 */
export function uploaderMakesAttachmentsPublic(data, options = {}) {
  if (!data) return Boolean(options.makeAttachmentsPublic)
  return Boolean(data.make_attachments_public)
}
