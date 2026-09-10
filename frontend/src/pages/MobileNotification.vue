<!-- eslint-disable vue/no-v-html -->
<template>
  <LayoutHeader>
    <template #left-header>
      <Breadcrumbs
        :items="[
          { label: __('Notifications'), route: { name: 'Notifications' } },
        ]"
      />
    </template>
    <template #right-header>
      <Button
        :tooltip="__('Mark all as read')"
        :label="__('Mark all as read')"
        :iconLeft="MarkAsDoneIcon"
        @click="markAllAsRead"
      />
    </template>
  </LayoutHeader>
  <div class="flex flex-col overflow-hidden text-ink-gray-9">
    <div
      v-if="notifications.data?.length"
      class="divide-y divide-outline-gray-1 overflow-y-auto text-base"
    >
      <RouterLink
        v-for="n in notifications.data"
        :key="notificationKey(n)"
        :to="notificationRoute(n)"
        class="flex cursor-pointer items-start gap-3 px-2.5 py-3 hover:bg-surface-gray-2"
        @click="mark_doc_as_read(n.notification_type_doc)"
      >
        <div class="mt-1 flex items-center gap-2.5">
          <div
            class="size-[5px] rounded-full"
            :class="[n.read ? 'bg-transparent' : 'bg-surface-gray-10']"
          />
          <WhatsAppIcon v-if="n.type == 'WhatsApp'" class="size-7" />
          <UserAvatar v-else :user="n.from_user.name" size="lg" />
        </div>
        <div>
          <div
            v-if="n.notification_text"
            v-html="sanitizeHTML(n.notification_text)"
          />
          <div v-else class="mb-2 space-x-1 leading-5 text-ink-gray-5">
            <span class="font-medium text-ink-gray-9">
              {{ n.from_user.full_name }}
            </span>
            <span>
              {{ __('mentioned you in {0}', [n.reference_doctype]) }}
            </span>
            <span class="font-medium text-ink-gray-9">
              {{ n.reference_name }}
            </span>
          </div>
          <div class="text-sm text-ink-gray-5">
            {{ __(timeAgo(n.creation)) }}
          </div>
        </div>
      </RouterLink>
    </div>
    <!-- "No New Notifications" was the answer to a failed fetch as well as an
         empty one, so an outage read as a cleared inbox. The desktop panel
         grew its own branch for this; the page had none. -->
    <ErrorState
      v-else-if="notifications.error"
      :error="notifications.error"
      :title="__('Could not load notifications')"
      :retry="() => notifications.reload()"
    />
    <div v-else class="flex flex-1 flex-col items-center justify-center gap-2">
      <NotificationsIcon class="h-20 w-20 text-ink-gray-2" />
      <div class="text-lg-medium text-ink-gray-4">
        {{ __('No New Notifications') }}
      </div>
    </div>
  </div>
</template>
<script setup>
import ErrorState from '@/components/ui/ErrorState.vue'
import LayoutHeader from '@/components/LayoutHeader.vue'
import WhatsAppIcon from '@/components/Icons/WhatsAppIcon.vue'
import MarkAsDoneIcon from '@/components/Icons/MarkAsDoneIcon.vue'
import NotificationsIcon from '@/components/Icons/NotificationsIcon.vue'
import UserAvatar from '@/components/UserAvatar.vue'
import { notifications, notificationsStore } from '@/stores/notifications'
import { globalStore } from '@/stores/global'
import { timeAgo, sanitizeHTML } from '@/utils'
import { notificationKey, notificationRoute } from '@/utils/notificationRoute'
import { quiet } from '@/utils/quiet'
import { Breadcrumbs } from 'frappe-ui'
import { onMounted, onBeforeUnmount } from 'vue'

const { $socket } = globalStore()
const { mark_all_as_read, mark_doc_as_read } = notificationsStore()

/* Passed to `off` by reference. A bare `off('crm_notification')` removes every
   listener on the event, including the sidebar's -- and this route is not
   width-guarded, so a desktop user who opens /notifications from a bookmark and
   clicks away used to stop the bell and the panel updating for the session. */
function onCrmNotification() {
  quiet(notifications.reload())
}

onBeforeUnmount(() => {
  $socket.off('crm_notification', onCrmNotification)
})

onMounted(() => {
  $socket.on('crm_notification', onCrmNotification)
})

function markAllAsRead() {
  mark_all_as_read()
}
</script>
