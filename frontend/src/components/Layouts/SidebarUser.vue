<template>
  <!-- The signed-in user, moved out of the header dropdown. Settings and log out
       are plain icon buttons rather than menu entries; collapsed, they stack
       into their own centred rows so neither becomes unreachable.

       `settings` is hidden on mobile because the settings dialog is desktop-only
       -- the same condition the dropdown applied before. -->
  <div class="flex flex-col gap-1">
    <div
      class="flex h-10 items-center rounded-5 duration-300 ease-in-out"
      :class="isCollapsed ? 'justify-center px-0' : 'px-2'"
    >
      <Avatar
        :label="user.full_name"
        :image="user.user_image"
        size="sm"
        class="shrink-0"
      />
      <div
        class="flex-1 truncate text-left duration-300 ease-in-out"
        :class="
          isCollapsed
            ? 'ml-0 w-0 overflow-hidden opacity-0'
            : 'ml-2 w-auto opacity-100'
        "
      >
        <div class="truncate text-base leading-none text-ink-gray-8">
          {{ user.full_name }}
        </div>
      </div>
      <template v-if="!isCollapsed">
        <button
          class="grid size-6 shrink-0 place-items-center rounded-4 text-ink-gray-7 hover:bg-surface-gray-2"
          :aria-label="__('Help')"
          :title="__('Help')"
          @click="() => openHelpCenter()"
        >
          <HelpIcon class="size-4" />
        </button>
        <button
          v-if="!isMobileView"
          class="ml-1 grid size-6 shrink-0 place-items-center rounded-4 text-ink-gray-7 hover:bg-surface-gray-2"
          :aria-label="__('Settings')"
          :title="__('Settings')"
          @click="openSettings"
        >
          <SettingsIcon class="size-4" />
        </button>
        <button
          class="ml-1 grid size-6 shrink-0 place-items-center rounded-4 text-ink-gray-7 hover:bg-surface-gray-2"
          :aria-label="__('Log out')"
          :title="__('Log out')"
          @click="logout.submit()"
        >
          <LogOutIcon class="size-4" />
        </button>
      </template>
    </div>

    <template v-if="isCollapsed">
      <button
        class="mx-auto grid size-6 place-items-center rounded-4 text-ink-gray-7 hover:bg-surface-gray-2"
        :aria-label="__('Help')"
        :title="__('Help')"
        @click="() => openHelpCenter()"
      >
        <HelpIcon class="size-4" />
      </button>
      <button
        v-if="!isMobileView"
        class="mx-auto grid size-6 place-items-center rounded-4 text-ink-gray-7 hover:bg-surface-gray-2"
        :aria-label="__('Settings')"
        :title="__('Settings')"
        @click="openSettings"
      >
        <SettingsIcon class="size-4" />
      </button>
      <button
        class="mx-auto grid size-6 place-items-center rounded-4 text-ink-gray-7 hover:bg-surface-gray-2"
        :aria-label="__('Log out')"
        :title="__('Log out')"
        @click="logout.submit()"
      >
        <LogOutIcon class="size-4" />
      </button>
    </template>
  </div>
</template>

<script setup>
import LogOutIcon from '~icons/lucide/log-out'
import HelpIcon from '@/components/Icons/HelpIcon.vue'
import SettingsIcon from '@/components/Icons/SettingsIcon.vue'
import { sessionStore } from '@/stores/session'
import { usersStore } from '@/stores/users'
import { showSettings, isMobileView } from '@/composables/settings'
import { openHelpCenter } from '@/stores/help'
import { Avatar } from 'frappe-ui'
import { computed } from 'vue'

defineProps({
  isCollapsed: { type: Boolean, default: false },
})

const { logout } = sessionStore()
const { getUser } = usersStore()

const user = computed(() => getUser() || {})

function openSettings() {
  showSettings.value = true
}
</script>
