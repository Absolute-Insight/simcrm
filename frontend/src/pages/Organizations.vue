<template>
  <LayoutHeader>
    <template #left-header>
      <ViewBreadcrumbs v-model="viewControls" routeName="Organizations" />
    </template>
    <template #right-header>
      <!-- MBP's reps identify an account by its Acumatica code (C-IMP003E),
           which is what both screens of their old app searched on. -->
      <div class="flex items-center gap-1">
        <FormControl
          v-model="codeQuery"
          type="text"
          size="sm"
          :placeholder="__('Customer code')"
          class="w-36"
          @keydown.enter="findByCode"
        />
        <Button
          variant="subtle"
          :label="__('Find')"
          :loading="findingCode"
          @click="findByCode"
        />
      </div>
      <CustomActions
        v-if="organizationsListView?.customListActions"
        :actions="organizationsListView.customListActions"
      />
      <Button
        variant="solid"
        :label="__('Create')"
        iconLeft="lucide-plus"
        @click="showOrganizationModal = true"
      />
    </template>
  </LayoutHeader>
  <ViewControls
    ref="viewControls"
    v-model="organizations"
    v-model:loadMore="loadMore"
    v-model:resizeColumn="triggerResize"
    v-model:updatedPageCount="updatedPageCount"
    doctype="CRM Organization"
  />
  <!-- Loading and failure had no branch at all: the chain went straight from
       "has data" to EmptyState, so a list still fetching and a list whose
       fetch failed both rendered nothing. A blank page reads as an empty CRM,
       not as a slow or a broken one. -->
  <ErrorState
    v-if="organizations.error"
    :error="organizations.error"
    :title="__('Could not load organizations')"
    :retry="() => organizations.reload()"
  />
  <SkeletonTable
    v-else-if="!organizations.data"
    class="px-5 pt-3"
    :columns="columns.length || 6"
    :rows="10"
    :label="__('Loading organizations')"
  />
  <OrganizationsListView
    v-else-if="organizations.data && rows.length"
    ref="organizationsListView"
    v-model="organizations.data.page_length_count"
    v-model:list="organizations"
    :rows="rows"
    :columns="columns"
    :options="{
      showTooltip: false,
      resizeColumn: true,
      rowCount: organizations.data.row_count,
      totalCount: organizations.data.total_count,
    }"
    @loadMore="() => loadMore++"
    @columnWidthUpdated="() => triggerResize++"
    @updatePageCount="(count) => (updatedPageCount = count)"
    @applyFilter="(data) => viewControls.applyFilter(data)"
    @applyLikeFilter="(data) => viewControls.applyLikeFilter(data)"
    @likeDoc="(data) => viewControls.likeDoc(data)"
    @selectionsChanged="
      (selections) => viewControls.updateSelections(selections)
    "
  />
  <EmptyState
    v-else-if="organizations.data && !rows.length"
    name="Organizations"
    :icon="OrganizationsIcon"
  />
  <OrganizationModal
    v-if="showOrganizationModal"
    v-model="showOrganizationModal"
  />
</template>
<script setup>
import ViewBreadcrumbs from '@/components/ViewBreadcrumbs.vue'
import CustomActions from '@/components/CustomActions.vue'
import OrganizationsIcon from '@/components/Icons/OrganizationsIcon.vue'
import LayoutHeader from '@/components/LayoutHeader.vue'
import OrganizationModal from '@/components/Modals/OrganizationModal.vue'
import OrganizationsListView from '@/components/ListViews/OrganizationsListView.vue'
import ViewControls from '@/components/ViewControls.vue'
import { getMeta } from '@/stores/meta'
import { formatDate, website } from '@/utils'
import { timestampCell } from '@/composables/useTimelinePreferences'
import { ref, computed } from 'vue'
import { useRouter } from 'vue-router'
import { call, toast } from 'frappe-ui'
import EmptyState from '../components/ListViews/EmptyState.vue'
import { renderFieldLayoutDialog } from '@/utils/renderFieldLayoutDialog'

