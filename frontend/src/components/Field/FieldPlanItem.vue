<!-- One planned activity, as a rep reads it on site: what, where, how it went. -->
<template>
  <div class="v-glass rounded-5 px-3.5 py-3">
    <div class="flex items-start gap-3">
      <div
        class="mt-0.5 grid size-8 shrink-0 place-items-center rounded-full bg-surface-gray-2"
      >
        <component
          :is="typeIcon(item.activity_type)"
          class="size-4"
          :class="statusColor(item.status)"
          aria-hidden="true"
        />
      </div>
      <div class="min-w-0 flex-1">
        <div class="flex items-start justify-between gap-2">
          <div class="min-w-0 text-base font-medium text-ink-gray-9">
            {{ text.title }}
          </div>
          <span
            v-if="item.status !== 'Planned'"
            class="shrink-0 text-sm font-medium"
            :class="statusColor(item.status)"
          >
            {{ statusLabel(item.status) }}
          </span>
        </div>
        <div class="mt-0.5 text-sm text-ink-gray-6">
          <span>{{ __(activityLabel(item.activity_type)) }}</span>
          <template v-if="showCustomer && item.organization">
            <span aria-hidden="true"> · </span>
            <router-link
              v-if="known"
              :to="{
                name: 'FieldCustomer',
                params: { organization: item.organization },
              }"
              class="text-ink-gray-8 underline decoration-outline-gray-3 underline-offset-2"
            >
              {{ customerName }}
            </router-link>
            <span v-else>{{ customerName }}</span>
          </template>
          <template v-if="showDate">
            <span aria-hidden="true"> · </span>
            <span class="tabular-nums">{{ shortDate(item.planned_date) }}</span>
          </template>
        </div>
        <p
          v-if="text.detail"
          class="mt-2 whitespace-pre-line border-l-2 border-outline-gray-2 pl-2.5 text-p-sm text-ink-gray-7"
        >
          {{ text.detail }}
        </p>
      </div>
    </div>
  </div>
</template>

<script setup>
import { useField } from '@/offline/useField'
import { planItemText, shortDate } from '@/utils/fieldPack'
import { activityLabel } from '@/utils/planner'
import { statusColor, statusLabel, typeIcon } from '@/utils/plannerDisplay'
import { computed } from 'vue'

const props = defineProps({
  item: { type: Object, required: true },
  /* Off on a customer's own page, where every row is that customer. */
  showCustomer: { type: Boolean, default: true },
  /* On where rows from different days share a list. */
  showDate: { type: Boolean, default: false },
})

const { index } = useField()

const customer = computed(() => index.value.byName.get(props.item.organization))
const known = computed(() => !!customer.value)
const customerName = computed(
  () => customer.value?.organization_name || props.item.organization,
)

/* The planner's own rule for a card's title, so the two screens agree. On a
   customer's page the customer is not news, so the type stands in instead. */
const text = computed(() =>
  planItemText(
    props.item,
    (props.showCustomer && customerName.value) ||
      __(activityLabel(props.item.activity_type)),
  ),
)
</script>
