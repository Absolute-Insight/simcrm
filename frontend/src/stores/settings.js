import { createDocumentResource } from 'frappe-ui'
import { reportActionError } from '@/utils/reportActionError'
import { reactive, ref } from 'vue'

const settings = ref({})
const brand = reactive({})

/* Created at boot, so this is the FCRM Settings resource every pane saves
   through: frappe-ui returns the cached one to later callers and ignores their
   options, useDocument's and Hierarchy's onError included. A refused save
   therefore has to be reported here, or it is reported nowhere. */
const _settings = createDocumentResource({
  doctype: 'FCRM Settings',
  name: 'FCRM Settings',
  onSuccess: (data) => {
    settings.value = data
    getSettings().setupBrand()
    return data
  },
  setValue: {
    onError: (error) =>
      reportActionError(error, __('Could not save the settings.')),
  },
})

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
