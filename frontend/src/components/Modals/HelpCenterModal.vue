<template>
  <Dialog v-model:open="helpCenterVisible" bare :size="'5xl'">
    <template #default>
      <div class="flex h-[calc(100vh_-_8rem)] bg-surface-gray-1">
        <div
          class="m-1 flex w-64 shrink-0 flex-col rounded-l-6 bg-surface-gray-1"
        >
          <div class="v-title-sm px-3 pb-2 pt-[15px] text-ink-gray-8">
            {{ __('Help center') }}
          </div>
          <div class="px-2 pb-2">
            <!-- No debounce, deliberately: the search is client-side over a
                 dozen small articles, and a debounced emit races the click on
                 a result — the blur's delayed emit lands after openResult()
                 clears the box and puts the stale query back. -->
            <TextInput
              v-model="search"
              type="text"
              :placeholder="__('Search the manual')"
            >
              <template #prefix>
                <LucideSearch class="size-4 text-ink-gray-5" />
              </template>
            </TextInput>
          </div>

          <div class="flex-1 overflow-y-auto px-1 pb-2">
            <!-- Search results replace the tree: one list, ranked, with the
                 matched context — not a tree with most branches greyed out. -->
            <template v-if="search.trim()">
              <div
                v-if="!results.length"
                class="px-2 py-3 text-sm text-ink-gray-5"
              >
                {{ __('Nothing matches "{0}"', [search.trim()]) }}
              </div>
              <button
                v-for="hit in results"
                :key="hit.article.name"
                type="button"
                class="flex w-full flex-col gap-0.5 rounded px-2 py-1.5 text-left transition hover:bg-surface-gray-3"
                @click="openResult(hit.article.name)"
              >
                <span class="text-base text-ink-gray-8">
                  {{ hit.article.title }}
                </span>
                <span
                  v-if="hit.snippet"
                  class="line-clamp-2 text-sm text-ink-gray-5"
                >
                  {{ hit.snippet }}
                </span>
              </button>
            </template>

            <template v-else>
              <div v-for="group in groups" :key="group.category" class="mb-1">
                <div
                  class="h-7.5 px-2 py-[7px] my-[3px] text-xs-medium text-ink-gray-5"
                >
                  {{ __(group.category) }}
                </div>
                <nav class="space-y-[3px]">
                  <SidebarItem
                    v-for="article in group.articles"
                    :key="article.name"
                    :label="article.title"
                    :active="article.name === shownArticle?.name"
                    class="w-full"
                    :class="
                      article.name !== shownArticle?.name &&
                      'hover:!bg-surface-gray-3'
                    "
                    @click="activeHelpArticle = article.name"
                  />
                </nav>
              </div>
            </template>
          </div>
        </div>

        <div
          class="flex flex-1 flex-col overflow-y-auto bg-surface-elevation-2"
        >
          <div v-if="helpContent.loading" class="flex flex-col gap-3 p-8">
            <Skeleton class="h-7 w-64" />
            <Skeleton class="h-4 w-full" />
            <Skeleton class="h-4 w-5/6" />
            <Skeleton class="h-4 w-4/6" />
          </div>
          <ErrorState
            v-else-if="helpContent.error"
            :error="helpContent.error"
            :retry="() => helpContent.reload()"
          />
          <article
            v-else-if="shownArticle"
            class="help-article mx-auto w-full max-w-3xl p-8"
          >
            <div class="mb-1 text-sm text-ink-gray-5">
              {{ __(shownArticle.category) }}
            </div>
            <h1 class="font-display text-2xl-semibold text-ink-gray-9">
              {{ shownArticle.title }}
            </h1>
            <!-- The markdown ships with the app, but it still goes through
                 sanitizeHTML like every other v-html in the codebase. -->
            <!-- eslint-disable-next-line vue/no-v-html -->
            <div class="mt-4" v-html="shownArticleHtml" />
          </article>
        </div>
      </div>
    </template>
  </Dialog>
</template>

<script setup>
import { PhMagnifyingGlass as LucideSearch } from '@phosphor-icons/vue'
import ErrorState from '@/components/ui/ErrorState.vue'
import Skeleton from '@/components/ui/Skeleton.vue'
import {
  activeHelpArticle,
  helpCenterVisible,
  helpContent,
} from '@/stores/help'
import { sanitizeHTML } from '@/utils'
import {
  groupArticles,
  renderArticleMarkdown,
  searchArticles,
} from '@/utils/helpCenter'
import { Dialog, SidebarItem, TextInput } from 'frappe-ui'
import { computed, ref, watch } from 'vue'

const search = ref('')

const articles = computed(() => helpContent.data?.articles || [])
const groups = computed(() =>
  groupArticles(articles.value, helpContent.data?.categories || []),
)
const results = computed(() => searchArticles(articles.value, search.value))

/* The landing view is the first article (the welcome page), so opening the
   help center never shows an empty pane while still deep-linking cleanly when
   the assistant hands over a specific article name. */
const shownArticle = computed(
  () =>
    articles.value.find((a) => a.name === activeHelpArticle.value) ||
    articles.value[0] ||
    null,
)

const shownArticleHtml = computed(() =>
  sanitizeHTML(renderArticleMarkdown(shownArticle.value?.content || '')),
)

function openResult(name) {
  activeHelpArticle.value = name
  search.value = ''
}

// A fresh open should read as a fresh open, not resume a stale search.
watch(helpCenterVisible, (open) => {
  if (open) search.value = ''
})
</script>

<style scoped>
/* Article typography. Scoped styles do not reach v-html children, hence :deep.
   Tokens only, so both themes hold. */
.help-article :deep(h2) {
  margin-top: 1.5rem;
  margin-bottom: 0.5rem;
  font-size: 1.125rem;
  font-weight: 600;
  color: var(--ink-gray-9);
}

.help-article :deep(h3) {
  margin-top: 1.25rem;
  margin-bottom: 0.375rem;
  font-size: 1rem;
  font-weight: 600;
  color: var(--ink-gray-8);
}

.help-article :deep(p) {
  margin-bottom: 0.75rem;
  font-size: 0.9375rem;
  line-height: 1.65;
  color: var(--ink-gray-7);
}

.help-article :deep(ul),
.help-article :deep(ol) {
  margin: 0 0 0.75rem 1.25rem;
  display: flex;
  flex-direction: column;
  gap: 0.375rem;
  font-size: 0.9375rem;
  line-height: 1.6;
  color: var(--ink-gray-7);
}

.help-article :deep(ul) {
  list-style: disc;
}

.help-article :deep(ol) {
  list-style: decimal;
}

.help-article :deep(strong) {
  font-weight: 600;
  color: var(--ink-gray-8);
}

.help-article :deep(code) {
  padding: 0.125rem 0.25rem;
  border-radius: 0.25rem;
  background: var(--surface-gray-2);
  font-size: 0.8125rem;
  color: var(--ink-gray-8);
}

.help-article :deep(table) {
  width: 100%;
  margin-bottom: 1rem;
  border-collapse: collapse;
  font-size: 0.875rem;
}

.help-article :deep(th) {
  padding: 0.5rem 0.625rem;
  border-bottom: 1px solid var(--outline-gray-2);
  text-align: left;
  font-weight: 600;
  color: var(--ink-gray-8);
}

.help-article :deep(td) {
  padding: 0.5rem 0.625rem;
  border-bottom: 1px solid var(--outline-gray-1);
  vertical-align: top;
  color: var(--ink-gray-7);
}

.help-article :deep(a) {
  color: var(--ink-gray-8);
  text-decoration: underline;
}
</style>
