/** Enter on an empty or blank composer sends nothing: Meta refuses an empty body. */
export function canSendMessage(content) {
  return Boolean(content?.trim())
}
