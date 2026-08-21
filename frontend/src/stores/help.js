/**
 * The in-app help center's state: one resource for the shipped articles and
 * the flags the modal reads. Module-level refs, the same shape the other
 * shell surfaces use (see composables/modals.js, stores/suggestions.js).
 */
import { createResource } from 'frappe-ui'
import { ref } from 'vue'

export const helpCenterVisible = ref(false)

/** Article `name` the modal should show; null means the landing view. */
export const activeHelpArticle = ref(null)

export const helpContent = createResource({
  url: 'crm.api.help.get_articles',
  initialData: { categories: [], articles: [] },
  auto: false,
})

/**
 * Open the help center, optionally on a specific article — the assistant's
 * "related articles" chips land here. Content is fetched on first open, not
 * at app start: most sessions never open the manual.
 */
export function openHelpCenter(articleName = null) {
  activeHelpArticle.value = articleName
  helpCenterVisible.value = true
  if (!helpContent.fetched && !helpContent.loading) {
    helpContent.fetch()
  }
}
