<template>
  <!-- A radio group: Tab reaches the chosen theme, the arrow keys move
       between them, and Enter or Space picks one. The cards were bare
       <div @click>s, which nothing but a pointer could operate. -->
  <div
    ref="group"
    class="flex gap-3"
    role="radiogroup"
    :aria-label="__('Theme')"
    @keydown="onKeydown"
  >
    <button
      v-bind="option('light')"
      class="flex-1 rounded-[var(--v-radius-card)] border cursor-pointer text-left focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-outline-gray-3"
      :class="
        theme == 'light'
          ? 'border-outline-gray-7'
          : 'border-outline-elevation-2'
      "
    >
      <div class="pl-5 pt-3.5 bg-surface-gray-2 rounded-t-[10.5px]">
        <div class="bg-white rounded-tl-1">
          <div class="flex gap-[3px] py-[3px] px-1 border-b border-gray-100">
            <div class="size-1.5 bg-[#FF5F57] rounded-full"></div>
            <div class="size-1.5 bg-[#FEBC2D] rounded-full"></div>
            <div class="size-1.5 bg-[#28C840] rounded-full"></div>
          </div>
          <div class="flex items-start justify-between gap-2 p-2.5 pr-0 pb-1">
            <div
              class="flex items-center flex-1 gap-1 text-xs-semibold text-ink-gray-5"
            >
              <img
                v-if="typeof logo == 'string'"
                :src="logo"
                alt=""
                class="size-5 object-cover"
              />
              <component
                :is="logo"
                v-else
                class="size-5 shrink-0 rounded-[var(--v-radius-control)]"
              />
              <div>{{ __(name) }}</div>
            </div>
            <div class="flex flex-col flex-1 gap-[5px]">
              <div class="bg-gray-100 w-full h-1.5"></div>
              <div class="bg-gray-100 w-full h-1.5"></div>
              <div class="bg-gray-100 w-full h-1.5"></div>
            </div>
          </div>
        </div>
      </div>
      <div class="flex items-center justify-between px-3 py-2 border-t">
        <div class="text-base text-ink-gray-7">
          {{ __('Light') }}
        </div>
        <div
          class="rounded-full size-3.5"
          :class="
            theme == 'light'
              ? 'border-4 border-outline-gray-7'
              : 'border  border-outline-gray-4'
          "
        />
      </div>
    </button>
    <button
      v-bind="option('dark')"
      class="flex-1 rounded-[var(--v-radius-card)] border cursor-pointer text-left focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-outline-gray-3"
      :class="
        theme == 'dark' ? 'border-outline-gray-7' : 'border-outline-elevation-2'
      "
    >
      <div class="pl-5 pt-3.5 bg-surface-gray-2 rounded-t-[10.5px]">
        <div class="bg-gray-900 rounded-tl-1">
          <div class="flex gap-[3px] py-[3px] px-1 border-b border-gray-800">
            <div class="size-1.5 bg-[#FF5F57] rounded-full"></div>
            <div class="size-1.5 bg-[#FEBC2D] rounded-full"></div>
            <div class="size-1.5 bg-[#28C840] rounded-full"></div>
          </div>
          <div class="flex items-start justify-between gap-2 p-2.5 pr-0 pb-1">
            <div
              class="flex items-center flex-1 gap-1 text-xs-semibold text-ink-gray-5"
            >
              <img
                v-if="typeof logo == 'string'"
                :src="logo"
                alt=""
                class="size-5 object-cover"
              />
              <component
                :is="logo"
                v-else
                class="size-5 shrink-0 rounded-[var(--v-radius-control)]"
              />
              <div>{{ __(name) }}</div>
            </div>
            <div class="flex flex-col flex-1 gap-[5px]">
              <div class="bg-gray-800 w-full h-1.5"></div>
              <div class="bg-gray-800 w-full h-1.5"></div>
              <div class="bg-gray-800 w-full h-1.5"></div>
            </div>
          </div>
        </div>
      </div>
      <div class="flex items-center justify-between px-3 py-2 border-t">
        <div class="text-base text-ink-gray-7">
          {{ __('Dark') }}
        </div>
        <div
          class="rounded-full size-3.5"
          :class="
            theme == 'dark'
              ? 'border-4 border-outline-gray-7'
              : 'border border-outline-gray-4'
          "
        />
      </div>
    </button>
    <button
      v-bind="option('system')"
      class="flex-1 rounded-[var(--v-radius-card)] border cursor-pointer text-left focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-outline-gray-3"
      :class="
        theme == 'system'
          ? 'border-outline-gray-7'
          : 'border-outline-elevation-2'
      "
    >
      <div class="flex">
        <div
          class="flex flex-1 pl-5 pt-3.5 bg-surface-gray-2 rounded-tl-[10.5px]"
        >
          <div class="bg-white rounded-tl-1 w-full">
            <div class="flex gap-[3px] py-[3px] px-1 border-b border-gray-100">
              <div class="size-1.5 bg-[#FF5F57] rounded-full"></div>
              <div class="size-1.5 bg-[#FEBC2D] rounded-full"></div>
              <div class="size-1.5 bg-[#28C840] rounded-full"></div>
            </div>
            <div class="flex items-start justify-between gap-2 p-2.5 pr-0 pb-1">
              <div
                class="flex items-center flex-1 gap-1 text-xs-semibold text-ink-gray-5"
              >
                <img
                  v-if="typeof logo == 'string'"
                  :src="logo"
                  alt=""
                  class="size-5 object-cover"
                />
                <component
                  :is="logo"
                  v-else
                  class="size-5 shrink-0 rounded-[var(--v-radius-control)]"
                />
                <div>{{ __(name) }}</div>
              </div>
            </div>
          </div>
        </div>
        <div
          class="flex flex-1 pl-5 pt-3.5 bg-surface-gray-3 rounded-tr-[10.5px]"
        >
          <div class="bg-gray-900 rounded-tl-1 w-full">
            <div class="flex gap-[3px] py-[3px] px-1 border-b border-gray-800">
              <div class="size-1.5 bg-[#FF5F57] rounded-full"></div>
              <div class="size-1.5 bg-[#FEBC2D] rounded-full"></div>
              <div class="size-1.5 bg-[#28C840] rounded-full"></div>
            </div>
            <div class="flex items-start justify-between gap-2 p-2.5 pb-3 pr-0">
              <div
                class="flex items-center flex-1 gap-1 text-xs-semibold text-ink-gray-5"
              >
                <img
                  v-if="typeof logo == 'string'"
                  :src="logo"
                  alt=""
                  class="size-5 object-cover"
                />
                <component
                  :is="logo"
                  v-else
                  class="size-5 shrink-0 rounded-[var(--v-radius-control)]"
                />
                <div>{{ __(name) }}</div>
              </div>
            </div>
          </div>
        </div>
      </div>
      <div class="flex items-center justify-between px-3 py-2 border-t">
        <div class="text-base text-ink-gray-7">
          {{ __('System') }}
        </div>
        <div
          class="rounded-full size-3.5"
          :class="
            theme == 'system'
              ? 'border-4 border-outline-gray-7'
              : 'border border-outline-gray-4'
          "
        ></div>
      </div>
    </button>
  </div>
