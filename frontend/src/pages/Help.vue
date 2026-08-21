<template>
  <LayoutHeader>
    <template #left-header>
      <div
        class="font-display text-lg font-medium tracking-tight text-ink-gray-7 px-0.5 py-1"
      >
        {{ __('Help centre') }}
      </div>
    </template>
  </LayoutHeader>

  <div class="flex flex-1 overflow-hidden">
    <!-- Same rail idiom as Reports: a vertical list on a desktop, and on a
         phone a collapsed picker above the article, because 224px of rail out
         of a 375px viewport leaves nothing to read. -->
    <nav
      class="hidden w-64 shrink-0 flex-col border-r sm:flex print:hidden"
      :aria-label="__('Help articles')"
    >
      <div class="p-2">
        <FormControl
          v-model="search"
          type="text"
          :placeholder="__('Search help')"
        >
          <template #prefix>
            <LucideSearch class="size-4 text-ink-gray-5" />
          </template>
        </FormControl>
      </div>

      <div class="flex flex-col gap-3 overflow-y-auto p-2 pt-0">
        <div
          v-for="section in visibleSections"
          :key="section.title"
          class="flex flex-col gap-0.5"
        >
          <div
            class="px-2 py-1 text-p-xs uppercase tracking-wide text-ink-gray-5"
          >
            {{ __(section.title) }}
          </div>
          <button
            v-for="article in section.articles"
            :key="article.slug"
            class="v-rail rounded px-2 py-1.5 text-left text-base text-ink-gray-8 hover:bg-surface-gray-2"
            :data-state="article.slug === slug ? 'active' : undefined"
            :class="
              article.slug === slug ? 'bg-surface-gray-2 font-medium' : ''
            "
            @click="open(article.slug)"
          >
            {{ __(article.title) }}
          </button>
        </div>

        <p
          v-if="!visibleSections.length"
          class="px-2 py-4 text-base text-ink-gray-5"
        >
          {{ __('No article matches “{0}”.', [search]) }}
        </p>
      </div>
    </nav>

    <div class="flex flex-1 flex-col overflow-y-auto">
      <!-- The phone picker. Sections are flattened into optgroups so the
           grouping survives without the rail. -->
      <div class="border-b p-3 sm:hidden">
        <select
          v-model="mobileSlug"
          class="w-full rounded border border-outline-gray-2 bg-surface-white px-2 py-1.5 text-base text-ink-gray-8"
          :aria-label="__('Help articles')"
        >
          <optgroup
            v-for="section in HELP_SECTIONS"
            :key="section.title"
            :label="__(section.title)"
          >
            <option
              v-for="article in section.articles"
              :key="article.slug"
              :value="article.slug"
            >
              {{ __(article.title) }}
            </option>
          </optgroup>
        </select>
      </div>

      <ErrorState
        v-if="!article"
        :title="__('No such help article')"
        :description="
          __('The link may be out of date. Pick an article from the list.')
        "
      />
      <article
        v-else
        ref="body"
        class="help-article mx-auto w-full max-w-3xl px-6 py-8"
        @click="onBodyClick"
        v-html="html"
      />
    </div>
  </div>
</template>

<script setup>
/**
 * The Vectora help centre, served by Vectora.
 *
 * It replaces thirty-four links to docs.frappe.io: another product's
 * documentation, on another product's domain, describing features this one
 * renamed and missing every feature it added. Articles are markdown bundled
 * into this route's chunk, so a pilot on a private network -- or an
 * air-gapped one -- has the whole manual, and nothing here can rot
 * independently of the build it ships with.
 *
 * The route is lazy, which is what keeps `marked` out of the main bundle: it
 * loads the first time somebody opens help and never on a cold app start.
 */
import { computed, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { FormControl, usePageMeta } from 'frappe-ui'
import { marked } from 'marked'
import DOMPurify from 'dompurify'
import LayoutHeader from '@/components/LayoutHeader.vue'
import ErrorState from '@/components/ui/ErrorState.vue'
import { FIRST_ARTICLE, HELP_SECTIONS, findArticle } from '@/help/manifest'

/* Eager rather than lazy: the whole help centre is about 40KB of text, and an
   article that arrives a frame after the page did is a worse read than one
   that is simply there. */
const SOURCES = import.meta.glob('@/help/content/*.md', {
  query: '?raw',
  import: 'default',
  eager: true,
})

function sourceFor(slug) {
  const key = Object.keys(SOURCES).find((path) => path.endsWith(`/${slug}.md`))
  return key ? SOURCES[key] : ''
}

const route = useRoute()
const router = useRouter()
const search = ref('')

const slug = computed(() => route.params.slug || FIRST_ARTICLE.slug)
const article = computed(() => findArticle(slug.value))

const html = computed(() => {
  const source = sourceFor(slug.value)
  if (!source) return ''
  /* The markdown is ours and ships in the bundle, so this is not a trust
     boundary -- it is a guard against one of these files ever being generated
     from something that is. Cheap, and it cannot be added back later by
     someone who does not know it was skipped. */
  return DOMPurify.sanitize(marked.parse(source, { async: false }))
})

const visibleSections = computed(() => {
  const needle = search.value.trim().toLowerCase()
  if (!needle) return HELP_SECTIONS
  return HELP_SECTIONS.map((section) => ({
    title: section.title,
    articles: section.articles.filter((a) => matches(a, needle)),
  })).filter((section) => section.articles.length)
})

/* Body text is searched, not just titles: somebody looking for "SLA" should
   find the article that explains it even though the word is not in its
   name. */
function matches(article, needle) {
  return (
    article.title.toLowerCase().includes(needle) ||
    article.summary.toLowerCase().includes(needle) ||
    sourceFor(article.slug).toLowerCase().includes(needle)
  )
}

function open(next) {
  if (next !== slug.value) router.push({ name: 'Help', params: { slug: next } })
}

const mobileSlug = computed({
  get: () => slug.value,
  set: open,
})

/* Cross-links between articles are plain markdown links, so they arrive as
   real anchors. Left alone each one is a full page reload of the SPA. */
function onBodyClick(event) {
  const anchor = event.target.closest?.('a')
  if (!anchor || event.metaKey || event.ctrlKey || event.shiftKey) return
  const href = anchor.getAttribute('href') || ''
  if (!href.startsWith('/crm/help/')) return
  event.preventDefault()
  open(href.slice('/crm/help/'.length))
}

const body = ref(null)
watch(slug, () => {
  search.value = ''
  body.value?.parentElement?.scrollTo?.({ top: 0 })
})

usePageMeta(() => ({
  title: article.value ? __(article.value.title) : __('Help centre'),
}))
</script>
