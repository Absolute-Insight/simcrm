<template>
  <div
    class="flex gap-2"
    :class="[
      {
        'items-center': !props.isGroup,
      },
    ]"
  >
    <div
      class="flex gap-2 w-full"
      :class="[
        {
          'items-center justify-between': !props.isGroup,
        },
      ]"
    >
      <div :class="'text-end text-base text-ink-gray-5'">
        <div v-if="props.itemIndex == 0" class="min-w-[66px] text-start">
          {{ __('Where') }}
        </div>
        <div v-else class="min-w-[66px] flex items-start">
          <Button
            variant="subtle"
            class="w-max"
            icon-right="lucide-refresh-cw"
            :disabled="props.itemIndex > 2"
            :label="conjunction"
            @click="toggleConjunction"
          />
        </div>
      </div>
      <div v-if="!props.isGroup" class="flex items-center gap-2 w-full">
        <div id="fieldname" class="w-full">
          <Combobox
            trigger="button"
            :options="filterableFields.data || []"
            :model-value="condition[0]"
            :placeholder="__('Field')"
            @update:selected-option="updateField"
          />
        </div>
        <div id="operator">
          <FormControl
            v-if="!condition[0]"
            disabled
            type="text"
            :placeholder="__('Operator')"
            class="w-[100px]"
          />
          <FormControl
            v-else
            v-model="condition[1]"
            :disabled="!condition[0]"
            type="select"
            :options="getOperators()"
            class="w-max min-w-[100px] text-ink-gray-8"
            @update:modelValue="updateOperator"
          />
        </div>
        <div id="value" class="w-full">
          <FormControl
            v-if="!condition[0]"
            disabled
            type="text"
            :placeholder="__('Condition')"
            class="w-full"
          />
          <component
            :is="getValueControl()"
            v-else
            v-model="condition[2]"
            :placeholder="__('Condition')"
            @change="updateValue"
          />
        </div>
      </div>
      <CFConditions
        v-if="props.isGroup && !(props.level == 2 || props.level == 4)"
        :conditions="condition"
        :isChild="true"
        :level="props.level"
        :disableAddCondition="props.disableAddCondition"
        :doctype="props.doctype"
      />
      <Button
        v-if="props.isGroup && (props.level == 2 || props.level == 4)"
        variant="outline"
        :label="__('Open Nested Conditions')"
        @click="show = true"
      />
    </div>
    <div :class="'w-max'">
      <Dropdown align="end" :options="dropdownOptions">
        <Button variant="ghost" icon="lucide-more-horizontal" />
      </Dropdown>
    </div>
  </div>
  <Dialog v-model:open="show" :size="'3xl'" :title="__('Nested Conditions')">
    <template #default>
      <CFConditions
        :conditions="condition"
        :isChild="true"
        :level="props.level"
        :disableAddCondition="props.disableAddCondition"
        :doctype="props.doctype"
      />
    </template>
  </Dialog>
</template>

<script setup>
import { PhStack as GroupIcon } from '@phosphor-icons/vue'
// Phosphor's own family already pairs Stack with a "minus" variant for
// removing from a stack, which reads as the mirror of "Turn into a Group"
// (PhStack) above — a closer, same-family match than the Lucide glyph it
// replaces, not just a style swap.
import { PhStackMinus as UnGroupIcon } from '@phosphor-icons/vue'
import CFConditions from './CFConditions.vue'
import Link from '@/components/Controls/Link.vue'
import {
  Combobox,
  Button,
  DatePicker,
  DateRangePicker,
  DateTimePicker,
  Dialog,
  Dropdown,
  FormControl,
  Rating,
} from 'frappe-ui'
import { filterableFields } from './filterableFields'
import { reactive, computed, h, ref } from 'vue'

const show = ref(false)
const emit = defineEmits([
  'remove',
  'unGroupConditions',
  'toggleConjunction',
  'turnIntoGroup',
])

const props = defineProps({
  condition: { type: Array, required: true },
  isChild: { type: Boolean, default: false },
  itemIndex: { type: Number, default: 0 },
  level: { type: Number, default: 0 },
  isGroup: { type: Boolean, default: false },
  conjunction: { type: String, default: 'and' },
  disableAddCondition: { type: Boolean, default: false },
  doctype: { type: String, default: '' },
})

