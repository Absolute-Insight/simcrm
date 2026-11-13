<!-- The rep's open tasks, in the order to do them. -->
<template>
  <div class="flex flex-col gap-2">
    <div
      v-for="task in tasks"
      :key="task.name"
      class="v-glass rounded-5 px-3.5 py-3"
    >
      <div class="flex items-start justify-between gap-3">
        <span class="min-w-0 text-base font-medium text-ink-gray-9">
          {{ task.title }}
        </span>
        <span
          v-if="task.due_day"
          class="shrink-0 text-sm font-medium tabular-nums"
          :class="task.overdue ? 'text-ink-red-9' : 'text-ink-gray-6'"
        >
          {{
            task.overdue
              ? __('Overdue · {0}', [shortDate(task.due_day)])
              : task.due_day === today
                ? __('Today')
                : shortDate(task.due_day)
          }}
        </span>
      </div>
      <div class="mt-0.5 text-sm text-ink-gray-6">
        {{
          [
            __(task.status),
            task.priority && __('{0} priority', [__(task.priority)]),
            task.reference_docname,
          ]
            .filter(Boolean)
            .join(' · ')
        }}
      </div>
      <p
        v-if="task.description"
        class="mt-1.5 line-clamp-4 whitespace-pre-line text-p-sm text-ink-gray-7"
      >
        {{ task.description }}
      </p>
    </div>

    <div
      v-if="!tasks.length"
      class="flex flex-col items-center gap-1 rounded-5 border border-dashed px-4 py-10 text-center"
    >
      <LucideListChecks
        class="mb-1 size-6 text-ink-gray-5"
        aria-hidden="true"
      />
      <span class="text-base font-medium text-ink-gray-8">
        {{ __('No open tasks') }}
      </span>
      <span class="text-p-base text-ink-gray-6">
        {{ __('Tasks assigned to you appear here until they are done.') }}
      </span>
    </div>
  </div>
</template>

<script setup>
import { useField } from '@/offline/useField'
import { orderTasks, shortDate } from '@/utils/fieldPack'
import { computed } from 'vue'
import LucideListChecks from '~icons/lucide/list-checks'

const { pack, today } = useField()

const tasks = computed(() => orderTasks(pack.value?.tasks, today.value))
</script>