const { getFormattedPercent, getFormattedFloat, getFormattedCurrency } =
  getMeta('CRM Organization')

const router = useRouter()

const organizationsListView = ref(null)
const showOrganizationModal = ref(false)
const codeQuery = ref('')
const findingCode = ref(false)

// organizations data is loaded in the ViewControls component
const organizations = ref({})
const loadMore = ref(1)
const triggerResize = ref(1)
const updatedPageCount = ref(20)
const viewControls = ref(null)

const rows = computed(() => {
  if (
    !organizations.value?.data?.data ||
    !['list', 'group_by'].includes(organizations.value.data.view_type)
  )
    return []
  return organizations.value?.data.data.map((organization) => {
    let _rows = {}
    organizations.value?.data.rows.forEach((row) => {
      _rows[row] = organization[row]

      let fieldType = organizations.value?.data.columns?.find(
        (col) => (col.key || col.value) == row,
      )?.type

      if (
        fieldType &&
        ['Date', 'Datetime'].includes(fieldType) &&
        !['modified', 'creation'].includes(row)
      ) {
        _rows[row] = formatDate(
          organization[row],
          '',
          true,
          fieldType == 'Datetime',
        )
      }

      if (fieldType && fieldType == 'Currency') {
        _rows[row] = getFormattedCurrency(row, organization)
      }

      if (fieldType && fieldType == 'Float') {
        _rows[row] = getFormattedFloat(row, organization)
      }

      if (fieldType && fieldType == 'Percent') {
        _rows[row] = getFormattedPercent(row, organization)
      }

      if (row === 'organization_name') {
        _rows[row] = {
          label: organization.organization_name,
          logo: organization.organization_logo,
        }
      } else if (row === 'website') {
        _rows[row] = website(organization.website)
      } else if (['modified', 'creation'].includes(row)) {
        _rows[row] = timestampCell(organization[row])
      }
    })
    return _rows
  })
})

const columns = computed(() => {
  let _columns = organizations.value?.data?.columns || []

  // Set align right for last column
  if (_columns.length) {
    _columns = _columns.map((col, index) => {
      if (index === _columns.length - 1) {
        return { ...col, align: 'right' }
      }
      return col
    })
  }

  return _columns
})

async function findByCode() {
  if (!codeQuery.value.trim() || findingCode.value) return
  findingCode.value = true
  try {
    const matches = await call('crm.api.organization.find_by_code', {
      code: codeQuery.value,
    })
    if (!matches.length) {
      toast.warning(
        __('No organization has a code starting with {0}', [codeQuery.value]),
      )
      return
    }
    // One exact hit opens it; several ask which one. The search never touches
    // the list resource: a filter left pinned on the view outlives the search
    // that set it, and the rep has no way to tell it is there.
    const exact = matches.find(
      (r) =>
        r.acumatica_id.toLowerCase() === codeQuery.value.trim().toLowerCase(),
    )
    if (exact || matches.length === 1) {
      router.push({
        name: 'Organization',
        params: { organizationId: (exact || matches[0]).name },
      })
      return
    }
    const picked = await renderFieldLayoutDialog({
      title: __('Which organization?'),
      size: 'md',
      fields: [
        {
          fieldname: 'organization',
          fieldtype: 'Select',
          label: __('Organization'),
          options: matches.map((r) => ({
            label: `${r.acumatica_id} — ${r.name}`,
            value: r.name,
          })),
        },
      ],
      required: ['organization'],
      submitLabel: __('Open'),
      cancelLabel: __('Cancel'),
    })
    if (!picked?.organization) return
    router.push({
      name: 'Organization',
      params: { organizationId: picked.organization },
    })
  } catch (error) {
    // The missing-field case arrives here as a server message; it must be read, not hidden.
    toast.error(error?.messages?.[0] || __('Could not search by code'))
  } finally {
    findingCode.value = false
  }
}
</script>
