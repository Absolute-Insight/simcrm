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
