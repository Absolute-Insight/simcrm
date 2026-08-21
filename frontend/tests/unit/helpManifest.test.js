/**
 * The help centre's manifest against the files on disk.
 *
 * The manifest and the markdown are two lists that have to agree, and nothing
 * in the running app says when they stop: an entry with no file renders a
 * blank article, and a file with no entry is unreachable except by guessing
 * the URL. Both are the kind of thing that survives review and is found by a
 * customer.
 */
import { describe, expect, it } from 'vitest'
import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import {
  FIRST_ARTICLE,
  HELP_ARTICLES,
  HELP_SECTIONS,
  findArticle,
  helpPanelArticles,
} from '../../src/help/manifest.js'

const CONTENT_DIR = path.resolve(
  path.dirname(fileURLToPath(import.meta.url)),
  '../../src/help/content',
)

const files = fs
  .readdirSync(CONTENT_DIR)
  .filter((name) => name.endsWith('.md'))
  .map((name) => name.replace(/\.md$/, ''))

function read(slug) {
  return fs.readFileSync(path.join(CONTENT_DIR, `${slug}.md`), 'utf8')
}

describe('help manifest', () => {
  it('has an article file for every entry', () => {
    const missing = HELP_ARTICLES.map((a) => a.slug).filter(
      (slug) => !files.includes(slug),
    )
    expect(missing).toEqual([])
  })

  it('has an entry for every article file', () => {
    const slugs = HELP_ARTICLES.map((a) => a.slug)
    expect(files.filter((slug) => !slugs.includes(slug))).toEqual([])
  })

  it('has no duplicate slugs', () => {
    const slugs = HELP_ARTICLES.map((a) => a.slug)
    expect(new Set(slugs).size).toBe(slugs.length)
  })

  it('gives every article a title and a summary', () => {
    for (const article of HELP_ARTICLES) {
      expect(article.title, article.slug).toBeTruthy()
      expect(article.summary, article.slug).toBeTruthy()
    }
  })

  it('uses url-safe slugs, because a slug is a route', () => {
    for (const article of HELP_ARTICLES) {
      expect(article.slug).toMatch(/^[a-z0-9-]+$/)
    }
  })

  it('resolves an article by slug and nothing by a bad one', () => {
    expect(findArticle(FIRST_ARTICLE.slug)?.title).toBe(FIRST_ARTICLE.title)
    expect(findArticle('no-such-article')).toBeNull()
  })

  it('lands /help on a real article', () => {
    expect(files).toContain(FIRST_ARTICLE.slug)
  })

  it('stamps each article with the section it belongs to', () => {
    for (const section of HELP_SECTIONS) {
      for (const article of section.articles) {
        expect(findArticle(article.slug).section).toBe(section.title)
      }
    }
  })
})

describe('help article content', () => {
  it('opens each article with a single H1', () => {
    for (const slug of files) {
      const h1s = read(slug)
        .split('\n')
        .filter((line) => line.startsWith('# '))
      expect(h1s.length, slug).toBe(1)
    }
  })

  it('only cross-links to articles that exist', () => {
    const slugs = HELP_ARTICLES.map((a) => a.slug)
    for (const slug of files) {
      for (const [, target] of read(slug).matchAll(
        /\]\(\/crm\/help\/([^)#]+)/g,
      )) {
        expect(slugs, `${slug} links to ${target}`).toContain(target)
      }
    }
  })

  it('sends nobody to another product for its documentation', () => {
    for (const slug of files) {
      expect(read(slug), slug).not.toContain('docs.frappe.io')
    }
  })
})

describe('helpPanelArticles', () => {
  it('shapes the manifest the way the help panel wants it', () => {
    const panel = helpPanelArticles()
    expect(panel).toHaveLength(HELP_SECTIONS.length)
    expect(panel[0]).toMatchObject({
      title: HELP_SECTIONS[0].title,
      opened: false,
    })
    expect(panel[0].subArticles[0]).toEqual({
      name: HELP_SECTIONS[0].articles[0].slug,
      title: HELP_SECTIONS[0].articles[0].title,
    })
  })

  it('translates every string it hands over', () => {
    const panel = helpPanelArticles((value) => `[${value}]`)
    expect(panel[0].title).toBe(`[${HELP_SECTIONS[0].title}]`)
    expect(panel[0].subArticles[0].title).toBe(
      `[${HELP_SECTIONS[0].articles[0].title}]`,
    )
  })

  it('leaves the slug alone, because it is a route and not prose', () => {
    const panel = helpPanelArticles((value) => `[${value}]`)
    expect(panel[0].subArticles[0].name).toBe(HELP_SECTIONS[0].articles[0].slug)
  })
})