</template>

<script setup>
import { useColorScheme } from 'frappe-ui'
import { computed, ref } from 'vue'

defineProps({
  logo: { type: [String, Object], default: '' },
  name: { type: String, default: '' },
})

const { colorScheme: currentTheme, setColorScheme: setTheme } = useColorScheme()

const theme = computed({
  get() {
    if (currentTheme.value === 'light') return 'light'
    if (currentTheme.value === 'dark') return 'dark'
    return 'system'
  },
  set(value) {
    setTheme(value)
  },
})

const THEMES = ['light', 'dark', 'system']
const group = ref(null)

// Built per render, so a language change re-resolves the names
function option(value) {
  const checked = theme.value === value
  return {
    type: 'button',
    role: 'radio',
    'aria-checked': String(checked),
    'aria-label': {
      light: __('Light'),
      dark: __('Dark'),
      system: __('System'),
    }[value],
    // roving: only the chosen theme is a Tab stop, the arrows reach the rest
    tabindex: checked ? 0 : -1,
    onClick: () => (theme.value = value),
  }
}

function onKeydown(event) {
  const step = { ArrowRight: 1, ArrowDown: 1, ArrowLeft: -1, ArrowUp: -1 }[
    event.key
  ]
  if (!step) return
  event.preventDefault()
  const index =
    (THEMES.indexOf(theme.value) + step + THEMES.length) % THEMES.length
  theme.value = THEMES[index]
  group.value?.querySelectorAll('[role="radio"]')[index]?.focus()
}
</script>
