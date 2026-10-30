import { computed, ref, shallowRef } from 'vue'
import { groupCommands } from '@/utils/commandPalette'
import { toast } from 'frappe-ui'

export const commandPaletteOpen = ref(false)
export const commandPaletteQuery = ref('')
export const commandPaletteSearching = ref(false)

const commandProvider = shallowRef(() => [])
let previousFocus = null

export const commandPaletteGroups = computed(() =>
  groupCommands(commandProvider.value(), commandPaletteQuery.value),
)

export const commandPaletteItems = computed(() =>
  commandPaletteGroups.value.flatMap((group) => group.items),
)

export function setCommandPaletteProvider(provider) {
  commandProvider.value = provider
}

export function openCommandPalette() {
  previousFocus = document.activeElement
  commandPaletteQuery.value = ''
  commandPaletteOpen.value = true
}

export function closeCommandPalette() {
  commandPaletteOpen.value = false
}

export function restoreCommandPaletteFocus() {
  requestAnimationFrame(() => {
    if (document.activeElement === document.body) previousFocus?.focus?.()
    previousFocus = null
  })
}

export async function runCommandPaletteItem(command) {
  // Closing blurs the input, and headlessui re-emits the active option on blur.
  if (!command || command.disabled || !commandPaletteOpen.value) return
  closeCommandPalette()
  try {
    await command.perform?.()
  } catch (error) {
    console.error('Command palette action failed', error)
    toast.error(error?.messages?.[0] || __('Unable to run command'))
  }
}
