/**
 * Run `attempt` again after each delay in `delays` while it keeps failing.
 *
 * Pure apart from the timer, which is injectable, so the router's first-load
 * retry can be tested without a router or a network.
 *
 * @param {() => Promise<unknown>} attempt Called once, then once per delay.
 * @param {object} [options]
 * @param {number[]} [options.delays] Milliseconds to wait before each retry.
 * @param {(error: unknown) => boolean} [options.shouldRetry] False rethrows at
 *   once -- for an error a retry cannot fix, such as a PermissionError.
 * @param {(ms: number) => Promise<void>} [options.wait]
 * @returns {Promise<unknown>} The first success; rejects with the last error.
 */
export async function retryWithBackoff(
  attempt,
  {
    delays = [],
    shouldRetry = () => true,
    wait = (ms) => new Promise((resolve) => setTimeout(resolve, ms)),
  } = {},
) {
  for (let i = 0; ; i++) {
    try {
      return await attempt()
    } catch (error) {
      if (i >= delays.length || !shouldRetry(error)) throw error
      await wait(delays[i])
    }
  }
}
