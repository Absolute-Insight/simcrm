<!-- The customers this rep may see, searchable without a server. -->
<template>
  <div class="flex flex-col gap-3">
    <TextInput
      v-model="query"
      type="search"
      size="xl"
      inputmode="search"
      enterkeyhint="search"
      autocomplete="off"
      :placeholder="__('Search customers')"
      :aria-label="__('Search customers')"
    >
      <template #prefix>
        <LucideSearch class="size-4 text-ink-gray-5" aria-hidden="true" />
      </template>
    </TextInput>

    <div class="text-sm tabular-nums text-ink-gray-5" aria-live="polite">
      {{ countLabel }}
    </div>

    <ul v-if="result.rows.length" class="flex flex-col gap-2">
      <li v-for="org in result.rows" :key="org.name">
        <router-link
          :to="{ name: 'FieldCustomer', params: { organization: org.name } }"
          class="v-glass v-glass-hover flex min-h-14 items-center justify-between gap-3 rounded-5 px-3.5 py-2.5 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2"
        >
          <div class="min-w-0">
            <div class="truncate text-base font-medium text-ink-gray-9">
              {{ org.organization_name || org.name }}
            </div>
            <div class="truncate text-sm text-ink-gray-6">
              {{ subtitle(org) }}
            </div>
          </div>
          <LucideChevronRight
            class="size-4 shrink-0 text-ink-gray-5"
            aria-hidden="true"
          />
        </router-link>
      </li>
    </ul>

    <div
      v-else
      class="flex flex-col items-center gap-1 rounded-5 border border-dashed px-4 py-10 text-center"
    >
      <LucideBuilding2 class="mb-1 size-6 text-ink-gray-5" aria-hidden="true" />
      <span class="text-base font-medium text-ink-gray-8">
        {{ query ? __('No customer matches') : __('No customers yet') }}
      </span>
      <span class="text-p-base text-ink-gray-6">
        {{
          query
            ? __('Nothing saved on this device matches “{0}”.', [query])
            : __('Customers assigned to you are saved here when you sync.')
        }}
      </span>
    </div>

    <p
      v-if="pack?.truncated?.includes('organizations')"
      class="text-sm text-ink-gray-6"
    >
      {{
        __(
          'There are more customers than a device carries. Search online for the rest.',
        )
      }}
    </p>
  </div>
</template>

<script setup>
import { useField } from '@/offline/useField'
import { searchCustomers } from '@/utils/fieldPack'
import { computed, ref } from 'vue'
import LucideBuilding2 from '~icons/lucide/building-2'
import LucideChevronRight from '~icons/lucide/chevron-right'
import LucideSearch from '~icons/lucide/search'

const { pack, index } = useField()
const query = ref('')

const result = computed(() =>
  searchCustomers(pack.value?.organizations, query.value),
)

const countLabel = computed(() => {
  const { rows, total } = result.value
  if (!total) return ''
  if (rows.length < total) {
    return __('Showing {0} of {1}. Type to narrow it down.', [
      rows.length,
      total,
    ])
  }
  return total === 1 ? __('1 customer') : __('{0} customers', [total])
})

function subtitle(org) {
  const deals = index.value.deals.get(org.name)?.length ?? 0
  const place = org.address?.city || org.territory || ''
  const open =
    deals === 1 ? __('1 open deal') : deals ? __('{0} open deals', [deals]) : ''
  return [place, open].filter(Boolean).join(' · ') || __('No open deals')
}
</script>
