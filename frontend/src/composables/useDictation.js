/**
 * Dictation for a chat input: record from the microphone, convert in the
 * browser, send to `crm.agent.api.transcribe`, hand back the text.
 *
 * The text goes into the draft, never straight to a model: the rep sees what
 * was heard and fixes a mis-heard "PN16" before sending. Recording stops on
 * its own at the server's clip limit, so a forgotten microphone does not run
 * for minutes and then get refused.
 *
 * state: 'idle' | 'starting' | 'recording' | 'transcribing'
 * error: '' | 'unsupported' | 'denied' | 'nothing' | 'failed' | 'unavailable'
 */
import { call } from 'frappe-ui'
import { onBeforeUnmount, ref } from 'vue'

import { describeError } from '@/utils/describeError'
import { bytesToBase64, recordingToWav } from '@/utils/wav'

export const MAX_CLIP_SECONDS = 30
const MIN_CLIP_SECONDS = 0.5

export function dictationSupported() {
  return (
    typeof window !== 'undefined' &&
    window.isSecureContext !== false &&
    !!navigator.mediaDevices?.getUserMedia &&
    typeof window.MediaRecorder === 'function' &&
    typeof window.OfflineAudioContext === 'function'
  )
}

/**
 * @param {object} options
 * @param {(text: string) => void} options.onText  called with the transcript
 * @param {number} [options.maxSeconds]
 */
export function useDictation({ onText, maxSeconds = MAX_CLIP_SECONDS }) {
  const state = ref('idle')
  const error = ref('')
  /** server-written message for a refused clip, shown as-is (plain text) */
  const errorMessage = ref('')
  const elapsed = ref(0)

  let recorder = null
  let stream = null
  let chunks = []
  let ticker = null
  let startedAt = 0
  let cancelled = false
  let unmounted = false

  function release() {
    clearInterval(ticker)
    ticker = null
    stream?.getTracks().forEach((track) => track.stop())
    stream = null
  }

  async function start() {
    if (state.value !== 'idle') return
    error.value = ''
    errorMessage.value = ''
    if (!dictationSupported()) {
      error.value = 'unsupported'
      return
    }
    // 'starting' while the browser asks for the microphone: a second click
    // must not open a second stream, and an unmount during the wait must not
    // leave a live one behind
    state.value = 'starting'
    unmounted = false
    let opened
    try {
      opened = await navigator.mediaDevices.getUserMedia({
        audio: {
          channelCount: 1,
          echoCancellation: true,
          noiseSuppression: true,
        },
      })
    } catch (e) {
      state.value = 'idle'
      error.value =
        e?.name === 'NotAllowedError' || e?.name === 'SecurityError'
          ? 'denied'
          : 'unsupported'
      return
    }
    if (unmounted) {
      opened.getTracks().forEach((track) => track.stop())
      return
    }
    stream = opened
    chunks = []
    cancelled = false
    try {
      recorder = new MediaRecorder(stream)
    } catch {
      recorder = null
      release()
      state.value = 'idle'
      error.value = 'unsupported'
      return
    }
    recorder.ondataavailable = (event) => {
      if (event.data?.size) chunks.push(event.data)
    }
    recorder.onstop = finish
    recorder.start()
    startedAt = performance.now()
    elapsed.value = 0
    state.value = 'recording'
    ticker = setInterval(() => {
      elapsed.value = (performance.now() - startedAt) / 1000
      if (elapsed.value >= maxSeconds) stop()
    }, 200)
  }

  function stop() {
    if (state.value !== 'recording' || !recorder) return
    clearInterval(ticker)
    ticker = null
    if (recorder.state !== 'inactive') recorder.stop()
  }

  /** Stop and throw the recording away. */
  function cancel() {
    if (state.value !== 'recording') return
    cancelled = true
    stop()
  }

  async function finish() {
    const type = recorder?.mimeType || chunks[0]?.type || ''
    recorder = null
    release()
    if (cancelled) {
      state.value = 'idle'
      return
    }
    const blob = new Blob(chunks, { type })
    chunks = []
    if (!blob.size || elapsed.value < MIN_CLIP_SECONDS) {
      state.value = 'idle'
      error.value = 'nothing'
      return
    }
    state.value = 'transcribing'
    try {
      const { wav } = await recordingToWav(blob, maxSeconds)
      const result = await call('crm.agent.api.transcribe', {
        audio: bytesToBase64(wav),
      })
      if (result?.status === 'ok') {
        if (result.text?.trim()) onText(result.text.trim())
        else error.value = 'nothing'
      } else {
        error.value = 'unavailable'
      }
    } catch (e) {
      const described = describeError(e)
      error.value = 'failed'
      errorMessage.value = described.message || ''
    } finally {
      state.value = 'idle'
    }
  }

  onBeforeUnmount(() => {
    unmounted = true
    cancelled = true
    if (recorder && recorder.state !== 'inactive') recorder.stop()
    release()
  })

  return { state, error, errorMessage, elapsed, start, stop, cancel }
}
