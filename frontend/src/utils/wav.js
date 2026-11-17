/**
 * Turn a browser recording into the one audio shape the server accepts:
 * 16 kHz, mono, 16-bit PCM WAV (see crm/agent/media.py).
 *
 * The browser does the decoding and resampling so the server never has to run
 * a codec on a stranger's bytes. MediaRecorder hands back Opus in WebM (Chrome,
 * Firefox) or AAC in MP4 (Safari); `decodeAudioData` reads either, and an
 * OfflineAudioContext at 16 kHz does the resample and the downmix in one pass.
 *
 * `encodeWav` and `bytesToBase64` are pure and unit-tested; `recordingToWav` needs a
 * real AudioContext and is exercised in the browser.
 */

export const CLIP_SAMPLE_RATE = 16000

/**
 * Mono float samples in [-1, 1] → a PCM16 WAV file.
 * @param {Float32Array} samples
 * @param {number} sampleRate
 * @returns {Uint8Array}
 */
export function encodeWav(samples, sampleRate = CLIP_SAMPLE_RATE) {
  const dataBytes = samples.length * 2
  const buffer = new ArrayBuffer(44 + dataBytes)
  const view = new DataView(buffer)
  const ascii = (offset, text) => {
    for (let i = 0; i < text.length; i++)
      view.setUint8(offset + i, text.charCodeAt(i))
  }
  ascii(0, 'RIFF')
  view.setUint32(4, 36 + dataBytes, true)
  ascii(8, 'WAVE')
  ascii(12, 'fmt ')
  view.setUint32(16, 16, true) // fmt chunk size
  view.setUint16(20, 1, true) // PCM
  view.setUint16(22, 1, true) // mono
  view.setUint32(24, sampleRate, true)
  view.setUint32(28, sampleRate * 2, true) // byte rate
  view.setUint16(32, 2, true) // block align
  view.setUint16(34, 16, true) // bits per sample
  ascii(36, 'data')
  view.setUint32(40, dataBytes, true)
  for (let i = 0; i < samples.length; i++) {
    const s = Math.max(-1, Math.min(1, samples[i]))
    view.setInt16(44 + i * 2, s < 0 ? s * 0x8000 : s * 0x7fff, true)
  }
  return new Uint8Array(buffer)
}

/**
 * Bytes → base64, in chunks: spreading a 1 MB array into one
 * String.fromCharCode call overflows the argument limit.
 * @param {Uint8Array} bytes
 */
export function bytesToBase64(bytes) {
  let binary = ''
  const step = 0x8000
  for (let i = 0; i < bytes.length; i += step) {
    binary += String.fromCharCode.apply(null, bytes.subarray(i, i + step))
  }
  return btoa(binary)
}

/**
 * A MediaRecorder blob → 16 kHz mono WAV bytes, cut to `maxSeconds`.
 * @param {Blob} blob
 * @param {number} maxSeconds
 * @returns {Promise<{wav: Uint8Array, seconds: number}>}
 */
export async function recordingToWav(blob, maxSeconds) {
  const AudioCtx = window.AudioContext || window.webkitAudioContext
  const context = new AudioCtx()
  let decoded
  try {
    decoded = await context.decodeAudioData(await blob.arrayBuffer())
  } finally {
    context.close?.()
  }
  const seconds = Math.min(decoded.duration, maxSeconds)
  const length = Math.max(1, Math.round(seconds * CLIP_SAMPLE_RATE))
  const offline = new OfflineAudioContext(1, length, CLIP_SAMPLE_RATE)
  const source = offline.createBufferSource()
  source.buffer = decoded
  source.connect(offline.destination)
  source.start()
  const rendered = await offline.startRendering()
  return {
    wav: encodeWav(rendered.getChannelData(0), CLIP_SAMPLE_RATE),
    seconds,
  }
}
