<template>
  <PhHeart v-bind="intrinsicProps('HeartIcon')" />
</template>

<script setup>
import { PhHeart } from '@phosphor-icons/vue'
import { intrinsicProps } from './_phosphor'
</script>
