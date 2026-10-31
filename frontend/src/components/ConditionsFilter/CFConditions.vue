<template>
  <div
    class="rounded-6 border border-outline-gray-2 p-3 flex flex-col gap-4 w-full"
  >
    <template v-for="(condition, i) in conditions" :key="rowKey(condition, i)">
      <CFCondition
        v-if="Array.isArray(condition)"
        :condition="condition"
        :isChild="props.isChild"
        :itemIndex="i"
        :level="props.level + 1"
        :isGroup="isGroupCondition(condition[0])"
        :conjunction="getConjunction()"
        :disableAddCondition="props.disableAddCondition"
        :doctype="props.doctype"
        @remove="removeCondition(condition)"
        @unGroupConditions="unGroupConditions(condition)"
        @toggleConjunction="toggleConjunction"
        @turnIntoGroup="turnIntoGroup(condition)"
      />
    </template>
    <div v-if="props.isChild" class="flex">
      <Dropdown v-slot="{ open }" :options="dropdownOptions">
        <Button
          :disabled="props.disableAddCondition"
          :label="__('Add Condition')"
          icon-left="lucide-plus"
          :icon-right="open ? 'lucide-chevron-up' : 'lucide-chevron-down'"
        />
      </Dropdown>
    </div>
  </div>
</template>

<script setup>
import CFCondition from './CFCondition.vue'
import { filterableFields } from './filterableFields'
import { Button, Dropdown } from 'frappe-ui'
import { computed, reactive, toRaw, watch } from 'vue'

const props = defineProps({
  conditions: { type: Array, required: true },
  isChild: { type: Boolean, default: false },
  level: { type: Number, default: 0 },
  disableAddCondition: { type: Boolean, default: false },
  doctype: { type: String, required: true },
})

// Follows the prop rather than wrapping it once at setup, so the instance
// always edits the array it is showing.
const conditions = computed(() => reactive(props.conditions))

// A condition array has no field to key it by (`condition.field` was always
// undefined), so rows were reused by position: after Remove, Turn into a
// Group or Ungroup a row went on showing and editing the condition that used
// to sit there. Key each array by identity instead.
const rowKeys = new WeakMap()
let lastRowKey = 0
function rowKey(condition, i) {
  if (typeof condition !== 'object' || !condition) return `conjunction-${i}`
  condition = toRaw(condition)
  if (!rowKeys.has(condition)) rowKeys.set(condition, ++lastRowKey)
  return rowKeys.get(condition)
}

const getConjunction = () => {
  let conjunction = 'and'
  conditions.value.forEach((condition) => {
    if (typeof condition == 'string') {
      conjunction = condition
    }
  })
  return conjunction
}

const turnIntoGroup = (condition) => {
  conditions.value.splice(conditions.value.indexOf(condition), 1, [condition])
}

const isGroupCondition = (condition) => {
  return Array.isArray(condition)
}

const dropdownOptions = computed(() => {
  const options = [
    {
      label: __('Add Condition'),
      onClick: () => {
        const conjunction = getConjunction()
        conditions.value.push(conjunction, ['', '', ''])
      },
    },
  ]
  if (props.level < 3) {
    options.push({
      label: __('Add Condition Group'),
      onClick: () => {
        const conjunction = getConjunction()
        conditions.value.push(conjunction, [[]])
      },
    })
  }
  return options
})

function removeCondition(condition) {
  const conditionIndex = conditions.value.indexOf(condition)
  if (conditionIndex == 0) {
    conditions.value.splice(conditionIndex, 2)
  } else {
    conditions.value.splice(conditionIndex - 1, 2)
  }
}

function unGroupConditions(condition) {
  const conjunction = getConjunction()
  const newConditions = condition.map((c) => {
    if (typeof c == 'string') {
      return conjunction
    }
    return c
  })

  const index = conditions.value.indexOf(condition)
  if (index !== -1) {
    conditions.value.splice(index, 1, ...newConditions)
  }
}

function toggleConjunction(conjunction) {
  for (let i = 0; i < conditions.value.length; i++) {
    if (typeof conditions.value[i] == 'string') {
      conditions.value[i] = conjunction == 'and' ? 'or' : 'and'
    }
  }
}

watch(
  () => props.doctype,
  (doctype) => filterableFields.submit({ doctype }),
  { immediate: true },
)
</script>
