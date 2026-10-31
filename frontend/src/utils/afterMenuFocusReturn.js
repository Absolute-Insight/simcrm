const MENU = '[role="menu"]'
const FOCUS_RETURN_TIMEOUT = 500

/**
 * Run `callback` once a just-activated menu has given focus back.
 *
 * A menu item's onClick runs while the menu still holds focus. reka closes the
 * menu, unmounts it and only then focuses its trigger, two timers later, and
 * how long that takes depends on the menu's exit. A popover opened from the
 * item in the meantime sees that focus land outside it and dismisses itself:
 * it flashes open, or never appears at all. So wait for the focus to arrive
 * rather than guess at a delay.
 *
 * Call it from the item's onClick. `callback` runs on the first focus outside
 * any menu, or at once if no menu has focus to give back. The timeout is only
 * a floor under a trigger that was removed, or that focus never came back to.
 *
 * @param {() => void} callback
 */
export function afterMenuFocusReturn(callback) {
  if (!document.activeElement?.closest?.(MENU)) {
    setTimeout(callback, 0)
    return
  }

  function finish() {
    document.removeEventListener('focusin', onFocusIn)
    clearTimeout(timeout)
    callback()
  }
  function onFocusIn(event) {
    if (!event.target.closest?.(MENU)) finish()
  }

  const timeout = setTimeout(finish, FOCUS_RETURN_TIMEOUT)
  document.addEventListener('focusin', onFocusIn)
}
