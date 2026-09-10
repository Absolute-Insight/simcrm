import { getScript } from '@/data/script'
import { newDocumentDraft } from '@/utils/newDocument'
import { globalStore } from '@/stores/global'
import { getMeta } from '@/stores/meta'
import { useAttachments } from '@/composables/useAttachments'
import { showSettings, activeSettingsPage } from '@/composables/settings'
import { runSequentially, parseAssignees, sanitizeText } from '@/utils'
import { findMissingMandatory } from '@/utils/fieldTransforms'
import { validationErrorMessage } from '@/utils/formScriptErrors'
import { createDocumentResource, createResource, toast } from 'frappe-ui'
import { ref, reactive, getCurrentInstance } from 'vue'

const documentsCache = {}
const controllersCache = {}
const assigneesCache = {}
const permissionsCache = {}
/* Setups in flight, keyed the same way as controllersCache. The re-entrancy
   guard used to be `controllersCache[...] = {}` written before the await, which
   doubled as a permanent "already tried" marker: a script that threw while
   being set up left an empty controller map behind and was never evaluated
   again for that record, not even on a fresh mount. */
const setupPromises = {}

/**
 * Surface a Form Script failure the way a blocked save already does.
 *
 * onValidate was fixed to toast; onLoad, onRender, onSave and onError were
 * called without an await and without a catch, so a script that threw in one
 * of them produced an unhandled rejection in the console and nothing at all on
 * screen -- a record with no scripted behaviour and no explanation.
 *
 * Takes the promise rather than being wrapped around the call so it reads the
 * same at every site, and stays fire-and-forget: reporting must not make the
 * caller wait, and it must never reject in turn.
 */
function reportScriptFailure(promise, fallback) {
  return Promise.resolve(promise).catch((err) => {
    const message = validationErrorMessage(err, fallback)
    if (message) toast.error(message)
    console.error(err)
  })
}

// Deleting a doc makes the framework emit a realtime `doc_update` as part of
// delete_doc, so the still-mounted document resource refetches and hits a
// DoesNotExistError just as we navigate away. Docs listed here have that one
// expected error swallowed instead of flashed as a toast and an error page.
const intentionallyDeletedDocs = new Set()

export function markDocumentAsDeleted(doctype, docname) {
  intentionallyDeletedDocs.add(`${doctype}:${docname}`)
}

// Called once the delete request has finished, so a reused docname does not
// have a later, unrelated error silently swallowed. Kept separate from
// markDocumentAsDeleted so the marker covers the whole (possibly slow) request
// rather than a fixed window starting before it.
export function expireDeletionMarker(doctype, docname) {
  const key = `${doctype}:${docname}`
  setTimeout(() => intentionallyDeletedDocs.delete(key), 10000)
}

// Called when the delete request itself fails, so a legitimate later
// DoesNotExistError for this doc is not swallowed.
export function unmarkDocumentAsDeleted(doctype, docname) {
  intentionallyDeletedDocs.delete(`${doctype}:${docname}`)
}

