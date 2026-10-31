<template>
  <Avatar
    :label="user ? getUser(user).full_name : label || getUser(user).full_name"
    :image="user || !label ? getUser(user).user_image : undefined"
    v-bind="$attrs"
  />
</template>
<script setup>
import { usersStore } from '@/stores/users'
import { Avatar } from 'frappe-ui'

defineProps({
  user: { type: String, default: null },
  // For what is not a user, such as a visit's organization: getUser() of no
  // name is the signed-in user, who has no business on that avatar.
  label: { type: String, default: '' },
})

const { getUser } = usersStore()
</script>
