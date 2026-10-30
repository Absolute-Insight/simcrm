import { call, dayjs, dayjsLocal, toast } from 'frappe-ui'
import { onBeforeUnmount, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import router from '@/router'
import { useDoctypeModal } from '@/composables/doctypeModal'
import { showCreateDealModal, showCreateLeadModal } from '@/composables/modals'
import { isMobileView, showSettings } from '@/composables/settings'
import {
  commandPaletteOpen,
  commandPaletteQuery,
  commandPaletteSearching,
  setCommandPaletteProvider,
} from '@/composables/useCommandPalette'
import { useNavLinks } from '@/composables/useNavLinks'
import ContactsIcon from '@/components/Icons/ContactsIcon.vue'
import DealsIcon from '@/components/Icons/DealsIcon.vue'
import LeadsIcon from '@/components/Icons/LeadsIcon.vue'
import OrganizationsIcon from '@/components/Icons/OrganizationsIcon.vue'
import PlannerIcon from '@/components/Icons/PlannerIcon.vue'
import TaskIcon from '@/components/Icons/TaskIcon.vue'
import { sessionStore } from '@/stores/session'
import { assistantVisible, toggleAssistant } from '@/stores/assistant'
import { prettyDate } from '@/utils'
import {
  addRecent,
  isDueItemVisible,
  isRecordVisible,
  recentNamesByDoctype,
  recordSubtitle,
  sortByRecency,
} from '@/utils/commandPalette'

const MIN_QUERY_LENGTH = 2
const SEARCH_DEBOUNCE_MS = 180

const RECENT_TYPES = {
  Lead: 'CRM Lead',
  Deal: 'CRM Deal',
  Contact: 'Contact',
  Organization: 'CRM Organization',
}

// Only the untyped list is ranked; a rank bypasses matching.
const GROUP_RANK = {
  Upcoming: 400,
  Recent: 300,
  'Go to': 250,
  Create: 200,
  Account: 150,
}

const RECORD_ICONS = {
  'CRM Lead': LeadsIcon,
  'CRM Deal': DealsIcon,
  Contact: ContactsIcon,
  'CRM Organization': OrganizationsIcon,
}

export function useCRMCommands() {
  const { user } = sessionStore()
  const { showModal } = useDoctypeModal()
  const context = {
    user,
    showModal,
    links: useNavLinks({ mobile: () => isMobileView.value }),
    state: createSearchState(),
  }
  setCommandPaletteProvider(() => buildCommands(context))
  installWatchers(context)
}

function createSearchState() {
  return {
    records: ref([]),
    recent: ref([]),
    upcoming: ref([]),
    error: ref(false),
    requestId: 0,
    timer: null,
  }
}

function visibleLinks(links) {
  return links.filter((link) => !link.condition || link.condition())
}

function buildCommands({ links, showModal, state }) {
  const visible = visibleLinks(links)
  const surfaces = new Set(visible.map((link) => link.to).filter(Boolean))
  const typed = Boolean(commandPaletteQuery.value.trim())
  const reachable = (record) => isRecordVisible(record, surfaces)

  const commands = [
    ...(typed ? [] : upcomingCommands(state.upcoming.value, surfaces)),
    ...state.recent.value
      .filter(reachable)
      .map((record) => recordCommand(record, 'Recent')),
    ...navigationCommands(visible),
    ...createCommands(surfaces, showModal),
    settingsCommand(),
    ...(state.error.value ? [searchErrorCommand()] : []),
    ...state.records.value
      .filter(reachable)
      .map((record) => recordCommand(record, 'Records')),
  ]
  if (typed) return commands
  return commands.map((command) => ({
    ...command,
    rank: GROUP_RANK[command.group] ?? 0,
  }))
}

function installWatchers(context) {
  const route = useRoute()
  watch(commandPaletteOpen, (open) => {
    if (open) fetchRecords(commandPaletteQuery.value, context)
  })
  watch(commandPaletteQuery, (query) => scheduleSearch(query, context))
  watch(route, () => rememberRoute(route, context.user), { immediate: true })
  onBeforeUnmount(() => clearTimeout(context.state.timer))
}

function scheduleSearch(query, context) {
  const { state } = context
  const term = query.trim()
  clearTimeout(state.timer)
  state.requestId++
  commandPaletteSearching.value = term.length >= MIN_QUERY_LENGTH
  if (!term) return fetchRecords('', context)
  if (term.length < MIN_QUERY_LENGTH) {
    state.records.value = []
    return
  }
  state.timer = setTimeout(
    () => fetchRecords(query, context),
    SEARCH_DEBOUNCE_MS,
  )
}

async function fetchRecords(query, context) {
  const { state, user } = context
  const request = ++state.requestId
  const recent = readRecent(user)
  try {
    const data = await call('crm.api.command_palette.search', {
      query,
      recent_names: JSON.stringify(recentNamesByDoctype(recent)),
    })
    if (request !== state.requestId) return
    commandPaletteSearching.value = false
    state.error.value = false
    state.records.value = data.matches || []
    state.recent.value = sortByRecency(data.recent || [], recent)
    state.upcoming.value = data.upcoming || []
  } catch (error) {
    if (request !== state.requestId) return
    commandPaletteSearching.value = false
    state.error.value = true
    state.records.value = []
    console.error('Command palette record search failed', error)
  }
}

function searchErrorCommand() {
  return {
    id: 'record-search-error',
    title: 'Record search is unavailable',
    subtitle: __('Try again shortly'),
    group: 'Records',
    icon: 'circle-alert',
    disabled: true,
    // A failed search has to stay visible whatever was typed.
    rank: 2000,
  }
}

function upcomingCommands(items, surfaces) {
  return items
    .filter((item) => isDueItemVisible(item, surfaces))
    .map((item) => ({
      id: `upcoming-${item.kind}-${item.name}`,
      title: item.title,
      translate: false,
      group: 'Upcoming',
      icon: item.kind === 'task' ? TaskIcon : PlannerIcon,
      subtitle: __(item.label),
      ...dueBadge(item),
      perform: () => router.push(itemRoute(item)),
    }))
}

function dueBadge(item) {
  if (item.when) return { badge: __(item.when) }
  const due = dayjsLocal(item.due)
  // An exact time, because prettyDate calls anything 24 to 36 hours off
  // "tomorrow", and in the first minute past due it would say "now overdue".
  if (dayjs().diff(due, 'second') < 60)
    return { badge: due.format('ddd HH:mm') }
  return {
    badge: __('{0} overdue', [prettyDate(item.due, true)]),
    badgeClass: 'text-ink-red-9',
  }
}

function itemRoute(item) {
  if (!item.route_name) return { name: item.route }
  return {
    name: item.route,
    params: { [`${item.route.toLowerCase()}Id`]: item.route_name },
  }
}

function navigationCommands(links) {
  return links.map((link) => ({
    id: `navigate-${link.key}`,
    title: link.label,
    group: 'Go to',
    icon: link.icon,
    // A page must not outrank a record that matches the same words.
    weight: 0.7,
    keywords: `go open ${link.label}`,
    perform: () =>
      link.action === 'assistant'
        ? openAssistant()
        : router.push({ name: link.to }),
  }))
}

function openAssistant() {
  if (!assistantVisible.value) toggleAssistant()
}

function createCommands(surfaces, showModal) {
  const commands = [
    {
      key: 'lead',
      title: 'Create Lead',
      surface: 'Leads',
      perform: () => (showCreateLeadModal.value = true),
    },
    {
      key: 'deal',
      title: 'Create Deal',
      surface: 'Deals',
      perform: () => (showCreateDealModal.value = true),
    },
    {
      key: 'task',
      title: 'Create Task',
      surface: 'Tasks',
      perform: () =>
        showModal({
          doctype: 'CRM Task',
          title: 'Task',
          callbacks: { afterInsert: () => toast.success(__('Task created')) },
        }),
    },
    {
      key: 'note',
      title: 'Create Note',
      surface: 'Notes',
      perform: () =>
        showModal({
          doctype: 'FCRM Note',
          title: 'Note',
          callbacks: { afterInsert: () => toast.success(__('Note created')) },
        }),
    },
  ]
  return commands
    .filter((command) => surfaces.has(command.surface))
    .map(({ key, title, perform }) => ({
      id: `create-${key}`,
      title,
      group: 'Create',
      icon: 'plus',
      keywords: `new add ${key}`,
      perform,
    }))
}

function settingsCommand() {
  return {
    id: 'settings',
    title: 'Settings',
    group: 'Account',
    icon: 'settings',
    keywords: 'configure preferences profile users',
    perform: () => (showSettings.value = true),
  }
}

function recordCommand(record, group) {
  return {
    id: `${group}-${record.doctype}-${record.name}`,
    title: record.title,
    // The server matched these on fields the title may not contain.
    keywords: record.keywords,
    translate: false,
    subtitle: recordSubtitle(record),
    group,
    icon:
      group === 'Recent'
        ? 'clock'
        : RECORD_ICONS[record.doctype] || 'file-text',
    perform: () =>
      router.push(itemRoute({ route: record.route, route_name: record.name })),
  }
}

function rememberRoute(route, user) {
  const doctype = RECENT_TYPES[route.name]
  const name = route.params[`${route.name?.toLowerCase()}Id`]
  if (!doctype || !name) return
  writeRecent(user, addRecent(readRecent(user), { doctype, name }))
}

function recentKey(user) {
  return `crm-command-palette-recent:${user || 'anonymous'}`
}

function readRecent(user) {
  try {
    const recent = JSON.parse(localStorage.getItem(recentKey(user)) || '[]')
    return Array.isArray(recent) ? recent : []
  } catch {
    return []
  }
}

function writeRecent(user, recent) {
  try {
    localStorage.setItem(recentKey(user), JSON.stringify(recent))
  } catch {
    // Storage is a convenience here: a full or blocked store only costs Recent.
  }
}
