<template>
  <PhCircleNotch
    v-bind="intrinsicProps('LoadingIndicator')"
    class="animate-spin"
  />
</template>

<script setup>
import { PhCircleNotch } from '@phosphor-icons/vue'
import { intrinsicProps } from './_phosphor'
</script>
