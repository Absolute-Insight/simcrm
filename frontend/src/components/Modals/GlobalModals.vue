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
  <!-- Mounted while closed, like AboutModal: its on-open watchers reset the
       Mentor pane and pick the phone pane on the false -> true change, which a
       modal created already open never sees. -->
  <HelpCenterModal />
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
