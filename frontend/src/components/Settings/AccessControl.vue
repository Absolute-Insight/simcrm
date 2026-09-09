<!--
  Settings → Access Control.

  Two sections, and the difference between them is the design: above the rule,
  switches that change what the database returns; below it, a matrix that
  changes what the app shows. The copy says so, and it is load bearing -- edit
  it away and this pane starts implying it protects data that it does not.

  Nothing is hideable from an administrator, so the matrix has two columns. A
  manager may set the rep column only; the server refuses the rest
  (crm/api/access.py::set_visibility) and this UI does not offer it.
-->
<template>
  <div class="flex h-full flex-col gap-6 p-8">
    <div class="flex flex-col gap-1">
      <h2 class="v-title text-ink-gray-8">{{ __('Access Control') }}</h2>
      <p class="text-p-sm text-ink-gray-5">
        {{
          __(
            'Who can read what, and which parts of the app each role is shown.',
          )
        }}
      </p>
    </div>

    <!-- §1 Data access -->
    <section class="flex flex-col gap-3">
      <div class="flex flex-col gap-0.5">
        <h3 class="text-base font-semibold text-ink-gray-8">
          {{ __('Data access') }}
        </h3>
        <p class="text-p-sm text-ink-gray-5">
          {{
            __(
              'These change what the server returns. They apply everywhere — lists, dashboards, reports and the API.',
            )
          }}
        </p>
      </div>

      <SkeletonTable
        v-if="dataAccess.loading"
        :columns="2"
        :rows="2"
        density="compact"
        :label="__('Loading data access settings')"
      />

      <ErrorState
        v-else-if="dataAccess.error"
        :error="dataAccess.error"
        :title="__('Could not load the data access settings')"
        :retry="dataAccess.reload"
      />

      <div v-else class="flex flex-col gap-3">
        <div
          class="flex items-start justify-between gap-4 rounded-[var(--v-radius-card)] bg-surface-white p-4"
        >
          <div class="flex flex-col gap-0.5">
            <div class="text-base text-ink-gray-8">
              {{ __('Restrict by sales hierarchy') }}
            </div>
            <p class="text-p-sm text-ink-gray-5">
              {{ hierarchyCopy }}
            </p>
          </div>
          <CheckSwitch
            :model-value="dataAccess.data?.enable_sales_hierarchy"
            size="sm"
            :disabled="!isAdmin()"
            @update:model-value="onHierarchyToggle"
          />
        </div>

        <div
          class="flex items-start justify-between gap-4 rounded-[var(--v-radius-card)] bg-surface-white p-4"
        >
          <div class="flex flex-col gap-0.5">
            <div class="text-base text-ink-gray-8">
              {{ __('Managers outside the hierarchy') }}
            </div>
            <p class="text-p-sm text-ink-gray-5">
              {{
                __(
                  'A manager who is not in the tree either reads the whole site or only their own records. On a site with no tree yet, that is every manager.',
                )
              }}
            </p>
          </div>
          <!-- FormControl type="select", not a bare <Select>: that is the
               house pattern for a select in Settings (see
               GeneralSettings.vue's timeline controls) and keeps this pane
               visually identical to its neighbours. -->
          <FormControl
            type="select"
            class="w-48 shrink-0"
            :model-value="dataAccess.data?.manager_outside_hierarchy"
            :options="managerScopeOptions"
            :disabled="!isAdmin()"
            @update:model-value="onManagerScopeChange"
          />
        </div>

        <p v-if="!isAdmin()" class="text-p-sm text-ink-orange-9">
          {{ __('Only an administrator can change these.') }}
        </p>
      </div>
    </section>

    <!-- §2 Surface visibility -->
    <section class="flex min-h-0 flex-1 flex-col gap-3">
      <div class="flex flex-col gap-0.5">
        <h3 class="text-base font-semibold text-ink-gray-8">
          {{ __('What each role is shown') }}
        </h3>
        <!-- The sentence this pane is honest because of. Do not remove it. -->
        <p class="text-p-sm text-ink-gray-5">
          {{
            __(
              'Hiding a surface tidies the app for that role. It is not a permission — the data behind a hidden page is still governed by Data access above. Nothing can be hidden from an administrator.',
            )
          }}
        </p>
      </div>

      <SkeletonTable
        v-if="access.visibility.loading"
        :columns="CONFIGURABLE_ROLES.length + 1"
        :rows="12"
        density="compact"
        class="flex-1 px-1"
        :label="__('Loading the surface matrix')"
      />

      <ErrorState
        v-else-if="access.visibility.error"
        class="flex-1"
        :error="access.visibility.error"
        :title="__('Could not load the surface matrix')"
        :retry="access.reload"
      />

      <div v-else class="min-h-0 flex-1 overflow-auto">
        <table class="min-w-full text-base">
          <thead class="sticky top-0 z-10 bg-surface-elevation-2">
            <tr class="text-left text-ink-gray-6">
              <th scope="col" class="py-2 pr-4 font-medium">
                {{ __('Surface') }}
              </th>
              <th
                v-for="role in CONFIGURABLE_ROLES"
                :key="role"
                scope="col"
                class="w-40 py-2 pr-4 font-medium"
              >
                {{ roleLabel(role) }}
              </th>
            </tr>
          </thead>
          <tbody>
            <template v-for="group in ['nav', 'settings']" :key="group">
              <tr>
                <td
                  :colspan="CONFIGURABLE_ROLES.length + 1"
                  class="pb-1 pt-4 text-xs-medium uppercase tracking-wide text-ink-gray-5"
                >
                  {{ group === 'nav' ? __('Navigation') : __('Settings') }}
                </td>
              </tr>
              <tr
                v-for="surface in surfacesByGroup(group)"
                :key="surface.key"
                class="border-t border-[var(--v-shell-hairline)]"
              >
                <td class="py-2 pr-4 text-ink-gray-8">
                  <span v-if="surface.section" class="text-ink-gray-5"
                    >{{ __(surface.section) }} &middot; </span
                  >{{ __(surface.label) }}
                </td>
                <td
                  v-for="role in CONFIGURABLE_ROLES"
                  :key="role"
                  class="py-2 pr-4"
                >
                  <Tooltip
                    v-if="isAtFloor(surface, role)"
                    :text="
                      __('Already unavailable to this role: {0} only.', [
                        roleLabel(surface.floor),
                      ])
                    "
                  >
                    <span class="text-ink-gray-4" tabindex="0">—</span>
                  </Tooltip>
                  <CheckSwitch
                    v-else
                    :model-value="isVisible(role, surface.key) ? 1 : 0"
                    size="sm"
                    :disabled="!editableBy(callerRole, role) || saving"
                    @update:model-value="
                      (v) => onToggle(role, surface.key, Boolean(v))
                    "
                  />
                </td>
              </tr>
            </template>
          </tbody>
        </table>
      </div>
    </section>
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { createResource, FormControl, Tooltip, toast } from 'frappe-ui'
import CheckSwitch from '@/components/ui/CheckSwitch.vue'
import ErrorState from '@/components/ui/ErrorState.vue'
import SkeletonTable from '@/components/ui/SkeletonTable.vue'
import { accessStore } from '@/stores/access'
import { usersStore } from '@/stores/users'
import { globalStore } from '@/stores/global'
import {
  CONFIGURABLE_ROLES,
  editableBy,
  isAtFloor,
  surfacesByGroup,
} from '@/utils/surfaces'

const { isAdmin } = usersStore()
const { $dialog } = globalStore()
const access = accessStore()

// §1 refreshes itself via createResource's own auto:true; §2's data is the
// store's shared `visibility` resource, fetched once at boot by the router
// guard. Without this, opening the pane long after boot -- or in a second
// tab -- renders however stale a matrix that boot fetch got, and
// set_visibility is a whole-row replace, so a save from that stale row
// silently discards whatever anyone else changed to that row since.
// Swallowed on failure: access.visibility.error is already reactive and the
// template's ErrorState renders from it -- an uncaught rejection here would
// only be a second, unhandled report of the same failure (createResource
// re-throws even after its own onError runs; see stores/access.js).
onMounted(() => {
  access.reload().catch(() => {})
})

const saving = ref(false)

const callerRole = computed(() => access.role)

const ROLE_LABELS = {
  'Sales Manager': __('Manager'),
  'Sales User': __('Rep'),
  'System Manager': __('Admin'),
}
function roleLabel(role) {
  return ROLE_LABELS[role] || role
}

const managerScopeOptions = [
  { label: __('All records'), value: 'All records' },
  { label: __('Own records only'), value: 'Own records only' },
]

const dataAccess = createResource({
  url: 'crm.api.access.get_data_access',
  auto: true,
})

const hierarchyCopy = computed(() => {
  const size = dataAccess.data?.hierarchy_size || 0
  if (dataAccess.data?.enable_sales_hierarchy) {
    return __(
      'On. Leads and deals are scoped to the reporting tree — {0} people are in it.',
      [size],
    )
  }
  // "Off" always takes every manager out of the tree (org_hierarchy.py's
  // in_tree is hierarchy_enabled() and _in_hierarchy(user)), but what that
  // means depends on the scope below: the default ("All records") hands
  // every manager the whole site, while "Own records only" narrows every
  // manager to their own records, same as a rep.
  return dataAccess.data?.manager_outside_hierarchy === 'Own records only'
    ? __(
        'Off, and every manager is outside the tree, so each reads only their own leads, deals and target — the same as a rep. Turning it on restores subtree access to managers already in it.',
      )
    : __(
        "Off. Every manager reads every lead and deal on the site, and every rep's targets.",
      )
})

// Hoisted, not built fresh inside saveDataAccess(): a createResource() per
// click is a throwaway object every time, out of step with how every other
// save button in Settings works (Quotas.vue's grid, Hierarchy.vue's
// fcrmSettings). One resource, submitted with whatever payload the caller
// that click needs.
const setDataAccess = createResource({
  url: 'crm.api.access.set_data_access',
  method: 'POST',
})

function saveDataAccess(payload, message) {
  setDataAccess
    .submit(payload)
    .then(() => {
      dataAccess.reload()
      toast.success(message)
    })
    .catch((error) =>
      toast.error(
        error?.messages?.[0] || error?.message || __('Could not save'),
      ),
    )
}

function onHierarchyToggle(value) {
  // Only the *disabling* direction is confirmed -- its consequence depends on
  // the scope below (widens under "All records", narrows under "Own records
  // only"), which is exactly what the message branches on. Same shape as
  // Hierarchy.vue.
  if (!value) {
    const message =
      dataAccess.data?.manager_outside_hierarchy === 'Own records only'
        ? __(
            'Every manager will be narrowed to their own leads, deals and sales target — the same as a rep, since none of them will be in the tree. Are you sure?',
          )
        : __(
            'Every manager will be able to read every lead, deal and sales target on the site. Are you sure?',
          )
    $dialog({
      title: __('Stop restricting by hierarchy?'),
      message,
      actions: [
        {
          label: __('Stop restricting'),
          variant: 'solid',
          theme: 'red',
          onClick: ({ close }) => {
            saveDataAccess(
              { enable_sales_hierarchy: 0 },
              __('Hierarchy restriction disabled'),
            )
            close()
          },
        },
      ],
    })
    return
  }
  saveDataAccess(
    { enable_sales_hierarchy: 1 },
    __('Hierarchy restriction enabled'),
  )
}

function onManagerScopeChange(value) {
  saveDataAccess({ manager_outside_hierarchy: value }, __('Saved'))
}

function hiddenFor(role) {
  return access.matrix?.[role] || []
}

function isVisible(role, key) {
  return !hiddenFor(role).includes(key)
}

// Hoisted for the same reason as setDataAccess above -- one resource for
// every toggle in the matrix, not one per click.
const setVisibility = createResource({
  url: 'crm.api.access.set_visibility',
  method: 'POST',
})

async function onToggle(role, key, nextVisible) {
  // Vue's :disabled binding on the switch is reactive but not synchronous --
  // two clicks in the same tick both arrive here before the DOM disables
  // anything, and would otherwise both read the same base row and the
  // second whole-row write would clobber the first.
  if (saving.value) return

  const hidden = new Set(hiddenFor(role))
  if (nextVisible) hidden.delete(key)
  else hidden.add(key)

  saving.value = true
  try {
    await setVisibility.submit({ role, hidden: Array.from(hidden) })
  } catch (error) {
    toast.error(error?.messages?.[0] || error?.message || __('Could not save'))
    saving.value = false
    return
  }

  toast.success(__('Saved'))

  // Re-read rather than patching local state: the caller's own row may be
  // among the ones that changed, and the shell reads it from this store.
  // Its own try/catch on purpose, separate from the save above: the save
  // already succeeded and is already reported, so a blip on this refresh
  // must not turn into "Could not save" for a row that did save --
  // createResource re-throws even after its own onError runs, and
  // stores/access.js's onError already resets hidden to [] as its own
  // fail-open, so there is nothing further to tell the user here.
  try {
    await access.reload()
  } catch {
    // handled above
  } finally {
    saving.value = false
  }
}
</script>
