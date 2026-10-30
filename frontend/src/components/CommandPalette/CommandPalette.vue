<template>
  <Dialog
    v-model:open="commandPaletteOpen"
    bare
    size="2xl"
    position="top"
    padding-top="10vh"
  >
    <VisuallyHidden>
      <DialogTitle>{{ __('Search') }}</DialogTitle>
      <DialogDescription>
        {{ __('Find a record, go to a page or create something') }}
      </DialogDescription>
    </VisuallyHidden>
    <Combobox
      as="div"
      class="crm-command-palette"
      nullable
      @update:model-value="onSelection"
    >
      <div class="flex items-center border-b border-outline-gray-1 px-1">
        <LucideSearch class="ms-3 size-4 shrink-0 text-ink-gray-6" />
        <ComboboxInput
          ref="inputRef"
          :display-value="() => commandPaletteQuery"
          :placeholder="__('Search customers, deals, quotes...')"
          :aria-label="__('Search')"
          class="w-full border-none bg-transparent py-3.5 pe-4 ps-3 text-base text-ink-gray-9 placeholder-ink-gray-6 focus:outline-none focus:ring-0 focus-visible:outline-none focus-visible:ring-0"
          autofocus
          autocomplete="off"
          spellcheck="false"
          @input="onInput"
        />
      </div>

      <ComboboxOptions
        class="crm-command-palette-list max-h-[380px] min-h-[7rem] overflow-y-auto py-2"
        static
        :hold="true"
      >
        <div
          v-if="!commandPaletteItems.length"
          class="flex flex-col items-center py-12 text-ink-gray-6"
        >
          <component
            :is="emptyIcon"
            class="mb-2.5 size-8 opacity-60"
            :class="{ 'animate-spin': commandPaletteSearching }"
          />
          <span class="text-base">{{ emptyMessage }}</span>
        </div>
        <template v-else>
          <div v-for="group in commandPaletteGroups" :key="group.title">
            <div
              v-if="group.title"
              class="px-4 pb-1 pt-2 text-xs font-medium text-ink-gray-6"
            >
              {{ __(group.title) }}
            </div>
            <ComboboxOption
              v-for="(item, index) in group.items"
              :key="item.id"
              v-slot="{ active }"
              :value="item"
              class="cursor-pointer scroll-my-10 px-2"
              :class="{ 'scroll-mt-16': index === 0 }"
              :disabled="item.disabled"
            >
              <CommandPaletteRow :command="item" :active="active" />
            </ComboboxOption>
          </div>
        </template>
      </ComboboxOptions>

      <div
        class="hidden items-center gap-4 border-t border-outline-gray-1 px-4 py-2.5 text-xs text-ink-gray-6 md:flex"
      >
        <span
          v-for="(hint, index) in hints"
          :key="index"
          class="flex items-center gap-1.5"
          :class="{ 'ms-auto': hint.trailing }"
        >
          <kbd
            v-for="key in hint.keys"
            :key="key"
            class="rounded-1 bg-surface-gray-2 px-1 py-0.5 font-sans text-ink-gray-7"
          >
            {{ key }}
          </kbd>
          {{ __(hint.label) }}
        </span>
      </div>
    </Combobox>
  </Dialog>
</template>

<script setup>
import {
  Combobox,
  ComboboxInput,
  ComboboxOption,
  ComboboxOptions,
} from '@headlessui/vue'
import { Dialog } from 'frappe-ui'
import { DialogDescription, DialogTitle, VisuallyHidden } from 'reka-ui'
import { computed, nextTick, ref, watch } from 'vue'
import LucideLoaderCircle from '~icons/lucide/loader-circle'
import LucideSearch from '~icons/lucide/search'
import LucideSearchX from '~icons/lucide/search-x'
import CommandPaletteRow from './CommandPaletteRow.vue'
import { useCRMCommands } from './useCRMCommands'
import { useKeyboardShortcuts } from '@/composables/useKeyboardShortcuts'
import {
  closeCommandPalette,
  commandPaletteGroups,
  commandPaletteItems,
  commandPaletteOpen,
  commandPaletteQuery,
  commandPaletteSearching,
  openCommandPalette,
  restoreCommandPaletteFocus,
  runCommandPaletteItem,
} from '@/composables/useCommandPalette'

useCRMCommands()

const hints = [
  { keys: ['↑', '↓'], label: 'Navigate' },
  { keys: ['↵'], label: 'Select' },
  { keys: ['esc'], label: 'Close', trailing: true },
]

const inputRef = ref(null)

// Never re-key the Combobox: headlessui selects the active option on blur.
watch(commandPaletteOpen, (open) =>
  nextTick(() => {
    const input = inputRef.value?.$el
    if (open && input) {
      input.value = commandPaletteQuery.value
      input.focus()
    }
    if (!open) restoreCommandPaletteFocus()
  }),
)

const emptyIcon = computed(() => {
  if (commandPaletteSearching.value) return LucideLoaderCircle
  return commandPaletteQuery.value ? LucideSearchX : LucideSearch
})

const emptyMessage = computed(() => {
  if (commandPaletteSearching.value) return __('Searching...')
  return commandPaletteQuery.value
    ? __('No results for "{0}"', [commandPaletteQuery.value])
    : __('Type to search')
})

function onInput(event) {
  commandPaletteQuery.value = event.target.value
}

function onSelection(command) {
  if (command) runCommandPaletteItem(command)
}

function togglePalette() {
  if (commandPaletteOpen.value) closeCommandPalette()
  else openCommandPalette()
}

useKeyboardShortcuts({
  ignoreTyping: false,
  skipWhenDialogOpen: false,
  shortcuts: [
    {
      match: (event) =>
        (event.metaKey || event.ctrlKey) && event.key.toLowerCase() === 'k',
      // Ctrl/Cmd+K is the link shortcut inside an editor.
      guard: (event) => !event.target?.closest?.('.ProseMirror'),
      action: togglePalette,
    },
  ],
})
</script>

<style>
.dialog-content[data-state='open']:has(.crm-command-palette) {
  transform-origin: center;
  animation: palette-open 180ms cubic-bezier(0.2, 1, 0.4, 1);
}

@keyframes palette-open {
  from {
    opacity: 0;
    transform: scale(0.94);
  }
  to {
    opacity: 1;
    transform: scale(1);
  }
}

@media (prefers-reduced-motion: reduce) {
  .dialog-content[data-state='open']:has(.crm-command-palette) {
    animation: none;
  }
}

@property --palette-fade-top {
  syntax: '<length>';
  inherits: false;
  initial-value: 0px;
}

@property --palette-fade-bottom {
  syntax: '<length>';
  inherits: false;
  initial-value: 0px;
}

/* Fades only the edges with more to scroll to, so a list cut off at the footer
   reads as a list that continues. No fade at either end or when nothing scrolls. */
.crm-command-palette-list {
  mask-image: linear-gradient(
    to bottom,
    transparent,
    #000 var(--palette-fade-top),
    #000 calc(100% - var(--palette-fade-bottom)),
    transparent
  );
  animation:
    palette-fade-top linear both,
    palette-fade-bottom linear both;
  animation-timeline: scroll(self), scroll(self);
  animation-range:
    0 2rem,
    calc(100% - 2rem) 100%;
}

@keyframes palette-fade-top {
  to {
    --palette-fade-top: 2.5rem;
  }
}

@keyframes palette-fade-bottom {
  from {
    --palette-fade-bottom: 2.5rem;
  }
  to {
    --palette-fade-bottom: 0px;
  }
}
</style>
