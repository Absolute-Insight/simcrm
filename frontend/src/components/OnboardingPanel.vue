<!--
  OnboardingPanel — the "Getting started" checklist, owned by this repo.

  It replaces @framework/ui's HelpModal, which had two problems no prop could
  fix: it floated over the top-right of every page (covering Refresh/Edit on
  the dashboard until onboarding was complete), and its "Help centre" footer
  opened an empty pane with an external docs link — the one thing the in-app
  help center exists to retire.

  The step *state* still lives in the framework: `useOnboarding()` registers,
  persists and syncs the steps, and `showHelpModal` / `minimize` stay the
  shared switches so the GettingStartedBanner and every step's onClick keep
  working untouched. Only the rendering moved.

  Anchored bottom-right and capped below the page header, so it can sit on
  screen without taking a control away from the page it is meant to teach.
-->
<template>
  <div
    v-if="open"
    class="fixed bottom-5 right-5 z-40 flex w-80 flex-col rounded-lg bg-surface-elevation-2 text-ink-gray-9"
    :class="collapsed ? '' : 'max-h-[calc(100vh_-_6rem)]'"
    :style="{ 'box-shadow': 'var(--elevation-lg)' }"
    @click.stop
  >
    <div class="flex items-center justify-between px-4 py-2.5">
      <div class="text-base font-medium">
        {{ __('Getting started') }}
        <span v-if="collapsed" class="ml-1 text-sm text-ink-gray-5">
          {{ __('{0}/{1} steps', [stepsCompleted, totalSteps]) }}
        </span>
      </div>
      <div class="flex gap-1">
        <Button
          variant="ghost"
          :aria-label="collapsed ? __('Expand') : __('Minimise')"
          :icon="collapsed ? 'lucide-chevron-up' : 'lucide-chevron-down'"
          @click="collapsed = !collapsed"
        />
        <Button
          variant="ghost"
          :aria-label="__('Close')"
          icon="lucide-x"
          @click="open = false"
        />
      </div>
    </div>

    <div v-show="!collapsed" class="flex min-h-0 flex-col px-3 pb-3">
      <div class="mb-4 mt-2 flex flex-col items-center gap-1">
        <component :is="logo" class="mb-3 size-10 shrink-0 rounded" />
        <div class="text-base font-medium">
          {{ __('Welcome to {0}', [title]) }}
        </div>
        <div class="text-p-base text-ink-gray-6">
          {{ __('{0}/{1} steps completed', [stepsCompleted, totalSteps]) }}
        </div>
      </div>

      <div class="flex items-center justify-between py-0.5">
        <Badge
          :label="__('{0}% completed', [completedPercentage])"
          :theme="completedPercentage == 100 ? 'green' : 'orange'"
          size="lg"
        />
        <div class="flex">
          <Button
            v-if="completedPercentage != 0"
            variant="ghost"
            :label="__('Reset all')"
            @click="() => resetAll?.(afterResetAll)"
          />
          <Button
            v-if="completedPercentage != 100"
            variant="ghost"
            :label="__('Skip all')"
            @click="() => skipAll?.(afterSkipAll)"
          />
        </div>
      </div>

      <div class="mt-2 flex min-h-0 flex-col gap-1.5 overflow-y-auto">
        <div
          v-for="step in steps || []"
          :key="step.name"
          class="group flex w-full cursor-pointer items-center justify-between gap-2 rounded px-2 py-1.5 hover:bg-surface-gray-1"
          @click.stop="
            () => !step.completed && !isDependent(step) && step.onClick?.()
          "
        >
          <Tooltip
            :text="dependsOnTooltip(step)"
            :disabled="!isDependent(step)"
          >
            <div
              class="flex items-center gap-2"
              :class="
                step.completed
                  ? 'text-ink-gray-5'
                  : isDependent(step)
                    ? 'text-ink-gray-4'
                    : 'text-ink-gray-8'
              "
            >
              <component :is="step.icon" class="h-4" />
              <div
                class="text-base"
                :class="{ 'line-through': step.completed }"
              >
                {{ step.title }}
              </div>
            </div>
          </Tooltip>
          <Button
            v-if="!step.completed && !isDependent(step)"
            :label="__('Skip')"
            class="!h-4 hidden text-xs !text-ink-gray-6 group-hover:flex"
            @click.stop="() => skip?.(step.name, afterSkip)"
          />
          <Button
            v-else-if="!isDependent(step)"
            :label="__('Reset')"
            class="!h-4 hidden text-xs !text-ink-gray-6 group-hover:flex"
            @click.stop="() => reset?.(step.name, afterReset)"
          />
        </div>
      </div>

      <!-- The in-app help center, not a docs site. -->
      <button
        type="button"
        class="mt-3 flex w-full items-center gap-2 rounded px-2 py-1.5 text-base text-ink-gray-8 hover:bg-surface-gray-1"
        @click="openHelpCenter()"
      >
        <HelpIcon class="h-4" />
        {{ __('Help center') }}
      </button>
    </div>
  </div>
</template>

<script setup>
import HelpIcon from '@/components/Icons/HelpIcon.vue'
import { openHelpCenter } from '@/stores/help'
import {
  minimize,
  showHelpModal,
  useOnboarding,
} from '@framework/ui/components/Onboarding'
import { Badge, Button, Tooltip } from 'frappe-ui'
import { isRef, ref, watch } from 'vue'

const props = defineProps({
  appName: { type: String, default: 'frappecrm' },
  title: { type: String, default: 'Vectora' },
  logo: { type: [Object, Function], required: true },
  afterSkip: { type: Function, default: null },
  afterSkipAll: { type: Function, default: null },
  afterReset: { type: Function, default: null },
  afterResetAll: { type: Function, default: null },
})

/* The no-op stub of @framework/ui exports these as functions, not refs
   (src/lib/framework-ui-stub). A function is truthy, so binding it straight to
   v-if would pin this panel open on every stub build. Fall back to local refs
   that stay closed. */
const open = isRef(showHelpModal) ? showHelpModal : ref(false)
const collapsed = isRef(minimize) ? minimize : ref(false)

const {
  steps,
  stepsCompleted,
  totalSteps,
  completedPercentage,
  skip,
  skipAll,
  reset,
  resetAll,
} = useOnboarding(props.appName)

/* setUp() opens the modal from the *persisted* completion flag; the real
   status arrives from the server a moment later. A user who finished
   onboarding long ago would otherwise get the checklist — every step struck
   through — on every first visit from a new browser. Nothing left to do means
   nothing to show, whenever that becomes known. */
watch(
  completedPercentage,
  (percent) => {
    if (percent === 100) open.value = false
  },
  { immediate: true },
)

function blockedBy(step) {
  if (!step.dependsOn || step.completed) return null
  const parent = (steps || []).find((s) => s.name === step.dependsOn)
  return parent && !parent.completed ? parent : null
}

function isDependent(step) {
  return Boolean(blockedBy(step))
}

function dependsOnTooltip(step) {
  const parent = blockedBy(step)
  return parent ? __('You need to complete "{0}" first.', [parent.title]) : ''
}
</script>
