<template>
  <!-- The notifications panel is absolutely positioned at `left: 100%`, so it
       needs a positioning context that is not the Sidebar itself (Sidebar sets
       overflow-x-hidden, which would clip the panel away).

       It also paints the sidebar surface: Sidebar's own `bg-surface-sidebar` is
       transparent in dark mode, and nothing behind it sets a background, so the
       column falls through to the white page canvas. The token cannot be
       overridden on the Sidebar element itself — `bg-surface-sidebar` is emitted
       after `bg-surface-gray-1` in the utilities layer and would win. -->
  <div class="v-shell-sidebar relative flex h-full">
    <Sidebar
      v-model:collapsed="isSidebarCollapsed"
      :disable-collapse="mobile"
      :width="mobile ? '260px' : undefined"
      class="border-r border-[var(--v-shell-hairline)]"
    >
      <div class="flex h-full flex-col p-2">
        <SidebarBrand
          :isCollapsed="isCollapsed"
          @toggle="isSidebarCollapsed = !isSidebarCollapsed"
        >
          <!-- Notifications and Suggestions are panels, not places, so they sit
               with the collapse control rather than in the nav list below.

               Icon-only costs the two states the labelled rows used to show: a
               number, and the en dash that told "nothing waiting" apart from
               "never managed to ask". The dot cannot carry either, so the
               title/aria-label does instead -- that distinction was deliberate
               and is not worth losing to a layout change. The dot appears only
               for a count we actually have. -->
          <template #actions>
            <button
              id="notifications-btn"
              class="relative grid size-6 shrink-0 place-items-center rounded-[var(--v-radius-control)] hover:bg-surface-gray-2"
              :class="
                notificationsActive
                  ? 'bg-surface-gray-3 text-ink-gray-9'
                  : 'text-ink-gray-7'
              "
              :aria-label="notificationsLabel"
              :title="notificationsLabel"
              @click="onNotificationsClick"
            >
              <NotificationsIcon class="size-4 text-ink-blue-6" />
              <span
                v-if="unreadNotificationsCount"
                class="absolute -right-0.5 -top-0.5 size-1.5 rounded-full bg-surface-gray-9 ring-1 ring-[var(--surface-gray-1)]"
              />
            </button>
            <button
              id="suggestions-btn"
              class="relative grid size-6 shrink-0 place-items-center rounded-[var(--v-radius-control)] hover:bg-surface-gray-2"
              :class="
                suggestionsActive
                  ? 'bg-surface-gray-3 text-ink-gray-9'
                  : 'text-ink-gray-7'
              "
              :aria-label="suggestionsLabel"
              :title="suggestionsLabel"
              @click="onSuggestionsClick"
            >
              <SuggestionsIcon class="size-4 text-ink-orange-6" />
              <span
                v-if="openSuggestionsCount"
                class="absolute -right-0.5 -top-0.5 size-1.5 rounded-full bg-surface-gray-9 ring-1 ring-[var(--surface-gray-1)]"
              />
            </button>
          </template>
        </SidebarBrand>

        <!-- overflow-y-auto forces overflow-x to clip too, which would slice the
             active row's shadow. Widen the scroll box to the sidebar edges and
             pad the content back in so the shadow has room. -->
        <div class="-mx-2 mt-2 flex flex-1 flex-col gap-1 overflow-y-auto px-2">
          <CollapsibleSection
            v-for="section in allViews"
            :key="section.name"
            :label="section.name"
            :hideLabel="section.hideLabel"
            :opened="section.opened"
          >
            <template #header="{ opened, hide, toggle }">
              <SidebarLabel
                v-if="!hide"
                divider
                class="mb-1 mt-4 select-none"
                :class="!isCollapsed && 'cursor-pointer'"
                @click="toggle()"
              >
                <span class="flex items-center gap-1.5">
                  <span
                    class="lucide-chevron-right -ml-0.5 size-4 shrink-0 text-ink-gray-9 transition-transform duration-300 ease-in-out"
                    :class="{ 'rotate-90': opened }"
                    aria-hidden="true"
                  />
                  <span class="truncate">{{ __(section.name) }}</span>
                </span>
              </SidebarLabel>
            </template>
            <nav class="flex flex-col gap-1">
              <SidebarItem
                v-for="link in section.views"
                :id="link.action ? link.action + '-btn' : undefined"
                :key="link.key"
                :to="link.to"
                :label="__(link.label)"
                :active="
                  link.action === 'assistant'
                    ? assistantVisible
                    : activeItem === link.key
                "
                @click="
                  link.action === 'assistant'
                    ? toggleAssistant()
                    : selectItem($event, link.key)
                "
              >
                <template #prefix>
                  <!-- Tints are the -6 step of each family. The ladder is a
                       readability one rather than a lightness one -- it runs
                       light-to-dark in light mode and dark-to-light in dark --
                       so a single class is correct in both themes.
                       -9 was the first choice and was wrong here: it is the
                       most legible step but also the least saturated, and in
                       dark mode it lands on a near-white pastel (mean HSV
                       saturation 0.23) that reads as barely coloured at 16px.
                       -6 measures 0.70 there for the same ten families, and
                       still clears the floor a non-text mark needs on both
                       canvases -- worst case 4.89:1 dark, 3.71:1 light against
                       3:1. 3:1 is the right floor rather than 4.5:1 because
                       every icon sits beside its own text label and never
                       carries the meaning alone.
                       Public and pinned views carry no tint and stay gray, so a
                       coloured icon always means a built-in surface. -->
                  <Icon
                    :icon="link.icon"
                    class="size-4"
                    :class="link.tint || 'text-ink-gray-7'"
                  />
                </template>
                <Tooltip
                  :text="__(link.label)"
                  side="right"
                  :hoverDelay="1.5"
                  :disabled="isCollapsed"
                >
                  <span class="truncate text-sm">{{ __(link.label) }}</span>
                </Tooltip>
              </SidebarItem>
            </nav>
          </CollapsibleSection>
        </div>

        <div v-if="!mobile" class="mt-auto flex flex-col gap-1 pt-2">
          <div class="mb-1 flex flex-col gap-2">
            <SignupBanner
              v-if="isDemoSite"
              :isSidebarCollapsed="isCollapsed"
              :afterSignup="() => capture('signup_from_demo_site')"
            />
            <TrialBanner
              v-if="isFCSite"
              :isSidebarCollapsed="isCollapsed"
              :afterUpgrade="() => capture('upgrade_plan_from_trial_banner')"
            />
            <!-- frappe-ui's own markup (button + wrapper divs) carries no
                 class, id, or data-slot hook of its own -- every class on it
                 is a shared Tailwind utility used elsewhere in the app -- so
                 wrap it here, in code we own, rather than reaching into its
                 internal structure from index.css. See the .v-getting-started
                 rule there for why (F3, low-contrast CTA button). -->
            <div v-if="!isOnboardingStepsCompleted" class="v-getting-started">
              <GettingStartedBanner :isSidebarCollapsed="isCollapsed" />
            </div>
          </div>
          <SidebarItem
            v-if="isManager() && isDemoDataCreated"
            :label="__('Clear Demo Data')"
            class="!text-ink-red-6 hover:!bg-surface-red-2"
            @click="() => clearDemoData()"
          >
            <template #prefix>
              <BrushCleaningIcon class="size-4" />
            </template>
          </SidebarItem>
          <SidebarUser :isCollapsed="isCollapsed" />
        </div>
      </div>
    </Sidebar>
    <Notifications v-if="!mobile" />
    <Suggestions v-if="!mobile" />
    <Assistant v-if="!mobile" />
  </div>

  <template v-if="!mobile">
    <Settings />
    <!-- The getting-started checklist. Rendered in-repo (OnboardingPanel)
         over the framework's step state, so it sits clear of page headers and
         its help link opens the in-app help center. -->
    <!-- v-if matters: useOnboarding() hands back the step list as it stands
         when called, and the steps are registered in onMounted. -->
    <OnboardingPanel
      v-if="showHelpModal"
      :logo="CRMLogo"
      :title="__('Vectora')"
      :afterSkip="(step) => capture('onboarding_step_skipped_' + step)"
      :afterSkipAll="() => capture('onboarding_steps_skipped')"
      :afterReset="(step) => capture('onboarding_step_reset_' + step)"
      :afterResetAll="() => capture('onboarding_steps_reset')"
    />
    <IntermediateStepModal
      v-model="showIntermediateModal"
      :currentStep="currentStep"
    />
  </template>
