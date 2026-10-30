import { ref } from 'vue'

export const showQuickEntryModal = ref(false)
export const quickEntryProps = ref({})

export const showAboutModal = ref(false)

export const showChangePasswordModal = ref(false)

// The command palette creates from any page. A broadcast to the Leads page would
// not do: useBroadcast replays what is left in storage on the next mount, so the
// modal would open again the next time the rep visited Leads.
export const showCreateLeadModal = ref(false)
export const showCreateDealModal = ref(false)
