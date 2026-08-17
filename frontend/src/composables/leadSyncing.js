import { createResource } from 'frappe-ui'
import { ref } from 'vue'

/* Off unless the site opts in. The Facebook connector drops leads past the
   first Graph API page and still advances its watermark, so the settings tab
   is hidden rather than left as a switch that loses data when flipped.
   See crm/lead_syncing/__init__.py. */
export const leadSyncingEnabled = ref(false)

createResource({
  url: 'crm.lead_syncing.is_lead_syncing_enabled',
  cache: 'Is Lead Syncing Enabled',
  auto: true,
  onSuccess: (data) => {
    leadSyncingEnabled.value = Boolean(data)
  },
})