</template>

<script setup>
import { PhBroom as BrushCleaningIcon } from '@phosphor-icons/vue'
import { PhChartLineUp as AnalystIcon } from '@phosphor-icons/vue'
import DashboardIcon from '@/components/Icons/DashboardIcon.vue'
import PlannerIcon from '@/components/Icons/PlannerIcon.vue'
import ReportsIcon from '@/components/Icons/ReportsIcon.vue'
import SuggestionsIcon from '@/components/Icons/SuggestionsIcon.vue'
import CRMLogo from '@/components/Icons/CRMLogo.vue'
import InviteIcon from '@/components/Icons/InviteIcon.vue'
import ConvertIcon from '@/components/Icons/ConvertIcon.vue'
import CommentIcon from '@/components/Icons/CommentIcon.vue'
import EmailIcon from '@/components/Icons/EmailIcon.vue'
import StepsIcon from '@/components/Icons/StepsIcon.vue'
import CollapsibleSection from '@/components/CollapsibleSection.vue'
import Icon from '@/components/Icon.vue'
import PinIcon from '@/components/Icons/PinIcon.vue'
import SidebarBrand from '@/components/Layouts/SidebarBrand.vue'
import SidebarUser from '@/components/Layouts/SidebarUser.vue'
import SquareAsterisk from '@/components/Icons/SquareAsterisk.vue'
import LeadsIcon from '@/components/Icons/LeadsIcon.vue'
import DealsIcon from '@/components/Icons/DealsIcon.vue'
import ContactsIcon from '@/components/Icons/ContactsIcon.vue'
import OrganizationsIcon from '@/components/Icons/OrganizationsIcon.vue'
import NoteIcon from '@/components/Icons/NoteIcon.vue'
import TaskIcon from '@/components/Icons/TaskIcon.vue'
import CalendarIcon from '@/components/Icons/CalendarIcon.vue'
import PhoneIcon from '@/components/Icons/PhoneIcon.vue'
import NotificationsIcon from '@/components/Icons/NotificationsIcon.vue'
import Notifications from '@/components/Notifications.vue'
import Suggestions from '@/components/Suggestions.vue'
import Assistant from '@/components/Assistant.vue'
import SparkleIcon from '@/components/Icons/SparkleIcon.vue'
import { assistantVisible, toggleAssistant } from '@/stores/assistant'
import {
  suggestionsStore,
  openCountUnavailable,
  openSuggestionsCount,
  suggestionsVisible,
} from '@/stores/suggestions'
import Settings from '@/components/Settings/Settings.vue'
import { viewsStore } from '@/stores/views'
import {
  unreadCountUnavailable,
  unreadNotificationsCount,
  notificationsStore,
  visible as notificationsVisible,
} from '@/stores/notifications'
import { usersStore } from '@/stores/users'
import { sessionStore } from '@/stores/session'
import {
  showSettings,
  activeSettingsPage,
  mobileSidebarOpened,
} from '@/composables/settings'
import { showChangePasswordModal } from '@/composables/modals'
import { useBroadcast } from '@/composables/useBroadcast.js'
import { call, Sidebar, SidebarItem, SidebarLabel, Tooltip } from 'frappe-ui'
import { SignupBanner } from '@framework/ui/components/SignupBanner'
import { TrialBanner } from '@framework/ui/components/TrialBanner'
import OnboardingPanel from '@/components/OnboardingPanel.vue'
import {
  GettingStartedBanner,
  useOnboarding,
  showHelpModal,
  minimize,
  IntermediateStepModal,
} from '@framework/ui/components/Onboarding'
import { useTelemetry } from '@framework/ui/telemetry'
import router from '@/router'
import { useStorage } from '@vueuse/core'
import { useDemoData } from '@/composables/demoData'
import { ref, reactive, computed, markRaw, onMounted, watch } from 'vue'
import { useRoute } from 'vue-router'

