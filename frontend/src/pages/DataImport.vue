<template>
  <DataImport
    :doctype="route.params.doctype"
    :importName="route.params.importName"
    :doctypeMap="doctypeMap"
  />
</template>

<script setup>
import { usePageMeta } from 'frappe-ui'
import { DataImport } from '@framework/ui/components/DataImport'
import { useRoute } from 'vue-router'

const route = useRoute()

const doctypeMap = {
  'CRM Lead': {
    title: __('Leads'),
    listRoute: '/crm/leads',
    pageRoute: `/crm/leads/docname`,
  },
  'CRM Deal': {
    title: __('Deals'),
    listRoute: '/crm/deals',
    pageRoute: `/crm/deals/docname`,
  },
  Contact: {
    title: __('Contacts'),
    listRoute: '/crm/contacts',
    pageRoute: `/crm/contacts/docname`,
  },
  'CRM Task': {
    title: __('Tasks'),
    listRoute: '/crm/tasks',
  },
  'CRM Organization': {
    title: __('Organizations'),
    listRoute: '/crm/organizations',
    pageRoute: `/crm/organizations/docname`,
  },
  'CRM Call Log': {
    title: __('Call Log'),
    listRoute: '/crm/call-logs',
  },
}

usePageMeta(() => {
  return {
    title: __('Data Import'),
  }
})
</script>
