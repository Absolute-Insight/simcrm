import { describe, expect, it } from 'vitest'
import {
  groupArticles,
  renderArticleMarkdown,
  searchArticles,
  stripMarkdown,
} from '@/utils/helpCenter'

const ARTICLES = [
  {
    name: 'welcome',
    title: 'Welcome to Vectora',
    category: 'Getting started',
    order: 1,
    content: '# Welcome\n\nVectora is a **proactive** CRM.',
  },
  {
    name: 'planner',
    title: 'The weekly planner',
    category: 'Proactive selling',
    order: 3,
    content:
      'Plans resolve against real activity. A daily matcher links items.',
  },
  {
    name: 'deals',
    title: 'Deals and the pipeline',
    category: 'Working with records',
    order: 2,
    content: 'Expected closure date feeds the forecast and the planner signal.',
  },
]

const CATEGORIES = [
  'Getting started',
  'Working with records',
  'Proactive selling',
]

describe('groupArticles', () => {
  it('groups into the given category order', () => {
    const groups = groupArticles(ARTICLES, CATEGORIES)
    expect(groups.map((g) => g.category)).toEqual(CATEGORIES)
    expect(groups[0].articles.map((a) => a.name)).toEqual(['welcome'])
  })

  it('drops categories with no articles instead of rendering them empty', () => {
    const groups = groupArticles(
      [ARTICLES[0]],
      ['Getting started', 'Working with records'],
    )
    expect(groups.map((g) => g.category)).toEqual(['Getting started'])
  })

  it('tolerates missing inputs', () => {
    expect(groupArticles(undefined, undefined)).toEqual([])
    expect(groupArticles(ARTICLES, [])).toEqual([])
  })
})

describe('searchArticles', () => {
  it('returns nothing for a blank query', () => {
    expect(searchArticles(ARTICLES, '')).toEqual([])
    expect(searchArticles(ARTICLES, '   ')).toEqual([])
  })

  it('matches titles case-insensitively and ranks them first', () => {
    const hits = searchArticles(ARTICLES, 'PLANNER')
    expect(hits.map((h) => h.article.name)).toEqual(['planner', 'deals'])
    expect(hits[0].snippet).toBe('')
  })

  it('body hits carry a snippet around the match', () => {
    const hits = searchArticles(ARTICLES, 'daily matcher')
    expect(hits).toHaveLength(1)
    expect(hits[0].article.name).toBe('planner')
    expect(hits[0].snippet).toContain('daily matcher')
  })

  it('long bodies get an elided snippet, not the whole article', () => {
    const long = {
      name: 'long',
      title: 'Long',
      category: 'Getting started',
      content: 'x'.repeat(500) + ' needle in here ' + 'y'.repeat(500),
    }
    const [hit] = searchArticles([long], 'needle')
    expect(hit.snippet.startsWith('…')).toBe(true)
    expect(hit.snippet.endsWith('…')).toBe(true)
    expect(hit.snippet.length).toBeLessThan(200)
    expect(hit.snippet).toContain('needle')
  })

  it('finds prose that markdown syntax would otherwise hide', () => {
    const table = {
      name: 't',
      title: 'T',
      category: 'Getting started',
      content: '| **Idle deal** | No activity logged |\n|---|---|',
    }
    const [hit] = searchArticles([table], 'idle deal')
    expect(hit).toBeTruthy()
    expect(hit.snippet).not.toContain('**')
    expect(hit.snippet).not.toContain('|')
  })
})

describe('stripMarkdown', () => {
  it('removes headings, emphasis, code and link syntax but keeps the words', () => {
    const text = stripMarkdown(
      '# Title\n\nSee **Settings → [Brand](x)** and `code`.',
    )
    expect(text).toContain('Title')
    expect(text).toContain('Settings → Brand')
    expect(text).toContain('code')
    expect(text).not.toMatch(/[#*`[\]]/)
  })
})

describe('renderArticleMarkdown', () => {
  it('renders markdown to HTML', () => {
    const html = renderArticleMarkdown('# Hello\n\nSome **bold** text.')
    expect(html).toContain('<h1>')
    expect(html).toContain('<strong>bold</strong>')
  })

  it('renders GFM tables', () => {
    const html = renderArticleMarkdown('| a | b |\n|---|---|\n| 1 | 2 |')
    expect(html).toContain('<table>')
  })

  it('tolerates empty input', () => {
    expect(renderArticleMarkdown('')).toBe('')
    expect(renderArticleMarkdown(undefined)).toBe('')
  })
})
