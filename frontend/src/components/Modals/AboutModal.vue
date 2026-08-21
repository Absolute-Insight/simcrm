<template>
  <Dialog v-model:open="show" bare :size="'sm'">
    <template #default>
      <div class="p-4 pt-5">
        <div class="flex justify-center">
          <div class="flex flex-col items-center">
            <CRMLogo class="mb-3 size-12" />
            <h3 class="text-2xl-semibold text-ink-gray-9">Vectora</h3>
          </div>
        </div>
        <hr class="border-t my-3 mx-2" />
        <div>
          <a
            v-for="link in links"
            :key="link.label"
            class="flex py-2 px-2 hover:bg-surface-gray-1 rounded-4 cursor-pointer"
            target="_blank"
            :href="link.url"
          >
            <component
              :is="link.icon"
              v-if="link.icon"
              class="size-4 mr-2 text-ink-gray-7"
            />
            <span class="text-base text-ink-gray-8">
              {{ link.label }}
            </span>
          </a>
        </div>
        <hr class="border-t my-3 mx-2" />
        <!-- Attribution, not decoration: this is AGPLv3 software built on
             Frappe CRM, and saying so is both a licence obligation and the
             honest answer to "what is this?". -->
        <p class="text-sm text-ink-gray-6 px-2 mt-2">
          © Frappe Technologies Pvt. Ltd. and contributors
        </p>
        <p class="text-sm text-ink-gray-5 px-2 mt-1">
          {{ __('Built on Frappe CRM. Licensed under the AGPL v3.') }}
        </p>
      </div>
    </template>
  </Dialog>
</template>
<script setup>
import CRMLogo from '@/components/Icons/CRMLogo.vue'
import GitHubIcon from '@/components/Icons/GitHubIcon.vue'
import LucideBug from '~icons/lucide/bug'
import LucideBookOpen from '~icons/lucide/book-open'

let show = defineModel({ type: Boolean })

/* This dialog carried the Vectora name and logo above five links that all led
   to Frappe. A bug in Vectora's planner filed on frappe/crm wastes the
   reporter's time and an upstream maintainer's, and support.frappe.io does not
   support this product at all — that link promised help that does not exist.

   The documentation link stays pointed upstream on purpose. Most of this CRM
   *is* Frappe CRM and those pages describe it accurately; swapping them for a
   Vectora docs site that has not been written would trade a useful link for a
   dead one. It is labelled for what it covers. */
let links = [
  {
    label: __('GitHub Repository'),
    url: 'https://github.com/Absolute-Insight/simcrm',
    icon: GitHubIcon,
  },
  {
    label: __('Vectora help centre'),
    url: '/crm/help',
    icon: LucideBookOpen,
  },
  {
    label: __('Report an Issue'),
    url: 'https://github.com/Absolute-Insight/simcrm/issues',
    icon: LucideBug,
  },
]
</script>
