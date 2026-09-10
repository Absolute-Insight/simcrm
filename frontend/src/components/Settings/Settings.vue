<template>
  <Dialog
    v-model:open="showSettings"
    bare
    :size="'5xl'"
    :dismissible="!disableSettingModalOutsideClick"
    @close="activeSettingsPage = ''"
  >
    <template #default>
      <VisuallyHidden>
        <DialogTitle>{{ __('Settings') }}</DialogTitle>
        <DialogDescription>
          {{ __('Manage your profile and this workspace') }}
        </DialogDescription>
      </VisuallyHidden>
      <!-- Below md the two panes do not fit side by side (the nav column alone
           is 224px of a 360px phone), so the dialog shows one at a time: the
           nav list first, then the chosen page behind a back button. From md
           up both are always visible and `mobilePane` is inert. -->
      <div class="flex h-[calc(100vh_-_8rem)] bg-surface-gray-1">
        <div
          class="flex-col m-1 rounded-l-[var(--v-radius-card)] w-full md:w-56 shrink-0 bg-surface-gray-1 overflow-y-auto"
          :class="mobilePane === 'page' ? 'hidden md:flex' : 'flex'"
        >
          <template v-for="(tab, i) in tabs" :key="tab.label">
            <div v-if="!tab.hideLabel && i != 0" class="mx-1 mb-0.5 mt-[5px]" />
            <div
              v-if="!tab.hideLabel"
              class="h-7.5 px-2 py-[7px] my-[3px] flex cursor-pointer gap-1.5 text-xs-medium text-ink-gray-5 transition-all duration-300 ease-in-out sticky top-0 z-10 bg-surface-gray-1"
            >
              <span>{{ __(tab.label) }}</span>
            </div>
            <nav class="space-y-[3px] px-1">
              <SidebarItem
                v-for="item in tab.items"
                :key="item.label"
                :label="__(item.label)"
                :active="activeTab?.label == item.label"
                class="w-full"
                :class="
                  activeTab?.label != item.label && 'hover:!bg-surface-gray-3'
                "
                @click="openPage(item.label)"
              >
                <template #prefix>
                  <Icon :icon="item.icon" class="size-4 text-ink-gray-7" />
                </template>
              </SidebarItem>
            </nav>
          </template>
        </div>
        <div
          class="flex-col flex-1 overflow-y-auto bg-surface-elevation-2"
          :class="mobilePane === 'nav' ? 'hidden md:flex' : 'flex'"
        >
          <div
            class="flex items-center gap-1 border-b border-[var(--v-shell-hairline)] px-2 py-2 md:hidden"
          >
            <Button
              variant="ghost"
              :label="__('Settings')"
              @click="mobilePane = 'nav'"
            >
              <template #prefix>
                <PhCaretLeft class="size-4" />
              </template>
            </Button>
          </div>
          <component :is="activeTab.component" v-if="activeTab" />
        </div>
      </div>
    </template>
  </Dialog>
