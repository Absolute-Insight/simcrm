import { call } from 'frappe-ui'
import { useRouter } from 'vue-router'
import { reportActionError } from '@/utils/reportActionError'

/**
 * The side panel's beforeFieldChange handler for an organization page.
 *
 * CRM Organization is named by its organization_name, so an edit to that field
 * is a rename of the record, not a save: saving it alone left the record under
 * its old name with a different name field. Every other field saves as usual.
 *
 * SidePanelLayout has already written the new value into the doc by the time
 * this runs. When the server refuses the rename -- the name is taken -- the old
 * one is put back: left there, the refused name went out with the next field
 * the rep edited, because a save sends everything that differs from the
 * server's copy, and that save failed too.
 *
 * @param {object} organization The page's CRM Organization document resource.
 * @param {string} organizationId The record's current name.
 */
export function useOrganizationFieldChange(organization, organizationId) {
  const router = useRouter()

  return function beforeFieldChange(data) {
    if (!Object.hasOwn(data ?? {}, 'organization_name')) {
      organization.save.submit()
      return
    }
    call('frappe.client.rename_doc', {
      doctype: 'CRM Organization',
      old_name: organizationId,
      new_name: data.organization_name,
    })
      .then(() => {
        router.push({
          name: 'Organization',
          params: { organizationId: data.organization_name },
        })
      })
      .catch((error) => {
        organization.doc.organization_name =
          organization.originalDoc?.organization_name
        reportActionError(error, __('Could not rename the organization.'))
      })
  }
}
