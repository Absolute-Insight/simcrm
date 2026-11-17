/**
 * Record a voice note for a field-mode note: the microphone, as the browser's
 * own compressed audio, kept as a Blob. Unlike dictation (useDictation) it is
 * never transcribed or sent anywhere while recording -- it goes with the note,
 * through the outbox, so it works with no signal at all.
 *
 * state: 'idle' | 'starting' | 'recording'
 * error: '' | 'unsupported' | 'denied' | 'nothing' | 'large'
 */
import { onBeforeUnmount, ref } from 'vue'

import { MAX_VOICE_BYTES, MAX_VOICE_SECONDS } from '@/utils/noteMedia'

const MIN_SECONDS = 1
/* Opus in WebM where the browser has it (Chrome, Android); AAC in MP4 on
   iOS Safari. Either is a few hundred KB a minute. */
const TYPES = ['audio/webm;codecs=opus', 'audio/webm', 'audio/mp4', 'audio/ogg']

export function voiceNotesSupported() {
  return (
    typeof window !== 'undefined' &&
    window.isSecureContext !== false &&
    !!navigator.mediaDevices?.getUserMedia &&
    typeof window.MediaRecorder === 'function'
  )
}

function preferredType() {
  const can = window.MediaRecorder?.isTypeSupported
  return TYPES.find((type) =>
    can ? can.call(window.MediaRecorder, type) : false,
  )
}

/**
 * @param {object} options
 * @param {(recording: {blob: Blob, seconds: number}) => void} options.onRecorded
 */
export function useVoiceNote({ onRecorded, maxSeconds = MAX_VOICE_SECONDS }) {
  const state = ref('idle')
  const error = ref('')
  const elapsed = ref(0)

  let recorder = null
  let stream = null
  let chunks = []
  let ticker = null
  let startedAt = 0
  let discard = false
  let gone = false

  function release() {
    clearInterval(ticker)
    ticker = null
    stream?.getTracks().forEach((track) => track.stop())
    stream = null
  }

  async function start() {
    if (state.value !== 'idle') return
    error.value = ''
    if (!voiceNotesSupported()) {
      error.value = 'unsupported'
      return
    }
    state.value = 'starting'
    gone = false
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
    if (gone) {
      opened.getTracks().forEach((track) => track.stop())
      return
    }
    stream = opened
    chunks = []
    discard = false
    try {
      const mimeType = preferredType()
      recorder = new MediaRecorder(stream, {
        ...(mimeType ? { mimeType } : {}),
        audioBitsPerSecond: 32000,
      })
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
    recorder.start(1000)
    startedAt = performance.now()
    elapsed.value = 0
    state.value = 'recording'
    ticker = setInterval(() => {
      elapsed.value = (performance.now() - startedAt) / 1000
      if (elapsed.value >= maxSeconds) stop()
    }, 250)
  }

  function stop() {
    if (state.value !== 'recording' || !recorder) return
    clearInterval(ticker)
    ticker = null
    if (recorder.state !== 'inactive') recorder.stop()
  }

  function cancel() {
    if (state.value !== 'recording') return
    discard = true
    stop()
  }

  function finish() {
    const type = recorder?.mimeType || chunks[0]?.type || 'audio/webm'
    recorder = null
    release()
    state.value = 'idle'
    if (discard || gone) return
    const blob = new Blob(chunks, { type })
    chunks = []
    if (!blob.size || elapsed.value < MIN_SECONDS) {
      error.value = 'nothing'
      return
    }
    if (blob.size > MAX_VOICE_BYTES) {
      error.value = 'large'
      return
    }
    onRecorded({ blob, seconds: Math.min(elapsed.value, maxSeconds) })
  }

  onBeforeUnmount(() => {
    gone = true
    discard = true
    if (recorder && recorder.state !== 'inactive') recorder.stop()
    release()
  })

  return { state, error, elapsed, start, stop, cancel }
}