</template>
<script setup>
import {
  PhCaretLeft,
  PhSquaresFour as LucideLayoutDashboard,
} from '@phosphor-icons/vue'
import { PhNetwork as LucideNetwork } from '@phosphor-icons/vue'
import { PhTarget as LucideTarget } from '@phosphor-icons/vue'
import { PhFlowArrow as LucideWorkflow } from '@phosphor-icons/vue'
import { PhSparkle as LucideSparkles } from '@phosphor-icons/vue'
import { PhBookOpenText as LucideBookOpenText } from '@phosphor-icons/vue'
// Phosphor has no envelope+checkmark combo glyph, but Report Digests is
// just "email, periodically" — the checkmark was decorative, not load-
// bearing meaning — so the plain envelope family already used for every
// other mail surface in the app (EmailTemplateIcon, Email2Icon) reads fine
// here too, and drops the Lucide weight mismatch on a Settings-tab icon,
// one of the two screens a client will look at closely.
import { PhEnvelopeSimple as LucideMailCheck } from '@phosphor-icons/vue'
import { PhMonitor as MonitorCogIcon } from '@phosphor-icons/vue'
import { PhCursorText as LucideTextCursorInput } from '@phosphor-icons/vue'
import SlidersIcon from '@/components/Icons/SlidersIcon.vue'
import SparkleIcon from '@/components/Icons/SparkleIcon.vue'
import CalendarIcon from '@/components/Icons/CalendarIcon.vue'
import WhatsAppIcon from '@/components/Icons/WhatsAppIcon.vue'
import ERPNextIcon from '@/components/Icons/ERPNextIcon.vue'
import PhoneIcon from '@/components/Icons/PhoneIcon.vue'
import Email2Icon from '@/components/Icons/Email2Icon.vue'
import EmailTemplateIcon from '@/components/Icons/EmailTemplateIcon.vue'
import SettingsIcon from '@/components/Icons/SettingsIcon.vue'
import SettingsIcon2 from '@/components/Icons/SettingsIcon2.vue'
import Users from '@/components/Settings/Users.vue'
import Hierarchy from '@/components/Settings/Hierarchy/Hierarchy.vue'
import Quotas from '@/components/Settings/Quotas.vue'
import AccessControl from '@/components/Settings/AccessControl.vue'
import AutomationRules from '@/components/Settings/AutomationRules.vue'
import AssistantSettings from '@/components/Settings/AssistantSettings.vue'
import KnowledgeSettings from '@/components/Settings/KnowledgeSettings.vue'
import ReportDigests from '@/components/Settings/ReportDigests.vue'
import InviteUserPage from '@/components/Settings/InviteUserPage.vue'
import ProfilePage from '@/components/Settings/Profile/ProfilePage.vue'
import PreferencesSettings from '@/components/Settings/PreferencesSettings.vue'
import WhatsAppSettings from '@/components/Settings/WhatsAppSettings.vue'
import ERPNextSettings from '@/components/Settings/ERPNextSettings.vue'
import AcumaticaSettings from '@/components/Settings/AcumaticaSettings.vue'
import LeadSyncSourcePage from '@/components/Settings/LeadSyncing/LeadSyncSourcePage.vue'
import DefaultsSettings from '@/components/Settings/DefaultsSettings.vue'
import BrandSettings from '@/components/Settings/BrandSettings.vue'
import CalendarSettings from '@/components/Settings/CalendarSettings.vue'
import HomeActions from '@/components/Settings/HomeActions.vue'
import FormsSettings from '@/components/Settings/Forms/FormsSettings.vue'
import GeneralSettings from '@/components/Settings/GeneralSettings.vue'
import DashboardSettings from '@/components/Settings/DashboardSettings.vue'
import EmailTemplatePage from '@/components/Settings/EmailTemplate/EmailTemplatePage.vue'
import TelephonyPage from '@/components/Settings/Telephony/TelephonyPage.vue'
import EmailConfig from '@/components/Settings/EmailConfig.vue'
import Icon from '@/components/Icon.vue'
import { DialogTitle, DialogDescription, VisuallyHidden } from 'reka-ui'
import { usersStore } from '@/stores/users'
import { accessStore } from '@/stores/access'
import {
  showSettings,
  activeSettingsPage,
  disableSettingModalOutsideClick,
} from '@/composables/settings'
import { isWhatsappInstalled } from '@/composables/whatsapp'
import { leadSyncingEnabled } from '@/composables/leadSyncing'
import { Dialog, Avatar, SidebarItem, Button } from 'frappe-ui'
import { ref, markRaw, computed, watch, h } from 'vue'
import AssignmentRulePage from './AssignmentRules/AssignmentRulePage.vue'
import { PhShieldCheck as ShieldCheck } from '@phosphor-icons/vue'
import { PhLockKey as LockKey } from '@phosphor-icons/vue'
import SlaConfig from './Sla/SlaConfig.vue'

const { isManager, isAdmin, getUser } = usersStore()
const { canSee } = accessStore()

const user = computed(() => getUser() || {})