// Follows the prop rather than wrapping it once at setup: a row reused for
// another condition went on showing and editing the one it mounted with.
const condition = computed(() => reactive(props.condition))

const dropdownOptions = computed(() => {
  const options = []

  if (!props.isGroup && props.level < 4) {
    options.push({
      label: __('Turn into a Group'),
      icon: () => h(GroupIcon),
      onClick: () => {
        emit('turnIntoGroup')
      },
    })
  }

  if (props.isGroup) {
    options.push({
      label: __('Ungroup Conditions'),
      icon: () => h(UnGroupIcon),
      onClick: () => {
        emit('unGroupConditions')
      },
    })
  }

  options.push({
    label: __('Remove'),
    icon: 'lucide-trash-2',
    variant: 'red',
    onClick: () => emit('remove'),
    condition: () => !props.isGroup,
  })

  options.push({
    label: __('Remove Group'),
    icon: 'lucide-trash-2',
    variant: 'red',
    onClick: () => emit('remove'),
    condition: () => props.isGroup,
  })

  return options
})

const typeCheck = ['Check']
const typeLink = ['Link', 'Dynamic Link']
const typeNumber = ['Float', 'Int', 'Currency', 'Percent']
const typeSelect = ['Select']
const typeString = ['Data', 'Long Text', 'Small Text', 'Text Editor', 'Text']
const typeDate = ['Date', 'Datetime']
const typeRating = ['Rating']

function toggleConjunction() {
  emit('toggleConjunction', props.conjunction)
}

const updateField = (field) => {
  condition.value[0] = field?.fieldname
  resetConditionValue()
}

const resetConditionValue = () => {
  condition.value[2] = ''
}

function getValueControl() {
  const [field, operator] = condition.value
  if (!field) return null
  const fieldData = filterableFields.data?.find((f) => f.fieldname == field)
  if (!fieldData) return null
  const { fieldtype, options } = fieldData
  if (operator == 'is') {
    return h(FormControl, {
      type: 'select',
      options: [
        {
          label: __('Set'),
          value: 'set',
        },
        {
          label: __('Not Set'),
          value: 'not set',
        },
      ],
    })
  } else if (['like', 'not like', 'in', 'not in'].includes(operator)) {
    return h(FormControl, { type: 'text' })
  } else if (typeSelect.includes(fieldtype) || typeCheck.includes(fieldtype)) {
    const _options =
      fieldtype == 'Check' ? ['Yes', 'No'] : getSelectOptions(options)
    return h(FormControl, {
      type: 'select',
      options: _options.map((o) => ({
        label: o,
        value: o,
      })),
    })
  } else if (typeLink.includes(fieldtype)) {
    if (fieldtype == 'Dynamic Link') {
      return h(FormControl, { type: 'text' })
    }
    return h(Link, {
      class: 'form-control',
      doctype: options,
      value: condition.value[2],
    })
  } else if (typeNumber.includes(fieldtype)) {
    return h(FormControl, { type: 'number' })
  } else if (typeDate.includes(fieldtype) && operator == 'between') {
    return h(DateRangePicker, { value: condition.value[2], iconLeft: '' })
  } else if (typeDate.includes(fieldtype)) {
    return h(fieldtype == 'Date' ? DatePicker : DateTimePicker, {
      value: condition.value[2],
      iconLeft: '',
    })
  } else if (typeRating.includes(fieldtype)) {
    return h(Rating, {
      modelValue: condition.value[2] || 0,
      class: 'truncate',
      'update:modelValue': (v) => updateValue(v),
    })
  } else {
    return h(FormControl, { type: 'text' })
  }
}

function updateValue(value) {
  value = value?.target ? value.target.value : value
  if (condition.value[1] === 'between') {
    // frappe-ui v1's DateRangePicker emits [from, to], and [] once cleared;
    // the old one emitted "from,to". An incomplete range is left unset.
    const range = Array.isArray(value) ? value : String(value ?? '').split(',')
    condition.value[2] =
      range.length === 2 && range[0] && range[1] ? [range[0], range[1]] : ''
  } else {
    condition.value[2] = isNaN(value) ? value : Number(value)
  }
}

function getSelectOptions(options) {
  return options.split('\n')
}

