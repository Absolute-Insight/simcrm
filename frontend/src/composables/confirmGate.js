import { computed, ref } from 'vue'

/* A confirmation the caller can `await`.
 *
 * `window.confirm` is the only thing in the browser that answers a question
 * synchronously, which is why guard code reaches for it: a route guard wants a
 * boolean, and blocking the whole tab is an easy way to get one. vue-router
 * accepts a promise instead, so the guard can wait on a real dialog -- but only
 * if that promise is guaranteed to settle.
 *
 *   const gate = useConfirmGate()
 *   if (!(await gate.ask())) return        // caller
 *   <ConfirmDialog v-model="gate.open" :onConfirm="() => gate.answer(true)" />
 *
 * Two things this exists to get right:
 *
 * - `open` is writable, and setting it false answers "no". A dialog closes by
 *   routes that never touch a button -- Escape, a backdrop click -- and a
 *   promise nobody resolves would wedge the route guard permanently: every
 *   later navigation away from the page would hang with no dialog on screen to
 *   explain why. Any close that is not an explicit confirm is a no.
 * - A second `ask()` while one is open returns the same promise rather than
 *   opening a second dialog. One question gets one answer, and both callers
 *   hear it. (A modal blocks the clicks behind it, but not the back button.)
 */
export function useConfirmGate() {
  const shown = ref(false)
  let settle = null
  let pending = null

  function answer(confirmed) {
    const resolve = settle
    settle = null
    pending = null
    shown.value = false
    resolve?.(confirmed)
  }

  const open = computed({
    get: () => shown.value,
    set: (value) => (value ? (shown.value = true) : answer(false)),
  })

  function ask() {
    if (pending) return pending
    pending = new Promise((resolve) => (settle = resolve))
    shown.value = true
    return pending
  }

  return { open, ask, answer }
}
