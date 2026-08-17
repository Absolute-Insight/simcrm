import { computed, ref } from 'vue'

export const mobileSidebarOpened = ref(false)

/* Tailwind's `md` breakpoint, so JS and CSS agree about what "mobile" is. */
export const MOBILE_BREAKPOINT_PX = 768

/* This was `computed(() => window.innerWidth < 768)`: a computed over a source
   Vue cannot track, so it evaluated once and cached that answer forever. Every
   `v-if="isMobileView"` in the app is written as though it were live, and none
   of them were -- rotating a phone or dragging a window across the breakpoint
   changed nothing until a reload.

   A matchMedia listener rather than a resize listener: it fires only when the
   breakpoint is actually crossed, so dragging a window edge does not re-render
   the app on every pixel. `matchMedia` is guarded because the unit tests import
   this module under happy-dom, where it may be absent -- and a missing API must
   not take the whole module down with it. */
const mobileQuery =
  typeof window !== 'undefined' && typeof window.matchMedia === 'function'
    ? window.matchMedia(`(max-width: ${MOBILE_BREAKPOINT_PX - 1}px)`)
    : null

const mobileMatches = ref(
  mobileQuery
    ? mobileQuery.matches
    : typeof window !== 'undefined' && window.innerWidth < MOBILE_BREAKPOINT_PX,
)

if (mobileQuery) {
  const update = (event) => (mobileMatches.value = event.matches)
  // addEventListener is the modern form; addListener is kept for Safari < 14,
  // where the modern one is simply absent rather than deprecated.
  if (typeof mobileQuery.addEventListener === 'function') {
    mobileQuery.addEventListener('change', update)
  } else if (typeof mobileQuery.addListener === 'function') {
    mobileQuery.addListener(update)
  }
}

export const isMobileView = computed(() => mobileMatches.value)

export const showSettings = ref(false)

export const disableSettingModalOutsideClick = ref(false)

export const activeSettingsPage = ref('')
