import { ref } from 'vue'

/**
 * The lucide sprite, put into the page the first time an icon needs it.
 *
 * frappe-ui's spritePlugin injected all 1777 symbols on boot: 488 KB of SVG
 * (82 KB gz) in the entry chunk, innerHTML-parsed into <body> on every cold
 * start, for the handful of icons drawn from it -- string icons through
 * Icon.vue (view icons, settings rows), FeatherIcon for @framework/ui, and
 * ViewModal's IconPicker, which lists the sprite's symbols. Those call this
 * instead, and the sprite arrives as its own chunk.
 */

/** True once the sprite is in the page; a `<use>` keyed on it re-resolves. */
export const lucideSpriteReady = ref(false)

let loading = null

export function ensureLucideSprite() {
  if (!loading) {
    loading = import('lucide-static/sprite.svg?raw')
      .then(({ default: sprite }) => {
        if (!document.getElementById('lucide-sprite')) {
          const div = document.createElement('div')
          div.id = 'lucide-sprite'
          div.style.display = 'none'
          div.innerHTML = sprite
          document.body.prepend(div)
        }
        lucideSpriteReady.value = true
      })
      .catch((error) => {
        // A chunk a release has since replaced: let the next icon try again.
        loading = null
        throw error
      })
  }
  return loading
}
