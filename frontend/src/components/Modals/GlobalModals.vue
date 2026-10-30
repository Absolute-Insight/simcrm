<template>
  <CreateDocumentModal
    v-if="showCreateDocumentModal"
    v-model="showCreateDocumentModal"
    :doctype="createDocumentDoctype"
    :data="createDocumentData"
    @callback="(data) => createDocumentCallback(data)"
  />
  <QuickEntryModal
    v-if="showQuickEntryModal"
    v-model="showQuickEntryModal"
    v-bind="quickEntryProps"
  />
  <ChangePasswordModal
    v-if="showChangePasswordModal"
    v-model="showChangePasswordModal"
  />
  <AboutModal v-model="showAboutModal" />
  <HelpCenterModal v-if="helpCenterVisible" />
  <FieldLayoutDialogContainer />
  <LeadModal v-if="showCreateLeadModal" v-model="showCreateLeadModal" />
  <DealModal v-if="showCreateDealModal" v-model="showCreateDealModal" />
  <CommandPalette />
</template>
<script setup>
import { defineAsyncComponent } from 'vue'
import CommandPalette from '@/components/CommandPalette/CommandPalette.vue'
import FieldLayoutDialogContainer from '@/components/Modals/FieldLayoutDialogContainer.vue'
import ChangePasswordModal from '@/components/Modals/ChangePasswordModal.vue'
import CreateDocumentModal from '@/components/Modals/CreateDocumentModal.vue'
import QuickEntryModal from '@/components/Modals/QuickEntryModal.vue'
import AboutModal from '@/components/Modals/AboutModal.vue'
import HelpCenterModal from '@/components/Modals/HelpCenterModal.vue'
import { helpCenterVisible } from '@/stores/help'
import {
  showCreateDocumentModal,
  createDocumentDoctype,
  createDocumentData,
  createDocumentCallback,
} from '@/composables/document'
import {
  showQuickEntryModal,
  quickEntryProps,
  showAboutModal,
  showChangePasswordModal,
  showCreateLeadModal,
  showCreateDealModal,
} from '@/composables/modals'

const LeadModal = defineAsyncComponent(
  () => import('@/components/Modals/LeadModal.vue'),
)
const DealModal = defineAsyncComponent(
  () => import('@/components/Modals/DealModal.vue'),
)
</script>
