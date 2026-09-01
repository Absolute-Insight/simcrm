<template>
  <svg
    width="64"
    height="64"
    viewBox="0 0 64 64"
    fill="none"
    role="img"
    :aria-hidden="decorative || undefined"
    xmlns="http://www.w3.org/2000/svg"
  >
    <title v-if="!decorative">Vectora</title>
    <defs>
      <linearGradient
        :id="gradientId"
        x1="8"
        y1="52"
        x2="58"
        y2="10"
        gradientUnits="userSpaceOnUse"
      >
        <stop offset="0" stop-color="#4aa3bd" />
        <stop offset="0.45" stop-color="#2f6d95" />
        <stop offset="1" stop-color="#1e4a6d" />
      </linearGradient>
    </defs>
    <!-- The mark is the Vectora check, vectorised from the brand artwork's
         alpha channel (500x500 render -> 1582-point contour -> 44 points after
         Douglas-Peucker at eps=1.0 -> closed Catmull-Rom beziers). Filled, not
         stroked: the shape has a varying width the old two-segment stroke
         could not express.

         The gradient is sampled from the flat lockup but held in a mid
         luminance band on purpose -- the artwork's deepest navy (#152b44)
         is invisible against the dark sidebar (#171922). -->
    <path
      d="M26.95 59.56 C26.23 59.72 25.45 59.67 24.86 59.62 C24.27 59.57 23.92 59.46 23.41 59.26 C22.91 59.07 22.38 58.85 21.81 58.47 C21.24 58.09 20.77 57.95 19.99 56.98 C19.20 56.01 18.18 54.60 17.10 52.64 C16.02 50.68 14.62 47.36 13.51 45.24 C12.40 43.13 11.25 41.17 10.44 39.94 C9.62 38.71 9.25 38.45 8.60 37.85 C7.95 37.25 7.20 36.72 6.53 36.36 C5.87 36.00 5.29 35.86 4.60 35.71 C3.92 35.55 2.85 35.99 2.42 35.44 C1.99 34.88 1.69 33.24 2.00 32.38 C2.31 31.53 3.30 30.94 4.30 30.29 C5.30 29.64 6.72 28.86 7.98 28.48 C9.24 28.09 10.69 27.97 11.84 28.00 C12.99 28.02 13.93 28.28 14.89 28.62 C15.86 28.97 16.76 29.42 17.63 30.08 C18.49 30.73 19.37 31.65 20.08 32.54 C20.79 33.44 21.26 34.21 21.87 35.44 C22.47 36.67 23.32 39.13 23.71 39.94 C24.10 40.75 24.05 40.23 24.22 40.27 C24.38 40.32 24.15 41.41 24.70 40.21 C25.26 39.00 26.38 35.59 27.55 33.03 C28.72 30.46 30.31 27.21 31.70 24.83 C33.10 22.44 34.55 20.47 35.92 18.72 C37.30 16.97 38.90 15.40 39.97 14.32 C41.05 13.24 41.42 12.98 42.39 12.23 C43.35 11.49 44.42 10.66 45.76 9.85 C47.10 9.05 48.92 8.09 50.42 7.41 C51.92 6.73 53.37 6.24 54.77 5.79 C56.16 5.34 57.58 4.92 58.78 4.68 C59.99 4.45 61.53 3.86 62.00 4.38 C62.47 4.90 62.17 6.90 61.60 7.78 C61.04 8.67 59.86 8.69 58.62 9.68 C57.39 10.67 55.38 12.52 54.17 13.73 C52.97 14.94 52.46 15.53 51.37 16.95 C50.28 18.37 48.82 20.41 47.64 22.25 C46.45 24.10 45.25 26.25 44.28 28.04 C43.31 29.84 43.73 28.66 41.84 33.03 C39.95 37.39 34.62 50.39 32.95 54.25 C31.27 58.11 32.20 55.60 31.79 56.18 C31.38 56.75 30.92 57.27 30.49 57.69 C30.06 58.11 29.79 58.38 29.20 58.69 C28.61 59.00 27.68 59.40 26.95 59.56 Z"
      :fill="`url(#${gradientId})`"
    />
  </svg>
</template>

<script setup>
import { useId } from 'vue'

defineProps({
  // Set where the product is already named in text next to the mark, so a
  // screen reader does not announce "Vectora Vectora".
  decorative: { type: Boolean, default: false },
})

// SVG gradient ids are document-global: two instances of a fixed id make the
// second mark reference the first one's (possibly unmounted) gradient node.
const gradientId = `vectora-mark-${useId()}`
</script>
