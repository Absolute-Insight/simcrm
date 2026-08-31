<template>
  <PhCamera v-bind="intrinsicProps('CameraIcon')" />
</template>

<script setup>
import { PhCamera } from '@phosphor-icons/vue'
import { intrinsicProps } from './_phosphor'
</script>
