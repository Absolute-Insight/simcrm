import { createDocumentResource } from 'frappe-ui'
import { computed, reactive } from 'vue'

const brand = reactive({})

const _settings = createDocumentResource({
  doctype: 'FCRM Settings',
  name: 'FCRM Settings',
  onSuccess: () => getSettings().setupBrand(),
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
