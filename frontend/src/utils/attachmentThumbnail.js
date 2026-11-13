// The URL a small preview of an attachment should load.
//
// frappe keeps a reduced copy of an image in File.thumbnail_url when one has
// been made; the original is a phone photo of several megabytes, and the
// Attachments tab draws it 44px square. Only a file on this site is taken from
// that field -- anything else falls back to the file itself -- so a row whose
// thumbnail was pointed somewhere else cannot make every viewer's browser
// fetch it.
const SITE_FILE = /^\/(private\/)?files\/[^?#\\]+$/

// "/files/../api/method/x" matches the prefix and the browser then resolves it
// to any path on this origin, so a dot segment is refused outright.
const hasDotSegment = (path) =>
  path.split('/').some((part) => part === '..' || part === '.')

export function attachmentThumbnail(attachment) {
  const thumbnail = attachment?.thumbnail_url
  if (
    typeof thumbnail === 'string' &&
    SITE_FILE.test(thumbnail) &&
    !hasDotSegment(thumbnail)
  ) {
    return thumbnail
  }
  return attachment?.file_url
}