const props = defineProps({
  mobile: { type: Boolean, default: false },
})

const route = useRoute()

const { getPinnedViews, getPublicViews } = viewsStore()
const { toggle: toggleNotificationPanel } = notificationsStore()
const { toggle: toggleSuggestionsPanel } = suggestionsStore()
const { capture } = useTelemetry()
const { clearDemoData, isDemoDataCreated } = useDemoData()
const { send } = useBroadcast()

const isSidebarCollapsed = useStorage('isSidebarCollapsed', false)

// The mobile drawer pins the sidebar open, so it is never visually collapsed
// even when the stored rail state says otherwise.
const isCollapsed = computed(() => isSidebarCollapsed.value && !props.mobile)

const isFCSite = ref(window.is_fc_site)
const isDemoSite = ref(window.is_demo_site)

const links = [
  // Order is product order, not alphabetical: what a rep opens first comes
  // first. Dashboard is the landing surface, Assistant answers the question
  // that sent them there, then the planning and pipeline surfaces, then the
  // records they act on.
  //
  // Dashboard, Planner and Reports are the surfaces Vectora is *for*, and they
  // were unreachable on a phone -- routed and rendering, just absent from the
  // one menu a mobile rep has. Each was checked at 390px: the dashboard stacks
  // its tiles, the planner falls back from a week grid to a day list, and the
  // reports table scrolls inside its own container. Calendar stays hidden
  // because it genuinely does not fit -- seven day-columns and a clipped
  // toolbar.
  //
  // `tint` is the -9 step of a colour family. See the comment on the nav row in
  // the template for why -9 and only -9.
  {
    label: 'Dashboard',
    icon: DashboardIcon,
    to: 'Dashboard',
    tint: 'text-ink-blue-6',
  },
  // The one entry that is not a place. Assistant opens a slide-over, so it
  // carries `action` instead of `to` and the row renders as a toggle -- it sits
  // second because it is the surface a rep reaches for from the dashboard, not
  // because it is a route. On mobile the panel has nowhere to slide from, the
  // same condition it carried when it lived above this list.
  {
    label: 'Assistant',
    icon: SparkleIcon,
    action: 'assistant',
    tint: 'text-ink-violet-6',
    condition: () => !props.mobile,
  },
  {
    label: 'Planner',
    icon: PlannerIcon,
    to: 'Planner',
    tint: 'text-ink-teal-6',
  },
  {
    label: 'Leads',
    icon: LeadsIcon,
    to: 'Leads',
    tint: 'text-ink-orange-6',
  },
  {
    label: 'Deals',
    icon: DealsIcon,
    to: 'Deals',
    tint: 'text-ink-green-6',
  },
  {
    label: 'Reports',
    icon: ReportsIcon,
    to: 'Reports',
    tint: 'text-ink-purple-6',
  },
  // Analyst arrived with the AI surfaces after this order was specified. It is
  // admin-only and it is an analytics surface, so it sits beside Reports rather
  // than at the end where an unplaced item would otherwise land.
  {
    label: 'Analyst',
    icon: AnalystIcon,
    to: 'Analyst',
    tint: 'text-ink-cyan-6',
    condition: () => isAdmin(),
  },
  {
    label: 'Notes',
    icon: NoteIcon,
    to: 'Notes',
    tint: 'text-ink-yellow-6',
  },
  {
    label: 'Tasks',
    icon: TaskIcon,
    to: 'Tasks',
    tint: 'text-ink-pink-6',
  },
  {
    label: 'Calendar',
    icon: CalendarIcon,
    to: 'Calendar',
    tint: 'text-ink-red-6',
    condition: () => !props.mobile,
  },
  {
    label: 'Organizations',
    icon: OrganizationsIcon,
    to: 'Organizations',
    tint: 'text-ink-teal-6',
  },
  {
    label: 'Contacts',
    icon: ContactsIcon,
    to: 'Contacts',
    tint: 'text-ink-blue-6',
  },
  {
    label: 'Call Logs',
    icon: PhoneIcon,
    to: 'Call Logs',
    tint: 'text-ink-orange-6',
  },
]