const tabs = computed(() => {
  let _tabs = [
    {
      label: __('User Configuration'),
      items: [
        {
          label: __('Profile'),
          key: 'settings.profile',
          icon: () =>
            h(Avatar, {
              size: 'xs',
              label: user.value.full_name,
              image: user.value.user_image,
            }),
          component: markRaw(ProfilePage),
        },
        {
          label: __('Preferences'),
          key: 'settings.preferences',
          icon: SlidersIcon,
          component: markRaw(PreferencesSettings),
        },
      ],
    },
    {
      label: __('System Configuration'),
      items: [
        {
          label: __('General'),
          key: 'settings.general',
          component: markRaw(GeneralSettings),
          icon: SettingsIcon,
        },
        {
          label: __('Dashboard'),
          key: 'settings.dashboard',
          component: markRaw(DashboardSettings),
          icon: LucideLayoutDashboard,
        },
        {
          label: __('Defaults'),
          key: 'settings.defaults',
          component: markRaw(DefaultsSettings),
          icon: MonitorCogIcon,
          // System Settings is a System Manager doctype; a Sales Manager
          // opening this pane got a blank page and two 403s
          condition: () => isAdmin(),
        },
        {
          label: __('Brand'),
          key: 'settings.brand',
          icon: SparkleIcon,
          component: markRaw(BrandSettings),
        },
        {
          label: __('Calendar'),
          key: 'settings.calendar',
          icon: CalendarIcon,
          component: markRaw(CalendarSettings),
        },
      ],
      condition: () => isManager(),
    },
    {
      label: __('User Management'),
      items: [
        {
          label: __('Users'),
          key: 'settings.users',
          icon: 'lucide-user',
          component: markRaw(Users),
          condition: () => isManager(),
        },
        {
          label: __('Invite User'),
          key: 'settings.invite_user',
          icon: 'lucide-user-plus',
          component: markRaw(InviteUserPage),
          condition: () => isManager(),
        },
        {
          label: __('Sales Hierarchy'),
          key: 'settings.sales_hierarchy',
          icon: LucideNetwork,
          component: markRaw(Hierarchy),
          condition: () => isManager(),
        },
        {
          label: __('Sales Targets'),
          key: 'settings.sales_targets',
          icon: LucideTarget,
          component: markRaw(Quotas),
          condition: () => isManager(),
        },
        {
          label: __('Access Control'),
          key: 'settings.access_control',
          icon: markRaw(h(LockKey)),
          component: markRaw(AccessControl),
          condition: () => isManager(),
        },
      ],
      condition: () => isManager(),
    },
    {
      label: __('Email'),
      items: [
        {
          label: __('Accounts'),
          key: 'settings.email_accounts',
          icon: Email2Icon,
          component: markRaw(EmailConfig),
          // The site's outgoing and incoming mail accounts, which Frappe keeps
          // to System Manager. A Sales Manager was offered the pane and met a
          // 403 behind an empty list; their own address lives under
          // Profile > Email instead.
          condition: () => isAdmin(),
        },
        {
          label: __('Templates'),
          key: 'settings.email_templates',
          icon: EmailTemplateIcon,
          component: markRaw(EmailTemplatePage),
          // The Email group carries no group condition (Telephony's group
          // cannot have one — a rep configures their own agent number there),
          // so an ungated item here falls through to reps. Templates is an
          // authoring surface; a rep *uses* templates from the composer, not
          // from Settings. Core Email Template gives Desk User read and keeps
          // create, write and delete to System Manager, and install.py adds
          // custom fields rather than a DocPerm — so a Sales Manager could
          // open the pane but every toggle and every New came back "Failed to
          // update/create template". isAdmin() is the gate the server enforces.
          condition: () => isAdmin(),
        },
      ],
    },
    {
      label: __('Automation & Rules'),
      items: [
        {
          label: __('Assignment Rules'),
          key: 'settings.assignment_rules',
          icon: markRaw(h(SettingsIcon2, { class: 'rotate-90' })),
          component: markRaw(AssignmentRulePage),
          // Assignment Rule is a framework doctype readable by System Manager
          // only, so a Sales Manager opening this got the error state rather
          // than their team's routing rules. Same gate as Assistant and
          // Knowledge above.
          condition: () => isAdmin(),
        },
        {
          label: __('SLA Policies'),
          key: 'settings.sla_policies',
          icon: markRaw(h(ShieldCheck)),
          component: markRaw(SlaConfig),
        },
        {
          label: __('Automation Rules'),
          key: 'settings.automation_rules',
          icon: markRaw(h(LucideWorkflow)),
          component: markRaw(AutomationRules),
        },
        {
          label: __('Assistant'),
          key: 'settings.assistant',
          icon: markRaw(h(LucideSparkles)),
          component: markRaw(AssistantSettings),
          // CRM Agent Settings grants read and write to System Manager only,
          // so showing this to a Sales Manager would be a pane that errors on
          // load. isManager() includes them; isAdmin() is the right gate.
          condition: () => isAdmin(),
        },
        {
          label: __('Knowledge'),
          key: 'settings.knowledge',
          icon: markRaw(h(LucideBookOpenText)),
          component: markRaw(KnowledgeSettings),
          // Writes are System Manager only; reads are open, but a page that
          // is all disabled controls is not worth showing a Sales Manager.
          condition: () => isAdmin(),
        },
        {
          label: __('Report Digests'),
          key: 'settings.report_digests',
          icon: markRaw(h(LucideMailCheck)),
          component: markRaw(ReportDigests),
        },
        {
          label: __('Forms'),
          key: 'settings.forms',
          component: markRaw(FormsSettings),
          icon: markRaw(LucideTextCursorInput),
        },
      ],
      condition: () => isManager(),
    },
    {
      label: __('Customization'),
      items: [
        {
          label: __('Home Actions'),
          key: 'settings.home_actions',
          component: markRaw(HomeActions),
          icon: 'lucide-house',
        },
      ],
      condition: () => isManager(),
    },
    {
      label: __('Integrations', null, 'FCRM'),
      items: [
        {
          label: __('Telephony'),
          key: 'settings.telephony',
          icon: PhoneIcon,
          component: markRaw(TelephonyPage),
        },
        {
          label: __('WhatsApp'),
          key: 'settings.whatsapp',
          icon: WhatsAppIcon,
          component: markRaw(WhatsAppSettings),
          condition: () => isWhatsappInstalled.value && isManager(),
        },
        {
          label: __('SIMERP'),
          key: 'settings.simerp',
          icon: ERPNextIcon,
          component: markRaw(ERPNextSettings),
          condition: () => isManager(),
        },
        {
          label: __('Acumatica'),
          key: 'settings.acumatica',
          icon: ERPNextIcon,
          component: markRaw(AcumaticaSettings),
          condition: () => isManager(),
        },
        {
          label: __('Lead Syncing'),
          key: 'settings.lead_syncing',
          icon: 'lucide-refresh-cw',
          component: markRaw(LeadSyncSourcePage),
          condition: () => leadSyncingEnabled.value && isManager(),
        },
      ],
    },
  ]

  return (
    _tabs
      .filter((tab) => {
        if (tab.condition && !tab.condition()) return false
        if (tab.items) {
          tab.items = tab.items.filter((item) => {
            // canSee only ever narrows: an item still has to pass the role
            // condition it already carried. See @/utils/surfaces.
            if (item.key && !canSee(item.key)) return false
            if (item.condition && !item.condition()) return false
            return true
          })
        }
        return true
      })
      // Drop groups left with no items — a heading for an empty category
      // confuses the navigation and contradicts the intent of per-item gates.
      .filter((tab) => !tab.items || tab.items.length > 0)
  )
})

// Optional chaining, not a bare index: with hiding available, a manager can
// have every item in the first surviving group hidden from them (or, in the
// limit, every item in every group), leaving `tabs.value` with nothing to
// point at. `activeTab` then stays undefined, which the template already
// treats as "no page open" (`v-if="activeTab"`).
const activeTab = ref(tabs.value[0]?.items?.[0])

function setActiveTab(tabName) {
  activeTab.value =
    (tabName &&
      tabs.value
        .map((tab) => tab.items)
        .flat()
        .find((tab) => tab.label === tabName)) ||
    tabs.value[0]?.items?.[0]
}

watch(activeSettingsPage, (activePage) => setActiveTab(activePage))

// Which pane a phone shows. A deep link (`activeSettingsPage` set before the
// dialog opens, e.g. the Invite User row) lands on the page; a plain open
// lands on the list.
const mobilePane = ref('nav')

function openPage(label) {
  activeSettingsPage.value = label
  mobilePane.value = 'page'
}

watch(showSettings, (open) => {
  if (open) mobilePane.value = activeSettingsPage.value ? 'page' : 'nav'
})
</script>
