import { computed, ref } from 'vue'

export const mobileSidebarOpened = ref(false)

/* Tailwind's `md` breakpoint, so JS and CSS agree about what "mobile" is. */
export const MOBILE_BREAKPOINT_PX = 768

/* Below this the dashboard's 20-column drag grid stops being a grid: a panel
   laid out four columns wide gets a fifth of the viewport, which is ~140px at
   700px and truncates a number card to nothing. Not a Tailwind breakpoint,
   because it is not about the device — it is the width at which twenty columns
   stop dividing into readable ones. */
export const WIDE_GRID_BREAKPOINT_PX = 1000

/* These were `computed(() => window.innerWidth < 768)`: a computed over a source
   Vue cannot track, so it evaluated once and cached that answer forever. Every
   `v-if="isMobileView"` in the app is written as though it were live, and none
   of them were -- rotating a phone or dragging a window across the breakpoint
   changed nothing until a reload.

   A matchMedia listener rather than a resize listener: it fires only when the
   breakpoint is actually crossed, so dragging a window edge does not re-render
   the app on every pixel. `matchMedia` is guarded because the unit tests import
   this module under happy-dom, where it may be absent -- and a missing API must
   not take the whole module down with it. */
function belowWidth(px) {
  const query =
    typeof window !== 'undefined' && typeof window.matchMedia === 'function'
      ? window.matchMedia(`(max-width: ${px - 1}px)`)
      : null

  const matches = ref(
    query
      ? query.matches
      : typeof window !== 'undefined' && window.innerWidth < px,
  )

  if (query) {
    const update = (event) => (matches.value = event.matches)
    // addEventListener is the modern form; addListener is kept for Safari < 14,
    // where the modern one is simply absent rather than deprecated.
    if (typeof query.addEventListener === 'function') {
      query.addEventListener('change', update)
    } else if (typeof query.addListener === 'function') {
      query.addListener(update)
    }
  }
  return computed(() => matches.value)
}

export const isMobileView = belowWidth(MOBILE_BREAKPOINT_PX)

/* True where the drag grid should stop pretending to have twenty columns. */
export const isNarrowGrid = belowWidth(WIDE_GRID_BREAKPOINT_PX)

export const showSettings = ref(false)

export const disableSettingModalOutsideClick = ref(false)

export const activeSettingsPage = ref('')
