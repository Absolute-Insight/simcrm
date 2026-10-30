import { nextTick } from 'vue'

/**
 * Let every pending promise and the re-render each one queues settle: a
 * resource's onSuccess runs a few microtasks after its fetch resolves, and the
 * DOM catches up a tick after that.
 */
export async function flushPromises(rounds = 10) {
  for (let i = 0; i < rounds; i++) {
    await new Promise((resolve) => setTimeout(resolve, 0))
    await nextTick()
  }
}

/**
 * Run `action` and collect the promise rejections nobody handled while it
 * settled. frappe-ui's resources re-throw a failure after calling onError, so
 * a refused submit always leaves its own error behind; what a test cares about
 * is that nothing *else* -- an onError that threw -- joined it.
 */
export async function collectRejections(action) {
  const reasons = []
  const listener = (reason) => reasons.push(reason)
  process.on('unhandledRejection', listener)
  try {
    await action()
    await flushPromises()
  } finally {
    process.off('unhandledRejection', listener)
  }
  return reasons
}
