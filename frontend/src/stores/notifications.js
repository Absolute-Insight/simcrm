import { defineStore } from 'pinia'
import { createResource } from 'frappe-ui'
import { computed, ref } from 'vue'
import { formatCompactNumber } from '@/utils/numberFormat.js'
import { neverLoaded } from '@/utils/resourceState'

export const visible = ref(false)

export const notifications = createResource({
  url: 'crm.api.notifications.get_notifications',
  initialData: [],
  auto: true,
})

export const unreadNotificationsCount = computed(() => {
  const count = notifications.data?.filter((n) => !n.read).length || 0
  return count ? formatCompactNumber(count) : 0
})

/* Same trap as the suggestions badge: `initialData` is [], frappe-ui leaves it
   there when the first fetch fails, the filter counts 0, and the sidebar hides
   the badge -- indistinguishable from having read everything. */
export const unreadCountUnavailable = computed(() => neverLoaded(notifications))

export const notificationsStore = defineStore('crm-notifications', () => {
  const mark_as_read = createResource({
    url: 'crm.api.notifications.mark_as_read',
    onSuccess: () => {
      mark_as_read.params = {}
      notifications.reload()
    },
  })

  function toggle() {
    visible.value = !visible.value
  }

  function mark_doc_as_read(doc) {
    mark_as_read.params = { doc: doc }
    mark_as_read.reload()
    toggle()
  }

  return {
    unreadNotificationsCount,
    mark_as_read,
    mark_doc_as_read,
    toggle,
  }
})