const allViews = computed(() => {
  let _views = [
    {
      name: 'All Views',
      hideLabel: true,
      opened: true,
      views: links
        .filter((link) => {
          if (link.condition) {
            return link.condition()
          }
          return true
        })
        .map((link) => ({
          label: link.label,
          icon: link.icon,
          tint: link.tint,
          action: link.action,
          // An action row has no route, so `to` must stay undefined -- passing
          // `{ name: undefined }` makes SidebarItem render a RouterLink that
          // resolves to nothing and swallows the click.
          key: link.action || link.to,
          to: link.action ? undefined : { name: link.to },
        })),
    },
  ]
  if (getPublicViews().length) {
    _views.push({
      name: 'Public Views',
      opened: true,
      views: parseView(getPublicViews()),
    })
  }

  if (getPinnedViews().length) {
    _views.push({
      name: 'Pinned Views',
      opened: true,
      views: parseView(getPinnedViews()),
    })
  }
  return _views
})

function parseView(views) {
  return views.map((view) => {
    return {
      label: view.label,
      icon: getIcon(view.route_name, view.icon),
      key: view.name,
      to: {
        name: view.route_name,
        params: { viewType: view.type || 'list' },
        query: { view: view.name },
      },
    }
  })
}

function getIcon(routeName, icon) {
  if (icon) return icon

  switch (routeName) {
    case 'Leads':
      return LeadsIcon
    case 'Deals':
      return DealsIcon
    case 'Contacts':
      return ContactsIcon
    case 'Organizations':
      return OrganizationsIcon
    case 'Notes':
      return NoteIcon
    case 'Call Logs':
      return PhoneIcon
    default:
      return PinIcon
  }
}

