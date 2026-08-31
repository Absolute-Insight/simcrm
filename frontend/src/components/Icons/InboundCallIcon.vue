<template>
  <PhPhoneIncoming v-bind="intrinsicProps('InboundCallIcon')" />
</template>

<script setup>
import { PhPhoneIncoming } from '@phosphor-icons/vue'
import { intrinsicProps } from './_phosphor'
</script>
