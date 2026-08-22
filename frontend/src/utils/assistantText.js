/**
 * Model answers are displayed as plain text — never HTML — by the standing
 * rule that model output is untrusted input. Small models still emit
 * markdown emphasis and headings no matter what the prompt says, and
 * `- **Idle**: …` read literally looks like a rendering bug. This strips the
 * decoration and keeps the words; bullets stay, they read fine as text.
 */
export function plainTextAnswer(text) {
  return String(text || '')
    .replace(/^#{1,6}\s+/gm, '')
    .replace(/\*\*([^*\n]+)\*\*/g, '$1')
    .replace(/__([^_\n]+)__/g, '$1')
    .replace(/(^|[\s(])\*([^*\n]+)\*(?=[\s).,;:!?]|$)/g, '$1$2')
    .replace(/`([^`\n]+)`/g, '$1')
    .replace(/\n{3,}/g, '\n\n')
    .trim()
}
