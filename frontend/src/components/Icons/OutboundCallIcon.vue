<template>
  <PhPhoneOutgoing v-bind="intrinsicProps('OutboundCallIcon')" />
</template>

<script setup>
import { PhPhoneOutgoing } from '@phosphor-icons/vue'
import { intrinsicProps } from './_phosphor'
</script>
