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
    onError: () => {
      /* The params were cleared only on success, so a per-document mark that
         failed left its `doc` behind on the shared resource -- and the next
         "mark all as read", which reloads with whatever params are sitting
         there, marked that one document instead of the inbox. */
      mark_as_read.params = {}
    },
  })

  /* Explicit rather than a bare reload(): reload() re-sends the last params,
     which is the whole of the bug above. `{}` is truthy, so it replaces them
     rather than falling back to them. */
  function mark_all_as_read() {
    return mark_as_read.submit({})
  }

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
    mark_all_as_read,
    mark_doc_as_read,
    toggle,
  }
})
