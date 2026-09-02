<template>
  <Dialog v-model:open="helpCenterVisible" bare :size="'5xl'">
    <template #default>
      <div class="flex h-[calc(100vh_-_8rem)] bg-surface-gray-1">
        <div
          class="m-1 flex w-64 shrink-0 flex-col rounded-l-[var(--v-radius-card)] bg-surface-gray-1"
        >
          <!-- The Mentor is the sparkle opposite the title: one click opens
               the conversation in the right pane, with its own examples. -->
          <div class="flex items-center justify-between px-3 pb-2 pt-[11px]">
            <div class="v-title-sm text-ink-gray-8">
              {{ __('Help Center') }}
            </div>
            <button
              type="button"
              class="grid size-7 place-items-center rounded-[var(--v-radius-control)] hover:bg-surface-gray-3"
              :class="mentorOpen ? 'bg-surface-gray-3' : ''"
              :aria-label="__('Ask the Mentor')"
              :title="__('Ask the Mentor')"
              @click="mentorOpen = true"
            >
              <SparkleIcon class="size-4 text-ink-violet-6" />
            </button>
          </div>
          <div class="px-2 pb-2">
            <!-- No debounce, deliberately: the search is client-side over a
                 dozen small articles, and a debounced emit races the click on
                 a result — the blur's delayed emit lands after openResult()
                 clears the box and puts the stale query back. -->
            <TextInput
              v-model="search"
              type="text"
              :placeholder="__('Search')"
            />
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
                    @click="showArticle(article.name)"
                  />
                </nav>
              </div>
            </template>
          </div>
        </div>

        <div
          class="flex flex-1 flex-col overflow-y-auto bg-surface-elevation-2"
        >
          <div v-if="mentorOpen" class="flex h-full min-h-0 flex-col">
            <div class="flex items-center justify-between px-4 pt-3">
              <div class="flex items-center gap-2">
                <SparkleIcon class="size-4 text-ink-gray-7" />
                <span class="v-title-sm text-ink-gray-8">{{
                  __('Mentor')
                }}</span>
              </div>
              <div class="flex items-center gap-1">
                <Button
                  v-if="mentorMessages.length"
                  :tooltip="__('Clear the conversation')"
                  :aria-label="__('Clear the conversation')"
                  icon="lucide-eraser"
                  variant="ghost"
                  @click="clearMentor"
                />
                <Button
                  :tooltip="__('Back to the manual')"
                  :aria-label="__('Back to the manual')"
                  icon="lucide-x"
                  variant="ghost"
                  @click="mentorOpen = false"
                />
              </div>
            </div>
            <AgentChat
              compact
              :messages="mentorMessages"
              :asking="mentorAsking"
              :failure="mentorFailure"
              :intro="mentorIntro"
              :examples="mentorExamples"
              :placeholder="__('Ask how Vectora works…')"
              :focus-when="mentorOpen"
              @send="askMentor"
              @retry="retryMentor"
            >
              <template #message-extra="{ message }">
                <div
                  v-if="message.relatedArticles?.length"
                  class="flex flex-wrap gap-1.5"
                >
                  <Button
                    v-for="name in message.relatedArticles"
                    :key="name"
                    variant="subtle"
                    size="sm"
                    :label="articleTitle(name)"
                    :iconLeft="LucideBookOpen"
                    @click="showArticle(name)"
                  />
                </div>
              </template>
              <template #failure="{ failure }">
                <p class="text-sm text-ink-gray-6">
                  {{
                    failure === 'disabled'
                      ? __(
                          'The mentor is switched off for this site. The manual on the left works either way.',
                        )
                      : __(
                          'The mentor could not be reached right now. Your question was not lost — try again in a moment.',
                        )
                  }}
                </p>
              </template>
            </AgentChat>
          </div>
          <div v-else-if="helpContent.loading" class="flex flex-col gap-3 p-8">
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
import { PhBookOpen as LucideBookOpen } from '@phosphor-icons/vue'
import AgentChat from '@/components/AgentChat.vue'
import SparkleIcon from '@/components/Icons/SparkleIcon.vue'
import ErrorState from '@/components/ui/ErrorState.vue'
import Skeleton from '@/components/ui/Skeleton.vue'
import {
  activeHelpArticle,
  helpCenterVisible,
  helpContent,
} from '@/stores/help'
import {
  askMentor,
  clearMentor,
  mentorAsking,
  mentorFailure,
  mentorMessages,
  mentorOpen,
  retryMentor,
} from '@/stores/mentor'
import { sanitizeHTML } from '@/utils'
import {
  groupArticles,
  renderArticleMarkdown,
  searchArticles,
} from '@/utils/helpCenter'
import { Dialog, SidebarItem, TextInput } from 'frappe-ui'
import { computed, ref, watch } from 'vue'

const search = ref('')

const mentorIntro = __(
  'Ask how Vectora works — screens, settings, and how the numbers are computed. The Mentor answers from this manual and cannot read or change your records.',
)
const mentorExamples = [
  __('What makes a deal show up as needing attention?'),
  __('How is quota attainment measured?'),
  __('What does the Analyst never do?'),
]

/* Chip labels come from the catalogue; the article name, de-kebabed, is
   honest enough for a button before it loads. */
function articleTitle(name) {
  const article = articles.value.find((a) => a.name === name)
  return article ? article.title : name.replaceAll('-', ' ')
}

function showArticle(name) {
  activeHelpArticle.value = name
  mentorOpen.value = false
}

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
  showArticle(name)
  search.value = ''
}

// A fresh open should read as a fresh open, not resume a stale search. The
// mentor transcript survives (it is the reader's own conversation), but the
// pane opens on the article the caller asked for.
watch(helpCenterVisible, (open) => {
  if (open) {
    search.value = ''
    mentorOpen.value = false
  }
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
