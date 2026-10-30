<template>
  <div class="text-ink-gray-6 flex items-center gap-1.5">
    <template v-for="(item, index) in items" :key="item.tab">
      <span v-if="index" class="text-4xl leading-[0]" aria-hidden="true">
        &middot;
      </span>
      <Tooltip :text="item.tooltip">
        <!-- The card is a link. Stopping here is how its other control, the
             actions dropdown, stays clickable too. -->
        <button
          type="button"
          class="flex items-center gap-1.5 rounded bg-transparent p-0 hover:text-ink-gray-9 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-outline-gray-4 focus-visible:ring-offset-1"
          :aria-label="item.tooltip"
          @click.stop.prevent="openTab(item.tab)"
        >
          <component :is="item.icon" class="h-4 w-4" aria-hidden="true" />
          <span v-if="item.count">{{ item.count }}</span>
        </button>
      </Tooltip>
    </template>
  </div>
</template>

<script setup>
import EmailAtIcon from '@/components/Icons/EmailAtIcon.vue'
import NoteIcon from '@/components/Icons/NoteIcon.vue'
import TaskIcon from '@/components/Icons/TaskIcon.vue'
import CommentIcon from '@/components/Icons/CommentIcon.vue'
import { Tooltip } from 'frappe-ui'
import { useRouter } from 'vue-router'
import { computed } from 'vue'

const props = defineProps({
  // The card's own route; the tab is added to it as a hash.
  route: { type: Object, required: true },
  counts: { type: Object, default: () => ({}) },
})

const router = useRouter()

const items = computed(() =>
  [
    { tab: 'emails', icon: EmailAtIcon, label: __('Emails') },
    { tab: 'notes', icon: NoteIcon, label: __('Notes') },
    { tab: 'tasks', icon: TaskIcon, label: __('Tasks') },
    { tab: 'comments', icon: CommentIcon, label: __('Comments') },
  ].map((item) => {
    const count = props.counts[item.tab] || 0
    return {
      ...item,
      count,
      tooltip: count ? `${count} ${item.label}` : item.label,
    }
  }),
)

function openTab(tab) {
  router.push({ ...props.route, hash: `#${tab}` })
}
</script>