function updateOperator() {
  condition.value[2] = getDefaultValue(condition.value[0])
  resetConditionValue()
}

function getOperators() {
  let options = []
  const field = condition.value[0]
  if (!field) return options
  const fieldData = filterableFields.data?.find((f) => f.fieldname == field)
  if (!fieldData) return options
  const { fieldtype, fieldname } = fieldData
  if (typeString.includes(fieldtype)) {
    options.push(
      ...[
        { label: __('Equals'), value: '==' },
        { label: __('Not Equals'), value: '!=' },
        { label: __('Like'), value: 'like' },
        { label: __('Not Like'), value: 'not like' },
        { label: __('In'), value: 'in' },
        { label: __('Not In'), value: 'not in' },
        { label: __('Is'), value: 'is' },
      ],
    )
  }
  if (fieldname === '_assign') {
    options = [
      { label: __('Like'), value: 'like' },
      { label: __('Not Like'), value: 'not like' },
      { label: __('Is'), value: 'is' },
    ]
  }
  if (typeNumber.includes(fieldtype)) {
    options.push(
      ...[
        { label: __('Equals'), value: '==' },
        { label: __('Not Equals'), value: '!=' },
        { label: __('Like'), value: 'like' },
        { label: __('Not Like'), value: 'not like' },
        { label: __('In'), value: 'in' },
        { label: __('Not In'), value: 'not in' },
        { label: __('Is'), value: 'is' },
        { label: '<', value: '<' },
        { label: '>', value: '>' },
        { label: '<=', value: '<=' },
        { label: '>=', value: '>=' },
      ],
    )
  }
  if (typeSelect.includes(fieldtype)) {
    options.push(
      ...[
        { label: __('Equals'), value: '==' },
        { label: __('Not Equals'), value: '!=' },
        { label: __('In'), value: 'in' },
        { label: __('Not In'), value: 'not in' },
        { label: __('Is'), value: 'is' },
      ],
    )
  }
  if (typeLink.includes(fieldtype)) {
    options.push(
      ...[
        { label: __('Equals'), value: '==' },
        { label: __('Not Equals'), value: '!=' },
        { label: __('Like'), value: 'like' },
        { label: __('Not Like'), value: 'not like' },
        { label: __('In'), value: 'in' },
        { label: __('Not In'), value: 'not in' },
        { label: __('Is'), value: 'is' },
      ],
    )
  }
  if (typeCheck.includes(fieldtype)) {
    options.push(...[{ label: __('Equals'), value: '==' }])
  }
  if (['Duration'].includes(fieldtype)) {
    options.push(
      ...[
        { label: __('Like'), value: 'like' },
        { label: __('Not Like'), value: 'not like' },
        { label: __('In'), value: 'in' },
        { label: __('Not In'), value: 'not in' },
        { label: __('Is'), value: 'is' },
      ],
    )
  }
  if (typeDate.includes(fieldtype)) {
    options.push(
      ...[
        { label: __('Equals'), value: '==' },
        { label: __('Not Equals'), value: '!=' },
        { label: __('Is'), value: 'is' },
        { label: '>', value: '>' },
        { label: '<', value: '<' },
        { label: '>=', value: '>=' },
        { label: '<=', value: '<=' },
        { label: __('Between'), value: 'between' },
      ],
    )
  }
  if (typeRating.includes(fieldtype)) {
    options.push(
      ...[
        { label: __('Equals'), value: '==' },
        { label: __('Not Equals'), value: '!=' },
        { label: __('Is'), value: 'is' },
        { label: '>', value: '>' },
        { label: '<', value: '<' },
        { label: '>=', value: '>=' },
        { label: '<=', value: '<=' },
      ],
    )
  }
  const op = options.find((o) => o.value == condition.value[1])
  condition.value[1] = op?.value || options[0].value
  return options
}

function getDefaultValue(field) {
  if (typeSelect.includes(field.fieldtype)) {
    return getSelectOptions(field.options)[0]
  }
  if (typeCheck.includes(field.fieldtype)) {
    return 'Yes'
  }
  if (typeDate.includes(field.fieldtype)) {
    return null
  }
  if (typeRating.includes(field.fieldtype)) {
    return 0
  }
  return ''
}
</script>
