import { nextTick, onBeforeUnmount, ref } from 'vue'

// App.vue keys <router-view> on $route.fullPath and a record page keeps its
// tab in the URL hash, so changing a Deal or Lead tab remounts the whole page.
// A request to open the composer on another tab has to outlive the page that
// made it: it waits here for the instance the tab change mounts.
const pending = new Set()

/**
 * The "Send an Email" hand-off from a tab without a composer to the Emails
 * tab. `openEmailBoxOnMount` is bound to Activities' `openEmailBox`, which
 * opens the composer when its panel mounts and hands the flag back.
 */
export function useEmailComposeOnTab(doctype, name) {
  const key = `${doctype}\u0000${name}`
  const openEmailBoxOnMount = ref(pending.delete(key))

  function openOnNextPanel() {
    pending.add(key)
    // Without a remount, this instance's own panel is the one that mounts.
    openEmailBoxOnMount.value = true
  }

  // Left unclaimed, the request would open the composer on a later visit. The
  // instance a remount brings claims it in the same patch that unmounts this
  // one, so it is dropped only once that patch is done.
  onBeforeUnmount(() => nextTick(() => pending.delete(key)))

  return { openEmailBoxOnMount, openOnNextPanel }
}
