// The bare 'frappe-ui' specifier resolves here (vite.config.js alias) so that
// @framework/ui — whose source still imports FeatherIcon from 'frappe-ui' —
// keeps working against beta.53, which removed it (ADR-0008). Everything else
// passes straight through to the real package; app code imports nothing from
// this file knowingly, and subpath imports (frappe-ui/experimental etc.) are
// untouched by the alias. Delete the FeatherIcon export when upstream frappe/ui
// stops importing it.
//
// `call` is the one override: a local export shadows the `export *`, and every
// `import { call } from 'frappe-ui'` gets the lapsed-session redirect the
// resources already have (see call.js). It keeps the shim alive on its own.
export * from 'frappe-ui-actual'
export { default as FeatherIcon } from './FeatherIcon.vue'
export { default as call } from './call.js'
