/**
 * The shape an unsaved record has to start from, and the one way to get back
 * to it.
 *
 * `useDocument(doctype)` with no name hands back a *module-level* buffer that
 * lives for the whole session, so whatever the last creation form left in it is
 * what the next one opens with. Three call sites have to agree on how that
 * buffer is emptied, and the two that wrote the object inline drifted: one
 * dropped the `doctype` key -- which `getField` needs, so every field lookup
 * returned null for the rest of the session -- and one never emptied it at all,
 * which is how a deal came to be saved against the previous customer.
 *
 * It lives in utils rather than beside useDocument because data/document.js
 * cannot be imported outside a browser: it pulls in frappe-ui's resource
 * plugin at module scope, and a helper this load-bearing has to be testable.
 */

/** A fresh unsaved record for `doctype`. */
export function newDocumentDraft(doctype) {
  return { __newDocument: true, doctype }
}

/**
 * Empty a creation form's shared buffer back to a fresh unsaved record.
 *
 * Only `doc` is replaced, and it is replaced rather than cleared in place: the
 * old object may still be referenced by an in-flight create request.
 * `fieldPropertyOverrides` is left alone because it is what the doctype's Form
 * Script applied at onLoad, and the script is set up once per doctype -- so
 * clearing it here would drop those properties with nothing to re-apply them.
 *
 * Returns the new doc, or null when there is no buffer to reset.
 */
export function resetNewDocument(document, doctype) {
  if (!document) return null
  document.doc = newDocumentDraft(doctype)
  return document.doc
}
