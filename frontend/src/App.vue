<template>
  <FrappeUIProvider>
    <NotPermitted v-if="$route.name === 'Not Permitted'" />
    <router-view v-else-if="$route.name === 'Onboarding'" />
    <Layout v-else-if="session.isLoggedIn" class="isolate">
      <router-view :key="$route.fullPath" />
    </Layout>
    <Dialogs />
    <DoctypeModals />
    <EventNotificationPopup />
  </FrappeUIProvider>
</template>

<script setup>
import NotPermitted from '@/pages/NotPermitted.vue'
import EventNotificationPopup from '@/components/EventNotificationPopup.vue'
import DoctypeModals from '@/components/Modals/DoctypeModals.vue'
import { Dialogs } from '@/utils/dialogs'
import { sessionStore } from '@/stores/session'
import { isMobileView } from '@/composables/settings'
import { FrappeUIProvider, setConfig } from 'frappe-ui'
import { computed, defineAsyncComponent, provide } from 'vue'

const session = sessionStore()
provide('session', session)

const MobileLayout = defineAsyncComponent(
  () => import('./components/Layouts/MobileLayout.vue'),
)
const DesktopLayout = defineAsyncComponent(
  () => import('./components/Layouts/DesktopLayout.vue'),
)
/* This read the viewport width directly, at 640 -- a second and narrower
   breakpoint than the router's 768, so between the two an iPad in split view
   got mobile pages inside the desktop shell. It was also evaluated once and
   cached forever, because a computed cannot track a plain width read: rotating
   a tablet across the boundary left the wrong shell up until a reload.
   isMobileView is the same constant the router now uses, behind a matchMedia
   listener. */
const Layout = computed(() =>
  isMobileView.value ? MobileLayout : DesktopLayout,
)

setConfig('systemTimezone', window.timezone?.system || null)
setConfig('localTimezone', window.timezone?.user || null)
setConfig('translatedMessages', window.translated_messages || {})
</script>
