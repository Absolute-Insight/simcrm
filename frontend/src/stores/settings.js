import { createDocumentResource } from 'frappe-ui'
import { reportActionError } from '@/utils/reportActionError'
import { computed, reactive } from 'vue'

const brand = reactive({})

/* Created at boot, so this is the FCRM Settings resource every pane saves
   through: frappe-ui returns the cached one to later callers and ignores their
   options, useDocument's and Hierarchy's onError included. A refused save
   therefore has to be reported here, or it is reported nowhere. */
const _settings = createDocumentResource({
  doctype: 'FCRM Settings',
  name: 'FCRM Settings',
  onSuccess: () => getSettings().setupBrand(),
  setValue: {
    onError: (error) =>
      reportActionError(error, __('Could not save the settings.')),
  },
})

/* The saved settings, for everything outside the Settings panes. This was a
   ref set once, in the first fetch's onSuccess, to `_settings.doc` itself: a
   pane's unsaved edits showed app-wide, and once the first save replaced that
   doc the ref never changed again -- the second Brand save of a session left
   the sidebar on the first one's name. `originalDoc` is what the resource last
   read from, or wrote to, the server. */
const settings = computed(() => _settings.originalDoc || {})

export function getSettings() {
  function setupBrand() {
    brand.name = settings.value?.brand_name
    brand.logo = settings.value?.brand_logo
    brand.favicon = settings.value?.favicon
  }

  return {
    _settings,
    settings,
    brand,
    setupBrand,
  }
}
