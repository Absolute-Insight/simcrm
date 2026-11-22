/** How many records a link picker lists before it asks the user to type. */
export const LINK_PAGE_LENGTH = 50

function stripHtml(html) {
  if (!html) return ''
  return html
    .replace(/<[^>]*>/g, ' ')
    .replace(/&nbsp;/g, ' ')
    .replace(/\s+/g, ' ')
    .trim()
}

/**
 * A record with a title shows the title as its label, and the server then
 * leads the description with the record's id. Under a title that id is noise,
 * and on a renamed record it is the old name the title replaced.
 */
function describe(option, label) {
  const parts = stripHtml(option.description)
    .split(/\s*,\s*/)
    .filter((part) => part && part !== option.value && part !== label)
  return parts.join(', ')
}

/**
 * The rows `search_link` returned, as picker options. The picker asks for one
 * row more than it lists, so `more` is exact: true only when a row was left out.
 */
export function linkOptions(rows, pageLength = LINK_PAGE_LENGTH) {
  const list = rows || []
  const options = list.slice(0, pageLength).map((option) => {
    const label = option.label || option.value
    return { label, value: option.value, description: describe(option, label) }
  })
  return { options, more: list.length > pageLength }
}