// A saved view's key is its name; a plain nav item's key is its route name.
function currentRouteKey() {
  return route.query.view || route.name
}

// Set the highlight on click rather than waiting for the route, since route
// components are lazily imported and the first visit waits on a chunk fetch.
// Modified clicks open a new tab without navigating this one, so they must not
// move the highlight here.
const activeItem = ref(currentRouteKey())

function selectItem(event, key) {
  if (
    event.metaKey ||
    event.ctrlKey ||
    event.shiftKey ||
    event.altKey ||
    event.button === 1
  ) {
    return
  }
  activeItem.value = key
  // Selecting the row for the route already open leaves the URL unchanged, so
  // the drawer's navigation watcher never fires. Close it here too.
  if (props.mobile) {
    mobileSidebarOpened.value = false
  }
}

watch(
  () => [route.name, route.query.view],
  () => (activeItem.value = currentRouteKey()),
)

// The optimistic highlight above has to be taken back when the navigation it
// predicted does not happen. A route guard that returns false -- the Planner's
// unsaved-changes prompt, answered with "Keep editing" -- leaves route.name
// untouched, so the watcher never fires and the sidebar goes on pointing at a
// page the user is not on. afterEach's third argument is that failure.
router.afterEach((to, from, failure) => {
  if (failure) activeItem.value = currentRouteKey()
})

// The two panel toggles sit in the brand row now, as plain buttons rather than
// SidebarItems. Everything SidebarItem used to supply for them -- the active
// styling, the accessible name, and on mobile the navigation itself -- has to
// be supplied here instead. `router` is the instance already imported above.
const notificationsActive = computed(() =>
  props.mobile
    ? activeItem.value === 'Notifications'
    : notificationsVisible.value,
)
const suggestionsActive = computed(() =>
  props.mobile ? activeItem.value === 'Suggestions' : suggestionsVisible.value,
)

// Icon-only leaves nowhere to print the count, so the accessible name carries
// it. That includes the "could not ask" case: a dot that simply stays hidden
// reads exactly like "nothing waiting", and telling those two apart was the
// point of the en-dash badge these buttons replaced.
const notificationsLabel = computed(() => {
  if (unreadCountUnavailable.value) {
    return __('Notifications — unread count unavailable')
  }
  if (unreadNotificationsCount.value) {
    return __('Notifications ({0} unread)', [unreadNotificationsCount.value])
  }
  return __('Notifications')
})
const suggestionsLabel = computed(() => {
  if (openCountUnavailable.value) {
    return __('Suggestions — count unavailable')
  }
  if (openSuggestionsCount.value) {
    return __('Suggestions ({0} open)', [openSuggestionsCount.value])
  }
  return __('Suggestions')
})

function onNotificationsClick(event) {
  if (props.mobile) {
    selectItem(event, 'Notifications')
    // A <button> has no href, so nothing navigates on its own any more -- and
    // for the same reason the modifier-click case selectItem guards against
    // cannot arise here.
    router.push({ name: 'Notifications' })
  } else {
    toggleNotificationPanel()
  }
}

function onSuggestionsClick(event) {
  if (props.mobile) {
    selectItem(event, 'Suggestions')
    router.push({ name: 'Suggestions' })
  } else {
    toggleSuggestionsPanel()
  }
}

// onboarding
const { user } = sessionStore()
const { users, isManager, isAdmin } = usersStore()
const { isOnboardingStepsCompleted, setUp } = useOnboarding('frappecrm')

async function getFirstLead() {
  let firstLead = localStorage.getItem('firstLead' + user)
  if (firstLead) return firstLead
  return await call('crm.api.onboarding.get_first_lead')
}

async function getFirstDeal() {
  let firstDeal = localStorage.getItem('firstDeal' + user)
  if (firstDeal) return firstDeal
  return await call('crm.api.onboarding.get_first_deal')
}

const showIntermediateModal = ref(false)
const currentStep = ref({})

