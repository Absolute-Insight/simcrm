import { describe, expect, it } from 'vitest'

import { bytesToBase64, encodeWav } from '@/utils/wav'

function header(bytes) {
  const view = new DataView(bytes.buffer)
  const text = (o, n) => String.fromCharCode(...bytes.subarray(o, o + n))
  return {
    riff: text(0, 4),
    wave: text(8, 4),
    format: view.getUint16(20, true),
    channels: view.getUint16(22, true),
    rate: view.getUint32(24, true),
    bits: view.getUint16(34, true),
    data: text(36, 4),
    dataBytes: view.getUint32(40, true),
  }
}

describe('encodeWav', () => {
  it('writes the exact shape the server accepts: 16 kHz mono PCM16', () => {
    const wav = encodeWav(new Float32Array(16000))
    expect(header(wav)).toEqual({
      riff: 'RIFF',
      wave: 'WAVE',
      format: 1,
      channels: 1,
      rate: 16000,
      bits: 16,
      data: 'data',
      dataBytes: 32000,
    })
    expect(wav.length).toBe(44 + 32000)
  })

  it('clips samples outside [-1, 1] instead of wrapping them', () => {
    const wav = encodeWav(new Float32Array([2, -2, 0.5]))
    const view = new DataView(wav.buffer)
    expect(view.getInt16(44, true)).toBe(32767)
    expect(view.getInt16(46, true)).toBe(-32768)
    expect(view.getInt16(48, true)).toBe(Math.trunc(0.5 * 0x7fff))
  })
})

describe('bytesToBase64', () => {
  it('encodes large arrays without overflowing the call stack', () => {
    const bytes = new Uint8Array(1_000_000).fill(65)
    const encoded = bytesToBase64(bytes)
    expect(encoded.length).toBe(Math.ceil(1_000_000 / 3) * 4)
    expect(atob(encoded.slice(0, 8))).toBe('AAAAAA')
  })
})
