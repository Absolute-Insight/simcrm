import { createResource } from 'frappe-ui'
import { ref } from 'vue'
import { globalStore } from '@/stores/global'
import { reportActionError } from '@/utils/reportActionError'

const isDemoDataCreated = ref(window.demo_data_created || false)

const _clearDemoData = createResource({
  url: 'crm.demo.api.clear_demo_data',
  onSuccess() {
    isDemoDataCreated.value = false
    window.location.reload()
  },
  /* The dialog closes on click and success reloads the page, so a rejection
     with no handler looked exactly like a slow success: the demo data stayed,
     and the only evidence was a console line. */
  onError(error) {
    reportActionError(error, __('Could not clear the demo data.'))
  },
})

export function useDemoData() {
  const { $dialog } = globalStore()

  const clearDemoData = () => {
    $dialog({
      title: __('Clear Demo Data'),
      message: __(
        'Are you sure you want to clear demo data? This action cannot be undone.',
      ),
      actions: [
        {
          label: __('Confirm'),
          theme: 'red',
          variant: 'solid',
          onClick: (close) => {
            _clearDemoData.submit()
            close()
          },
        },
      ],
    })
  }

  return {
    isDemoDataCreated,
    clearDemoData,
  }
}
