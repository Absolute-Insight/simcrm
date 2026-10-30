import { ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useDebounceFn, useStorage } from '@vueuse/core'

/**
 * Keeps the active record-page tab in sync with the URL hash and localStorage.
 *
 * v1 Tabs models the trigger `value` (a string), not an index, so this hands
 * back the tab's value. The export keeps the historical name `tabIndex` —
 * every record page binds `v-model="tabIndex"` — but the ref now holds the
 * active tab's `value`/`name`, which is also what the hash and storage always
 * stored, so persisted state from the index era keeps working.
 */
export function useActiveTabManager(tabs, storageKey) {
  const activeTab = useStorage(storageKey, 'activity')
  const route = useRoute()
  const router = useRouter()

  const valueOf = (tab) => tab?.value ?? tab?.name

  function findTab(name) {
    if (name == null) return undefined
    const needle = String(name).toLowerCase()
    return tabs.value?.find(
      (tab) => String(valueOf(tab) ?? '').toLowerCase() === needle,
    )
  }

  const changeTabTo = (tabName) => {
    const tab = findTab(tabName)
    if (!tab) return
    tabIndex.value = valueOf(tab)
  }

  const preserveLastVisitedTab = useDebounceFn((tabName) => {
    activeTab.value = String(tabName).toLowerCase()
  }, 300)

  function setActiveTabInUrl(tabName) {
    let hash = '#' + String(tabName).toLowerCase()
    if (route.hash === hash) return
    // Opening the feed for an anchor (see feedTab) keeps the anchor.
    if (isAnchor(route.hash) && valueOf(feedTab()) === tabName) return
    router.push({ ...route, hash })
  }

  function isAnchor(hash) {
    return Boolean(hash) && !findTab(hash.replace('#', ''))
  }

  function getActiveTabFromUrl() {
    return route.hash.replace('#', '')
  }

  /* A hash that names no tab is an anchor inside the feed: a mention
     notification links to `#<Comment name>`. It used to fall through to the
     stored tab, so a rep last on Emails landed where the comment is not
     rendered and Activities had nothing to scroll to. Open the feed and leave
     the hash alone; an anchor is not a tab worth remembering either. */
  function feedTab() {
    return findTab('activity') ?? findTab('comments') ?? tabs.value?.[0]
  }

  function getActiveTab() {
    const hash = getActiveTabFromUrl()
    const fromUrl = findTab(hash)
    if (fromUrl) {
      preserveLastVisitedTab(valueOf(fromUrl))
      return valueOf(fromUrl)
    }
    if (hash) return valueOf(feedTab())
    const fromStorage = findTab(activeTab.value)
    if (fromStorage) return valueOf(fromStorage)
    return valueOf(tabs.value?.[0])
  }

  const tabIndex = ref(getActiveTab())

  watch(tabIndex, (tabValue) => {
    if (tabValue == null) return
    setActiveTabInUrl(tabValue)
    preserveLastVisitedTab(tabValue)
  })

  watch(
    () => route.hash,
    (hashValue) => {
      if (!hashValue) return
      const tab = findTab(hashValue.replace('#', ''))
      if (!tab) {
        const feed = feedTab()
        if (feed) tabIndex.value = valueOf(feed)
        return
      }
      preserveLastVisitedTab(valueOf(tab))
      tabIndex.value = valueOf(tab)
    },
  )

  watch(tabs, () => {
    tabIndex.value = getActiveTab()
  })

  return { tabIndex, changeTabTo }
}
