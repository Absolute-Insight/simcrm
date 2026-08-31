<template>
  <PhGauge v-bind="intrinsicProps('PlaybackSpeedIcon')" />
</template>

<script setup>
import { PhGauge } from '@phosphor-icons/vue'
import { intrinsicProps } from './_phosphor'
</script>
