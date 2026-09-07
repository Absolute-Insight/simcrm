import { createResource } from 'frappe-ui'
import { computed, reactive, ref } from 'vue'

/* The fields crm.api.user.update_profile accepts. Kept in step with
   PROFILE_EDITABLE_FIELDS on the server; anything else on the doc is read-only
   context (email, full_name, modified) and is never sent back. */
const EDITABLE = ['first_name', 'last_name', 'user_image', 'language', 'time_zone']

/**
 * The session user's own profile, shaped like the document resource it
 * replaces (`doc`, `originalDoc`, `save.submit`, `save.loading`) so the Profile
 * and Preferences panes keep their templates.
 *
 * Why not createDocumentResource({ doctype: 'User' }): frappe's User doctype is
 * readable and writable by System Manager only, so that resource answered 403
 * for every Sales User and the panes rendered blank -- a rep could not change
 * their photo, their name or their language, and "Setup your password" is the
 * first item on their onboarding checklist. The two endpoints behind this read
 * and write the caller's own row through a fixed field list.
 */
export function useOwnProfile() {
  const doc = ref(null)
  const originalDoc = ref(null)

  function accept(data) {
    doc.value = { ...data }
    originalDoc.value = { ...data }
  }

  const profile = createResource({
    url: 'crm.api.user.get_profile',
    auto: true,
    onSuccess: accept,
  })

  const update = createResource({
    url: 'crm.api.user.update_profile',
  })

  const save = reactive({
    loading: computed(() => update.loading),
    /** Same call shape as a document resource's save.submit(null, options). */
    submit(_params, { onSuccess, onError } = {}) {
      const changes = {}
      for (const field of EDITABLE) {
        if (doc.value?.[field] !== originalDoc.value?.[field]) {
          changes[field] = doc.value?.[field] ?? null
        }
      }
      return update.submit(
        { changes },
        {
          onSuccess: (data) => {
            accept(data)
            onSuccess?.(data)
          },
          onError,
        },
      )
    },
  })

  return reactive({
    doc,
    originalDoc,
    save,
    loading: computed(() => profile.loading),
    reload: () => profile.reload(),
  })
}
