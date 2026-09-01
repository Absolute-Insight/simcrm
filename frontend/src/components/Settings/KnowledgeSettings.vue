<template>
  <div class="flex h-full flex-col gap-4 p-8">
    <div class="flex items-start justify-between gap-4">
      <div class="flex flex-col gap-1">
        <h2 class="v-title text-ink-gray-8">{{ __('Knowledge') }}</h2>
        <p class="text-p-sm text-ink-gray-5">
          {{
            __(
              'What the Assistant may say about your products, materials, standards and industries. It answers reps only from these articles — nothing here is guessed.',
            )
          }}
        </p>
      </div>
      <div class="flex shrink-0 items-center gap-2">
        <Button
          :label="__('Import sample knowledge')"
          :loading="importing"
          @click="confirmImport"
        />
        <Button
          variant="solid"
          :label="__('New article')"
          icon-left="lucide-plus"
          @click="openEditor(null)"
        />
      </div>
    </div>

    <TextInput
      v-model="search"
      type="text"
      :placeholder="__('Search titles, tags and bodies')"
    >
      <template #prefix>
        <LucideSearch class="size-4 text-ink-gray-5" />
      </template>
    </TextInput>

    <SkeletonTable
      v-if="articles.loading"
      :columns="4"
      :rows="6"
      density="compact"
      class="flex-1"
      :label="__('Loading knowledge articles')"
    />

    <ErrorState
      v-else-if="articles.error"
      class="flex-1"
      :error="articles.error"
      :title="__('Could not load the knowledge base')"
      :retry="articles.reload"
    />

    <div
      v-else-if="!rows.length"
      class="flex flex-1 flex-col items-center justify-center gap-3 rounded-lg border border-dashed border-outline-gray-2 p-8 text-center"
    >
      <p class="text-base text-ink-gray-7">
        {{
          search.trim()
            ? __('Nothing matches "{0}"', [search.trim()])
            : __('No knowledge yet. The Assistant has nothing to answer from.')
        }}
      </p>
      <p v-if="!search.trim()" class="max-w-md text-sm text-ink-gray-5">
        {{
          __(
            'Import the sample pack to see the shape — a valve knowledge base with sizes, materials, standards and a selection guide by industry — then replace it with your own.',
          )
        }}
      </p>
      <Button
        v-if="!search.trim()"
        :label="__('Import sample knowledge')"
        :loading="importing"
        @click="confirmImport"
      />
    </div>

    <div v-else class="flex-1 overflow-y-auto">
      <div v-for="group in groups" :key="group.category" class="mb-5">
        <div class="mb-1 px-1 text-xs-medium text-ink-gray-5">
          {{ group.category || __('Uncategorised') }}
        </div>
        <div
          class="divide-y divide-outline-gray-1 rounded-lg border border-outline-gray-1"
        >
          <div
            v-for="article in group.articles"
            :key="article.name"
            class="flex items-center gap-3 px-3 py-2"
          >
            <button
              type="button"
              class="flex min-w-0 flex-1 flex-col items-start gap-0.5 text-left"
              @click="openEditor(article)"
            >
              <span class="truncate text-base text-ink-gray-8">
                {{ article.title }}
              </span>
              <span
                v-if="article.tags"
                class="line-clamp-1 text-xs text-ink-gray-5"
              >
                {{ article.tags }}
              </span>
            </button>
            <Badge
              v-if="article.product"
              variant="subtle"
              :label="article.product"
            />
            <Switch
              :model-value="!!article.available_to_assistant"
              size="sm"
              :label="__('Available')"
              @update:model-value="toggleAvailable(article, $event)"
            />
            <Button
              variant="ghost"
              icon="lucide-trash-2"
              :aria-label="__('Delete')"
              @click="confirmDelete(article)"
            />
          </div>
        </div>
      </div>
    </div>

    <KnowledgeArticleModal
      v-model="editorOpen"
      :article="editing"
      @saved="articles.reload()"
    />
  </div>
</template>

<script setup>
import { PhMagnifyingGlass as LucideSearch } from '@phosphor-icons/vue'
import KnowledgeArticleModal from '@/components/Modals/KnowledgeArticleModal.vue'
import ErrorState from '@/components/ui/ErrorState.vue'
import SkeletonTable from '@/components/ui/SkeletonTable.vue'
import { globalStore } from '@/stores/global'
import { describeError } from '@/utils/describeError'
import {
  Badge,
  Button,
  Switch,
  TextInput,
  call,
  createResource,
  toast,
} from 'frappe-ui'
import { computed, ref } from 'vue'

const { $dialog } = globalStore()

const search = ref('')
const importing = ref(false)
const editorOpen = ref(false)
const editing = ref(null)

const articles = createResource({
  url: 'crm.api.knowledge.list_articles',
  auto: true,
  transform: (data) => data?.articles || [],
})

const rows = computed(() => {
  const all = articles.data || []
  const query = search.value.trim().toLowerCase()
  if (!query) return all
  return all.filter((a) =>
    [a.title, a.tags, a.category, a.body].some((field) =>
      (field || '').toLowerCase().includes(query),
    ),
  )
})

const groups = computed(() => {
  const byCategory = new Map()
  for (const article of rows.value) {
    const key = article.category || ''
    if (!byCategory.has(key)) byCategory.set(key, [])
    byCategory.get(key).push(article)
  }
  return [...byCategory.entries()].map(([category, list]) => ({
    category,
    articles: list,
  }))
})

function openEditor(article) {
  editing.value = article
  editorOpen.value = true
}

async function toggleAvailable(article, on) {
  try {
    await call('crm.api.knowledge.save_article', {
      doc: { name: article.name, available_to_assistant: on ? 1 : 0 },
    })
    article.available_to_assistant = on ? 1 : 0
  } catch (e) {
    toast.error(describeError(e).message || __('Could not save that change'))
  }
}

function confirmDelete(article) {
  $dialog({
    title: __('Delete this article?'),
    message: __(
      '"{0}" will be removed from the knowledge base. The Assistant stops quoting it immediately.',
      [article.title],
    ),
    actions: [
      {
        label: __('Delete'),
        theme: 'red',
        variant: 'solid',
        async onClick({ close }) {
          try {
            await call('crm.api.knowledge.delete_article', {
              name: article.name,
            })
            close()
            articles.reload()
          } catch (e) {
            toast.error(
              describeError(e).message || __('Could not delete the article'),
            )
          }
        },
      },
    ],
  })
}

function confirmImport() {
  $dialog({
    title: __('Import sample knowledge?'),
    message: __(
      'Adds a sample valve knowledge base — valve types, actuators, flow meters, materials, pressure classes, standards and a selection guide by industry. Articles whose title already exists are skipped, so this is safe to run again. Replace the samples with your own knowledge before reps rely on them.',
    ),
    actions: [
      {
        label: __('Import'),
        variant: 'solid',
        async onClick({ close }) {
          importing.value = true
          try {
            const result = await call('crm.api.knowledge.import_samples')
            close()
            toast.success(
              __('{0} articles imported, {1} already existed', [
                result.imported,
                result.skipped,
              ]),
            )
            articles.reload()
          } catch (e) {
            toast.error(
              describeError(e).message || __('Could not import the samples'),
            )
          } finally {
            importing.value = false
          }
        },
      },
    ],
  })
}
</script>
