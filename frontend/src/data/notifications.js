import { sessionStore } from '@/stores/session'
import { useEvent } from '@/composables/event'
import { quiet } from '@/utils/quiet'
import { dayjs, getConfig } from 'frappe-ui'
import isBetween from 'dayjs/plugin/isBetween'
import { useStorage } from '@vueuse/core'
import { getUserSettings, useUserSettings } from '@/data/userSettings'
import { ref, computed, onUnmounted, onMounted } from 'vue'

dayjs.extend(isBetween)

/* Event datetimes are stored naive, in the site's timezone. "Now" as
   toISOString() is UTC with a Z the comparison ignores, so on a site ahead of
   UTC it let in events that had ended hours ago. */
function siteNow() {
  const timezone = getConfig('systemTimezone')
  const now = dayjs()
  return (timezone ? now.tz(timezone) : now).format('YYYY-MM-DD HH:mm:ss')
}

export const useEventNotifications = () => {
  const { user } = sessionStore()
  const filters = {
    status: 'Open',
    owner: user,
    ends_on: ['>=', siteNow()],
  }

  /* The list is cached for the session, and frappe-ui hands a cached resource
     back with the filters it was created with -- and reloads it with them. So
     "now" was the first open's, and every later open listed the events that
     had ended since. Fetched here instead, on every open, with this one's. */
  const event = useEvent({ filters, notifications: false, auto: false })
  event.eventsResource.update({ filters })
  quiet(event.eventsResource.reload())
  return event
}

const eventNotificationAlerts = useStorage('eventNotificationAlerts', [])

/* The reminders the user has dismissed live here beside the alerts, not in
   each caller. The popup records a dismissal and Notifications.vue's socket
   handler decides whether to show the next send -- and the server re-sends a
   reminder on every scheduler tick inside its window. With a list per caller
   the handler never heard of the dismissal, so the reminder came back. */
const completedEvents = ref([])
let settingsLoad = null
let cleanupInterval = null
let mountedCallers = 0

export const useEventNotificationAlert = () => {
  const { save: saveUserSettings } = useUserSettings()

  // Loaded once a session, and merged, so a dismissal made before it returns
  // is kept. A failed load is tried again by the next caller to mount.
  const loadNotificationSettings = () => {
    settingsLoad ||= getUserSettings('Event', 'notifications')
      .then((settings) => {
        const saved = settings?.completedEvents || []
        completedEvents.value = [
          ...new Set([...saved, ...completedEvents.value]),
        ]
      })
      .catch((error) => {
        settingsLoad = null
        console.error('Error loading notification settings:', error)
      })
    return settingsLoad
  }

  // Save completed events to user settings
  const saveNotificationSettings = async () => {
    try {
      await saveUserSettings('Event', 'notifications', {
        completedEvents: completedEvents.value,
        lastUpdated: dayjs().format('YYYY-MM-DD HH:mm:ss'),
      })
    } catch (error) {
      console.error('Error saving notification settings:', error)
    }
  }

  // Check if event has already been completed/acknowledged
  const isEventCompleted = (eventId) => completedEvents.value.includes(eventId)

  // Get active (non-completed) notification alerts
  const activeAlerts = computed(() => {
    const now = dayjs()

    return eventNotificationAlerts.value.filter((alert) => {
      if (alert.completed || isEventCompleted(alert.id)) {
        return false
      }

      const notification = alert.notification
      if (notification && notification.ends_on) {
        const eventEndTime = dayjs(notification.ends_on)
        if (eventEndTime.isBefore(now)) {
          return false
        }
      }

      return true
    })
  })

  function handleEventNotification(event) {
    if (isEventCompleted(event.event_name)) return

    addEventNotificationAlert(event)
  }

  function addEventNotificationAlert(data) {
    // Don't add if already exists and not completed
    const existingAlert = eventNotificationAlerts.value.find(
      (alert) => alert.id === data.event_name && !alert.completed,
    )

    if (existingAlert) return

    eventNotificationAlerts.value.push({
      id: data.event_name,
      completed: false,
      notification: data,
      createdAt: dayjs().toISOString(),
    })
  }

  async function completeEventNotificationAlert(id) {
    let alert = eventNotificationAlerts.value.find((a) => a.id === id)
    if (alert) {
      alert.completed = true
    }

    // Add to completed events in user settings
    if (!completedEvents.value.includes(id)) {
      completedEvents.value.push(id)
      // the save writes the whole list, so it waits for the stored one
      await loadNotificationSettings()
      await saveNotificationSettings()
    }
  }

  function removeCompletedEventNotificationAlerts() {
    eventNotificationAlerts.value = eventNotificationAlerts.value.filter(
      (alert) => !alert.completed,
    )
  }

  function clearAllEventNotificationAlerts() {
    eventNotificationAlerts.value = []
  }

  async function clearCompletedEvents() {
    completedEvents.value = []
    await saveNotificationSettings()
  }

  async function cleanupExpiredEventAlerts() {
    const now = dayjs()
    const alertsToComplete = eventNotificationAlerts.value.filter((alert) => {
      if (alert.completed || isEventCompleted(alert.id)) {
        return false
      }

      const notification = alert.notification
      if (notification && notification.ends_on) {
        const eventEndTime = dayjs(notification.ends_on)
        return eventEndTime.isBefore(now)
      }

      return false
    })

    for (const alert of alertsToComplete) {
      await completeEventNotificationAlert(alert.id)
    }
  }

  onMounted(() => {
    loadNotificationSettings()
    cleanupExpiredEventAlerts()
    if (mountedCallers++ === 0) {
      cleanupInterval = setInterval(cleanupExpiredEventAlerts, 5 * 60 * 1000)
    }
  })

  onUnmounted(() => {
    if (--mountedCallers === 0) clearInterval(cleanupInterval)
  })

  return {
    eventNotificationAlerts,
    activeAlerts,
    completedEvents,
    isEventCompleted,
    handleEventNotification,
    addEventNotificationAlert,
    completeEventNotificationAlert,
    removeCompletedEventNotificationAlerts,
    clearAllEventNotificationAlerts,
    clearCompletedEvents,
    cleanupExpiredEventAlerts,
    loadNotificationSettings,
    saveNotificationSettings,
  }
}