const steps = reactive([
  {
    name: 'setup_your_password',
    title: __('Setup your password'),
    icon: markRaw(SquareAsterisk),
    completed: false,
    onClick: () => {
      minimize.value = true
      showChangePasswordModal.value = true
      capture('onboarding_step_clicked_setup_password')
    },
  },
  {
    name: 'create_first_lead',
    title: __('Create your first lead'),
    icon: markRaw(LeadsIcon),
    completed: false,
    onClick: () => {
      minimize.value = true
      router.push({ name: 'Leads' })
      send('trigger_lead_create', true)
      capture('onboarding_step_clicked_create_first_lead')
    },
  },
  {
    name: 'invite_your_team',
    title: __('Invite your team'),
    icon: markRaw(InviteIcon),
    completed: false,
    onClick: () => {
      minimize.value = true
      showSettings.value = true
      activeSettingsPage.value = 'Invite User'
      capture('onboarding_step_clicked_invite_your_team')
    },
    condition: () => isManager(),
  },
  {
    name: 'convert_lead_to_deal',
    title: __('Convert lead to deal'),
    icon: markRaw(ConvertIcon),
    completed: false,
    dependsOn: 'create_first_lead',
    onClick: async () => {
      minimize.value = true
      capture('onboarding_step_clicked_convert_lead_to_deal')
      currentStep.value = {
        title: __('Convert lead to deal'),
        buttonLabel: __('Convert'),
        videoURL: '/assets/crm/videos/convertToDeal.mov',
        onClick: async () => {
          showIntermediateModal.value = false
          currentStep.value = {}

          let lead = await getFirstLead()
          if (lead) {
            router.push({ name: 'Lead', params: { leadId: lead } })
          } else {
            router.push({ name: 'Leads' })
          }
        },
      }
      showIntermediateModal.value = true
    },
  },
  {
    name: 'create_first_task',
    title: __('Create your first task'),
    icon: markRaw(TaskIcon),
    completed: false,
    onClick: async () => {
      minimize.value = true
      let deal = await getFirstDeal()
      capture('onboarding_step_clicked_create_first_task')

      if (deal) {
        router.push({
          name: 'Deal',
          params: { dealId: deal },
          hash: '#tasks',
        })
      } else {
        router.push({ name: 'Tasks' })
      }
    },
  },
  {
    name: 'create_first_note',
    title: __('Create your first note'),
    icon: markRaw(NoteIcon),
    completed: false,
    onClick: async () => {
      minimize.value = true
      let deal = await getFirstDeal()
      capture('onboarding_step_clicked_create_first_note')

      if (deal) {
        router.push({
          name: 'Deal',
          params: { dealId: deal },
          hash: '#notes',
        })
      } else {
        router.push({ name: 'Notes' })
      }
    },
  },
  {
    name: 'add_first_comment',
    title: __('Add your first comment'),
    icon: markRaw(CommentIcon),
    completed: false,
    dependsOn: 'create_first_lead',
    onClick: async () => {
      minimize.value = true
      let deal = await getFirstDeal()
      capture('onboarding_step_clicked_add_first_comment')

      if (deal) {
        router.push({
          name: 'Deal',
          params: { dealId: deal },
          hash: '#comments',
        })
      } else {
        router.push({ name: 'Leads' })
      }
    },
  },
  {
    name: 'send_first_email',
    title: __('Send email'),
    icon: markRaw(EmailIcon),
    completed: false,
    dependsOn: 'create_first_lead',
    onClick: async () => {
      minimize.value = true
      let deal = await getFirstDeal()
      capture('onboarding_step_clicked_send_first_email')

      if (deal) {
        router.push({
          name: 'Deal',
          params: { dealId: deal },
          hash: '#emails',
        })
      } else {
        router.push({ name: 'Leads' })
      }
    },
  },
  {
    name: 'change_deal_status',
    title: __('Change deal status'),
    icon: markRaw(StepsIcon),
    completed: false,
    dependsOn: 'convert_lead_to_deal',
    onClick: async () => {
      minimize.value = true
      capture('onboarding_step_clicked_change_deal_status')

      currentStep.value = {
        title: __('Change deal status'),
        buttonLabel: __('Change'),
        videoURL: '/assets/crm/videos/changeDealStatus.mov',
        onClick: async () => {
          showIntermediateModal.value = false
          currentStep.value = {}

          let deal = await getFirstDeal()
          if (deal) {
            router.push({
              name: 'Deal',
              params: { dealId: deal },
              hash: '#activity',
            })
          } else {
            router.push({ name: 'Leads' })
          }
        },
      }
      showIntermediateModal.value = true
    },
  },
])

onMounted(async () => {
  if (props.mobile) return

  await users.promise

  const filteredSteps = steps.filter((step) => {
    if (step.condition) {
      return step.condition()
    }
    return true
  })

  setUp(filteredSteps)
})
</script>
