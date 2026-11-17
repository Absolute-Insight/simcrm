/**
 * Photos and voice notes on a field-mode note: the limits, and what the phone
 * does to a photo before keeping it. The server checks every limit again
 * (crm/api/note_media.py); these are so a rep is told at the client, not later.
 */

/* MAX_PHOTOS / MAX_RECORDINGS in crm/api/note_media.py */
export const MAX_PHOTOS = 4
export const MAX_RECORDINGS = 1
export const MAX_VOICE_SECONDS = 180
/* MAX_PHOTO_BYTES / MAX_VOICE_BYTES there */
export const MAX_PHOTO_BYTES = 2 * 1024 * 1024
export const MAX_VOICE_BYTES = 4 * 1024 * 1024
/* A camera photo is 4000 px and several MB; a note needs to show a nameplate
   or a drawing legibly, and to get through a weak signal. */
export const PHOTO_EDGE = 1600
const PHOTO_QUALITY = 0.82

/** The size to draw an image at so its longer edge is at most `edge`. */
export function fitWithin(width, height, edge = PHOTO_EDGE) {
  const longer = Math.max(width, height)
  if (!longer || longer <= edge) return { width, height }
  const scale = edge / longer
  return {
    width: Math.max(1, Math.round(width * scale)),
    height: Math.max(1, Math.round(height * scale)),
  }
}

/**
 * A photo the rep picked, as a JPEG no larger than it needs to be.
 * createImageBitmap honours the photo's EXIF orientation, so a portrait shot
 * is kept upright.
 */
export async function scalePhoto(file) {
  const bitmap = await createImageBitmap(file, {
    imageOrientation: 'from-image',
  })
  try {
    const { width, height } = fitWithin(bitmap.width, bitmap.height)
    const canvas = document.createElement('canvas')
    canvas.width = width
    canvas.height = height
    canvas.getContext('2d').drawImage(bitmap, 0, 0, width, height)
    const blob = await new Promise((resolve) =>
      canvas.toBlob(resolve, 'image/jpeg', PHOTO_QUALITY),
    )
    if (!blob) throw new Error(__('That photo could not be read.'))
    if (blob.size > MAX_PHOTO_BYTES) {
      throw new Error(__('That photo is too large.'))
    }
    return blob
  } finally {
    bitmap.close?.()
  }
}

/** A Blob as plain base64, for a JSON request. */
export function blobToBase64(blob) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader()
    reader.onload = () => resolve(String(reader.result).split(',', 2)[1] || '')
    reader.onerror = () => reject(reader.error)
    reader.readAsDataURL(blob)
  })
}

/** "1:05" */
export function clock(seconds) {
  const whole = Math.max(0, Math.floor(seconds))
  return `${Math.floor(whole / 60)}:${String(whole % 60).padStart(2, '0')}`
}

/** The kind of a file the server listed, by extension. */
export function mediaKind(url) {
  const ext = String(url || '')
    .toLowerCase()
    .split('?')[0]
    .split('.')
    .pop()
  if (['jpg', 'jpeg', 'png', 'webp'].includes(ext)) return 'photo'
  if (['webm', 'ogg', 'm4a', 'wav', 'mp4'].includes(ext)) return 'voice'
  return null
}
