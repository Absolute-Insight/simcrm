import { createResource } from 'frappe-ui'
import { ref } from 'vue'

export const whatsappEnabled = ref(false)
export const isWhatsappInstalled = ref(false)
export const whatsappCanSend = ref(false)

createResource({
  url: 'crm.api.whatsapp.is_whatsapp_enabled',
  cache: 'Is Whatsapp Enabled',
  auto: true,
  onSuccess: (data) => {
    whatsappEnabled.value = Boolean(data)
  },
})

createResource({
  url: 'crm.api.whatsapp.can_send_whatsapp',
  cache: 'Can Send Whatsapp',
  auto: true,
  onSuccess: (data) => {
    whatsappCanSend.value = Boolean(data)
  },
})

createResource({
  url: 'crm.api.whatsapp.is_whatsapp_installed',
  cache: 'Is Whatsapp Installed',
  auto: true,
  onSuccess: (data) => {
    isWhatsappInstalled.value = Boolean(data)
  },
})