export function useDocument(doctype, docname, resourceOverrides = {}) {
  if (typeof docname === 'number') docname = String(docname)
  const { setupScript, scripts } = getScript(doctype)
  const meta = getMeta(doctype)
  const { trackOldFile, processPendingDeletions } = useAttachments(
    doctype,
    docname,
  )

  const vm = getCurrentInstance()?.proxy
  documentsCache[doctype] = documentsCache[doctype] || {}

  const error = ref('')

  if (!documentsCache[doctype][docname || '']) {
    if (docname) {
      documentsCache[doctype][docname] = createDocumentResource(
        {
          realtime: Boolean(vm?.$socket),
          doctype: doctype,
          name: docname,
          onSuccess: async () => await setupFormScript(),
          onError: (err) => {
            const deletionKey = `${doctype}:${docname}`
            if (
              err.exc_type === 'DoesNotExistError' &&
              intentionallyDeletedDocs.has(deletionKey)
            ) {
              intentionallyDeletedDocs.delete(deletionKey)
              return
            }
            error.value = err
            if (err.exc_type === 'DoesNotExistError') {
              toast.error(__(err.messages[0] || 'Document does not exist'))
            }
            if (err.exc_type === 'PermissionError') {
              toast.error(
                __(
                  err.messages[0] ||
                    'You do not have permission to access this document',
                ),
              )
            }
          },
          setValue: {
            onSuccess: () => {
              reportScriptFailure(
                triggerOnSave(),
                __('This form script failed after the save.'),
              )
              toast.success(__('Document updated successfully'))
              processPendingDeletions()
            },
            onError: (err) => {
              reportScriptFailure(
                triggerOnError(err),
                __('This form script failed while reporting an error.'),
              )

              if (err.exc_type == 'MandatoryError') {
                const fieldName = err.messages
                  .map((msg) => {
                    let arr = msg.split(': ')
                    return arr[arr.length - 1].trim()
                  })
                  .join(', ')
                toast.error(__('Mandatory field error: {0}', [fieldName]))
                return
              }

              err.messages?.forEach((msg) => {
                toast.error(msg)
              })

              if (err.messages?.length === 0) {
                toast.error(__('An error occurred while updating the document'))
              }

              console.error(err)
            },
          },
          ...resourceOverrides,
        },
        vm,
      )
      if (!documentsCache[doctype][docname].fieldHtmlMap) {
        documentsCache[doctype][docname].fieldHtmlMap = {}
      }
      if (!documentsCache[doctype][docname].fieldPropertyOverrides) {
        documentsCache[doctype][docname].fieldPropertyOverrides = {}
      }

      // Override the submit function to trigger validation before submitting
      // TODO: fix validate function to return error message instead of throwing error in frappe-ui and remove try-catch block here
      const _save = documentsCache[doctype][docname].save
      const _originalSubmit = _save.submit
      _save.submit = async function (...args) {
        try {
          await triggerOnValidate()
        } catch (err) {
          /* Blocking the save was correct; saying nothing was not. The Form
             Script guide promises a thrown error is "shown as a toast
             automatically", and only throwError delivered that — a plain
             `new Error`, the idiom the docs list first, left the rep pressing
             a save button that did nothing. */
          const message = validationErrorMessage(
            err,
            __('This could not be saved.'),
          )
          if (message) toast.error(message)
          console.error(err)
          return
        }
        const mandatory = checkMandatory(documentsCache[doctype][docname].doc)
        if (mandatory) return
        return _originalSubmit.apply(_save, args)
      }
    } else {
      documentsCache[doctype][''] = reactive({
        doc: newDocumentDraft(doctype),
        fieldPropertyOverrides: {},
      })
      setupFormScript()
    }
  }

  assigneesCache[doctype] = assigneesCache[doctype] || {}

  if (!assigneesCache[doctype][docname || '']) {
    assigneesCache[doctype][docname || ''] = createResource({
      url: 'crm.api.doc.get_assigned_users',
      cache: `assignees:${doctype}:${docname}`,
      auto: docname ? true : false,
      params: {
        doctype: doctype,
        name: docname,
      },
      transform: (data) => parseAssignees(data),
    })
  }

  permissionsCache[doctype] = permissionsCache[doctype] || {}

  if (!permissionsCache[doctype][docname || '']) {
    permissionsCache[doctype][docname || ''] = createResource({
      url: 'frappe.client.get_doc_permissions',
      cache: `permissions:${doctype}:${docname}`,
      auto: docname ? true : false,
      params: {
        doctype: doctype,
        docname: docname,
      },
      initialData: { permissions: {} },
    })
  }

  async function setupFormScript() {
    const key = docname || ''

    if (typeof controllersCache[doctype]?.[key] === 'object') return

    // A second caller while the first is still awaiting the script joins it
    // rather than evaluating the class twice.
    setupPromises[doctype] = setupPromises[doctype] || {}
    if (setupPromises[doctype][key]) return setupPromises[doctype][key]

    const run = (async () => {
      const { makeCall } = globalStore()

      let helpers = {}

      helpers.crm = {
        makePhoneCall: makeCall,
        openSettings: (page) => {
          showSettings.value = true
          activeSettingsPage.value = page
        },
      }

      const controllersArray = await setupScript(
        documentsCache[doctype][key],
        helpers,
      )

      controllersCache[doctype] = controllersCache[doctype] || {}

      if (!controllersArray || controllersArray.length === 0) {
        // A doctype with no script is a settled answer, not a failure: cache
        // the empty map so the fetch is not repeated on every mount.
        controllersCache[doctype][key] = {}
        return
      }

      const organizedControllers = {}
      for (const controller of controllersArray) {
        const controllerKey =
          controller._className || controller.constructor.name
        if (!organizedControllers[controllerKey]) {
          organizedControllers[controllerKey] = []
        }
        organizedControllers[controllerKey].push(controller)
      }
      controllersCache[doctype][key] = organizedControllers

      // Reported rather than rethrown, and onRender still runs when onLoad
      // throws: they are independent hooks, and the controllers are already
      // cached by this point, so a broken onLoad must not cost the record its
      // buttons and onChange handlers as well.
      await reportScriptFailure(
        triggerOnLoad(),
        __('This form script failed while loading the record.'),
      )
      await reportScriptFailure(
        triggerOnRender(),
        __('This form script failed while rendering the record.'),
      )
    })()

    // Guarded before it is shared, so a joining caller cannot be handed a
    // promise that rejects into nothing.
    const guarded = reportScriptFailure(
      run,
      __('This form script could not be loaded.'),
    ).finally(() => delete setupPromises[doctype][key])

    setupPromises[doctype][key] = guarded
    return guarded
  }

  function getControllers(row = null) {
    const _doctype = row?.doctype || doctype
    const controllerKey = _doctype.replace(/\s+/g, '')

    const docControllers = controllersCache[doctype]?.[docname || '']

    if (
      typeof docControllers === 'object' &&
      docControllers !== null &&
      !Array.isArray(docControllers)
    ) {
      return docControllers[controllerKey] || []
    }
    return []
  }

  function checkMandatory(doc) {
    let fields = meta?.doctypesMeta?.[doctype]?.fields || []

    if (!fields || fields.length === 0) return

    const overrides =
      documentsCache[doctype][docname || '']?.fieldPropertyOverrides || {}

    const missingFields = findMissingMandatory(fields, doc, {
      propertyOverrides: overrides,
      doctypesMeta: meta?.doctypesMeta || {},
    })

    if (missingFields.length > 0) {
      toast.error(
        __('Mandatory fields required: {0}', [missingFields.join(', ')]),
      )
      return __('Mandatory fields required: {0}', [missingFields.join(', ')])
    }
  }

  async function triggerOnLoad() {
    const handler = async function () {
      await (this.onLoad?.() || this.on_load?.() || this.onload?.())
    }
    await trigger(handler)
  }

  async function triggerOnRender() {
    const handler = async function () {
      await (this.onRender?.() || this.on_render?.() || this.refresh?.())
    }
    await trigger(handler)
  }

  async function triggerOnBeforeCreate() {
    const args = Array.from(arguments)
    const handler = async function () {
      await (this.onBeforeCreate?.(...args) || this.on_before_create?.(...args))
    }
    await trigger(handler)
  }

  async function triggerOnValidate() {
    const handler = async function () {
      await (this.onValidate?.() || this.on_validate?.() || this.validate?.())
    }
    await trigger(handler)
  }

  async function triggerOnSave() {
    const handler = async function () {
      await (this.onSave?.() || this.on_save?.())
    }
    await trigger(handler)
  }

  async function triggerOnError() {
    const handler = async function () {
      await (this.onError?.() || this.on_error?.())
    }
    await trigger(handler)
  }

  async function triggerOnChange(fieldname, _value, row) {
    const value = sanitizeText(_value)
    let oldValue = null
    if (row) {
      oldValue = row[fieldname]
      row[fieldname] = value
    } else {
      oldValue = documentsCache[doctype][docname || ''].doc[fieldname]
      documentsCache[doctype][docname || ''].doc[fieldname] = value
      trackOldFile(oldValue, value)
    }

    const handler = async function () {
      this.value = value
      this.oldValue = oldValue
      if (row) {
        this.currentRowIdx = row.idx
      }
      await this[fieldname]?.()
    }

    try {
      await trigger(handler, row)
    } catch (error) {
      console.error(handler)
      throw error
    }
  }

  async function triggerButton(fieldname, row) {
    const handler = async function () {
      if (row) {
        this.currentRowIdx = row.idx
      }
      await this[fieldname]?.()
    }
    await trigger(handler, row)
  }

  async function triggerOnRowAdd(row) {
    const handler = async function () {
      this.currentRowIdx = row.idx
      this.value = row
      await this[row.parentfield + '_add']?.()
    }

    await trigger(handler, row)
  }

  async function triggerOnRowRemove(selectedRows, rows) {
    const handler = async function () {
      if (selectedRows.size === 1) {
        const selectedRow = Array.from(selectedRows)[0]
        this.currentRowIdx = rows.find((r) => r.name === selectedRow).idx
      } else {
        delete this.currentRowIdx
      }

      this.selectedRows = Array.from(selectedRows)
      this.rows = rows

      await this[rows[0].parentfield + '_remove']?.()
    }

    await trigger(handler, rows[0])
  }

  async function triggerOnCreateLead() {
    const args = Array.from(arguments)
    const handler = async function () {
      await (this.onCreateLead?.(...args) || this.on_create_lead?.(...args))
    }
    await trigger(handler)
  }

  async function triggerConvertToDeal() {
    const args = Array.from(arguments)
    const handler = async function () {
      await (this.convertToDeal?.(...args) || this.convert_to_deal?.(...args))
    }
    await trigger(handler)
  }

  function setFieldHtml(fieldname, html) {
    const cache = documentsCache[doctype][docname || '']
    if (!cache.fieldHtmlMap) cache.fieldHtmlMap = {}
    cache.fieldHtmlMap[fieldname] = html
  }

  async function trigger(taskFn, row = null) {
    const controllers = getControllers(row)
    if (!controllers.length) return

    const tasks = controllers.map(
      (controller) => async () => await taskFn.call(controller),
    )

    await runSequentially(tasks)
  }

  return {
    document: documentsCache[doctype][docname || ''],
    assignees: assigneesCache[doctype][docname || ''],
    permissions: permissionsCache[doctype][docname || ''],
    scripts,
    error,
    getControllers,
    triggerOnLoad,
    triggerOnRender,
    triggerOnBeforeCreate,
    triggerOnValidate,
    triggerOnSave,
    triggerOnError,
    triggerOnChange,
    triggerButton,
    triggerOnRowAdd,
    triggerOnRowRemove,
    setupFormScript,
    triggerOnCreateLead,
    triggerConvertToDeal,
    setFieldHtml,
  }
}
