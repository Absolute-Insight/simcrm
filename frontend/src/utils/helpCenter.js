/**
 * Pure logic for the in-app help center: grouping, search and rendering.
 *
 * Articles come from `crm.api.help.get_articles` as
 * `{ name, title, category, order, content }` with `categories` carrying the
 * display order.
 */
import { marked } from 'marked'

/**
 * Articles grouped into their categories, in the server's category order.
 * Categories with no articles are dropped rather than rendered empty.
 */
export function groupArticles(articles, categories) {
  return (categories || [])
    .map((category) => ({
      category,
      articles: (articles || []).filter((a) => a.category === category),
    }))
    .filter((group) => group.articles.length)
}

/** How much context a search snippet shows around the first hit. */
export const SNIPPET_RADIUS = 60

/**
 * Case-insensitive search over titles and bodies.
 *
 * Title hits rank before body hits; within a band the catalogue order is
 * kept, which is the help center's own display order. Body hits carry a
 * plain-text snippet around the first occurrence so the result list can show
 * why it matched.
 */
export function searchArticles(articles, query) {
  const needle = (query || '').trim().toLowerCase()
  if (!needle) return []

  const titleHits = []
  const bodyHits = []
  for (const article of articles || []) {
    if ((article.title || '').toLowerCase().includes(needle)) {
      titleHits.push({ article, snippet: '' })
      continue
    }
    const haystack = stripMarkdown(article.content || '')
    const at = haystack.toLowerCase().indexOf(needle)
    if (at >= 0) {
      bodyHits.push({
        article,
        snippet: makeSnippet(haystack, at, needle.length),
      })
    }
  }
  return [...titleHits, ...bodyHits]
}

function makeSnippet(text, at, matchLength) {
  const start = Math.max(0, at - SNIPPET_RADIUS)
  const end = Math.min(text.length, at + matchLength + SNIPPET_RADIUS)
  const prefix = start > 0 ? '…' : ''
  const suffix = end < text.length ? '…' : ''
  return prefix + text.slice(start, end).trim() + suffix
}

/**
 * Markdown syntax out, prose kept — for snippets, where `**bold**` markers
 * and table pipes are noise around the matched words.
 */
export function stripMarkdown(markdown) {
  return (markdown || '')
    .replace(/^#{1,6}\s+/gm, '')
    .replace(/\*\*([^*]+)\*\*/g, '$1')
    .replace(/\*([^*]+)\*/g, '$1')
    .replace(/`([^`]+)`/g, '$1')
    .replace(/\[([^\]]+)\]\([^)]*\)/g, '$1')
    .replace(/^\s*\|.*\|\s*$/gm, (row) =>
      row
        .split('|')
        .map((cell) => cell.trim())
        .filter(Boolean)
        .join(' · '),
    )
    .replace(/^\s*[-|:\s·]+$/gm, '')
    .replace(/^\s*[-*]\s+/gm, '')
    .replace(/\n{2,}/g, '\n')
    .trim()
}

/**
 * Markdown to HTML — UNSANITIZED. The rendering component must pass this
 * through `sanitizeHTML` from `@/utils` before `v-html`, the same rule every
 * other HTML path in the app follows. Sanitization lives at the component
 * rather than here because DOMPurify does not work under happy-dom (it keeps
 * `<script>` and strips structural tags there), so a util that sanitized
 * internally would be untestable exactly where its output shape matters.
 */
export function renderArticleMarkdown(markdown) {
  return marked.parse(markdown || '', { async: false, gfm: true })
}
