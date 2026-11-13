<!-- One customer, as much of it as the phone carries: where they are, who to
     ask for, what is open, and what happened last time. -->
<template>
  <div class="flex flex-col gap-5">
    <router-link
      :to="{ name: 'FieldCustomers' }"
      class="-ml-1 flex min-h-9 w-fit items-center gap-1 rounded-5 pr-2 text-sm text-ink-gray-6 hover:text-ink-gray-8 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2"
    >
      <LucideChevronLeft class="size-4" aria-hidden="true" />
      {{ __('Customers') }}
    </router-link>

    <div
      v-if="!org"
      class="flex flex-col items-center gap-1 rounded-5 border border-dashed px-4 py-10 text-center"
    >
      <span class="text-base font-medium text-ink-gray-8">
        {{ __('This customer is not saved on this device') }}
      </span>
      <span class="text-p-base text-ink-gray-6">
        {{
          __(
            'It may belong to another rep, or have been added since the last sync.',
          )
        }}
      </span>
    </div>

    <template v-else>
      <div>
        <h2
          class="font-display text-2xl font-semibold leading-tight tracking-tight text-ink-gray-9"
        >
          {{ org.organization_name || org.name }}
        </h2>
        <div
          v-if="org.industry || org.territory"
          class="mt-1 text-sm text-ink-gray-6"
        >
          {{ [org.industry, org.territory].filter(Boolean).join(' · ') }}
        </div>

        <div
          v-if="address || org.address?.phone"
          class="mt-3 flex flex-col gap-2"
        >
          <div v-if="address" class="flex items-start gap-2.5 text-p-base">
            <LucideMapPin
              class="mt-0.5 size-4 shrink-0 text-ink-gray-5"
              aria-hidden="true"
            />
            <span class="text-ink-gray-8">{{ address }}</span>
          </div>
          <a
            v-if="telHref(org.address?.phone)"
            :href="telHref(org.address.phone)"
            class="flex min-h-9 w-fit items-center gap-2.5 text-p-base text-ink-gray-8 underline decoration-outline-gray-3 underline-offset-2"
          >
            <PhPhone
              class="size-4 shrink-0 text-ink-gray-5"
              aria-hidden="true"
            />
            <span class="tabular-nums">{{ org.address.phone }}</span>
          </a>
        </div>
      </div>

      <div class="flex flex-wrap gap-2">
        <Button
          variant="solid"
          :label="__('Log activity')"
          @click="openFieldDialog('log', { organization })"
        >
          <template #prefix>
            <LucideMapPinPlus class="size-4" aria-hidden="true" />
          </template>
        </Button>
        <Button
          :label="__('Add note')"
          @click="openFieldDialog('note', { organization })"
        >
          <template #prefix>
            <LucideNotebookPen class="size-4" aria-hidden="true" />
          </template>
        </Button>
      </div>

      <section :aria-label="__('Contacts')">
        <h3 class="v-kpi-label mb-2">{{ __('Contacts') }}</h3>
        <ul v-if="contacts.length" class="flex flex-col gap-2">
          <li
            v-for="contact in contacts"
            :key="contact.name"
            class="v-glass flex items-center justify-between gap-3 rounded-5 px-3.5 py-2.5"
          >
            <div class="min-w-0">
              <div class="truncate text-base font-medium text-ink-gray-9">
                {{ contact.full_name || contact.name }}
              </div>
              <div class="truncate text-sm text-ink-gray-6">
                {{
                  [contact.designation, contact.mobile_no || contact.phone]
                    .filter(Boolean)
                    .join(' · ') ||
                  contact.email_id ||
                  __('No phone or e-mail on record')
                }}
              </div>
            </div>
            <div class="flex shrink-0 items-center gap-1">
              <a
                v-if="telHref(contact.mobile_no || contact.phone)"
                :href="telHref(contact.mobile_no || contact.phone)"
                class="grid size-11 place-items-center rounded-full text-ink-gray-7 hover:bg-surface-gray-2 focus-visible:outline focus-visible:outline-2"
                :aria-label="
                  __('Call {0}', [contact.full_name || contact.name])
                "
              >
                <PhPhone class="size-5" aria-hidden="true" />
              </a>
              <a
                v-if="contact.email_id"
                :href="`mailto:${contact.email_id}`"
                class="grid size-11 place-items-center rounded-full text-ink-gray-7 hover:bg-surface-gray-2 focus-visible:outline focus-visible:outline-2"
                :aria-label="
                  __('E-mail {0}', [contact.full_name || contact.name])
                "
              >
                <PhEnvelope class="size-5" aria-hidden="true" />
              </a>
            </div>
          </li>
        </ul>
        <p v-else class="text-p-base text-ink-gray-6">
          {{ __('No contacts on record for this customer.') }}
        </p>
      </section>

      <section :aria-label="__('Open deals')">
        <h3 class="v-kpi-label mb-2">{{ __('Open deals') }}</h3>
        <ul v-if="deals.length" class="flex flex-col gap-2">
          <li
            v-for="deal in deals"
            :key="deal.name"
            class="v-glass rounded-5 px-3.5 py-2.5"
          >
            <div class="flex items-baseline justify-between gap-3">
              <span class="truncate text-base font-medium text-ink-gray-9">
                {{ deal.name }}
              </span>
              <span class="shrink-0 text-base tabular-nums text-ink-gray-8">
                {{ moneyLabel(deal.deal_value, deal.currency) }}
              </span>
            </div>
            <div class="mt-0.5 text-sm text-ink-gray-6">
              {{
                [
                  deal.status,
                  deal.expected_closure_date &&
                    __('closes {0}', [shortDate(deal.expected_closure_date)]),
                ]
                  .filter(Boolean)
                  .join(' · ')
              }}
            </div>
            <p v-if="deal.next_step" class="mt-1.5 text-p-sm text-ink-gray-7">
              {{ __('Next: {0}', [deal.next_step]) }}
            </p>
          </li>
        </ul>
        <p v-else class="text-p-base text-ink-gray-6">
          {{ __('No open deals with this customer.') }}
        </p>
      </section>

      <section :aria-label="__('Recent activity')">
        <h3 class="v-kpi-label mb-2">{{ __('Recent activity') }}</h3>
        <div v-if="history.length || notes.length" class="flex flex-col gap-2">
          <FieldPlanItem
            v-for="item in history"
            :key="item.name"
            :item="item"
            :showCustomer="false"
            showDate
          />
          <div
            v-for="note in notes"
            :key="note.name"
            class="v-glass rounded-5 px-3.5 py-3"
          >
            <div class="flex items-baseline justify-between gap-3">
              <span
                class="min-w-0 truncate text-base font-medium text-ink-gray-9"
              >
                {{ note.title || __('Note') }}
              </span>
              <span class="shrink-0 text-sm tabular-nums text-ink-gray-5">
                {{
                  note.pending
                    ? __('Waiting to send')
                    : shortDate(note.modified)
                }}
              </span>
            </div>
            <p
              v-if="note.content"
              class="mt-1 whitespace-pre-line text-p-sm text-ink-gray-7"
            >
              {{ note.content }}
            </p>
          </div>
        </div>
        <p v-else class="text-p-base text-ink-gray-6">
          {{
            __('Nothing recorded with this customer in the last {0} days.', [
              pack?.rules?.history_days ?? 90,
            ])
          }}
        </p>
      </section>
    </template>
  </div>
</template>

<script setup>
import FieldPlanItem from '@/components/Field/FieldPlanItem.vue'
import { openFieldDialog } from '@/offline/fieldDialog'
import { useField } from '@/offline/useField'
import { addressLine, moneyLabel, shortDate, telHref } from '@/utils/fieldPack'
import { PhEnvelope, PhPhone } from '@phosphor-icons/vue'
import { computed } from 'vue'
import LucideChevronLeft from '~icons/lucide/chevron-left'
import LucideMapPin from '~icons/lucide/map-pin'
import LucideMapPinPlus from '~icons/lucide/map-pin-plus'
import LucideNotebookPen from '~icons/lucide/notebook-pen'

const props = defineProps({
  organization: { type: String, required: true },
})

const { pack, index } = useField()

const org = computed(() => index.value.byName.get(props.organization))
const address = computed(() => addressLine(org.value?.address))
const contacts = computed(
  () => index.value.contacts.get(props.organization) ?? [],
)
const deals = computed(() => index.value.deals.get(props.organization) ?? [])
const history = computed(
  () => index.value.history.get(props.organization) ?? [],
)
const notes = computed(() => index.value.notes.get(props.organization) ?? [])
</script>
