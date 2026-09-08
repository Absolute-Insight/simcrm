import js from '@eslint/js'
import ts from 'typescript-eslint'
import pluginVue from 'eslint-plugin-vue'
import configPrettier from 'eslint-config-prettier'
import vueParser from 'vue-eslint-parser'
import globals from 'globals'

export default [
  {
    ignores: ['**/dist/**', '**/node_modules/**', '**/public/dist/**'],
  },
  js.configs.recommended,
  ...ts.configs.recommended,
  ...pluginVue.configs['flat/recommended'],
  {
    files: ['**/*.vue', '**/*.js', '**/*.ts'],
    languageOptions: {
      parser: vueParser,
      parserOptions: {
        parser: ts.parser,
        sourceType: 'module',
        ecmaVersion: 'latest',
      },
      globals: {
        ...globals.browser,
        ...globals.node,
        frappe: 'readonly',
        __: 'readonly',
      },
    },
  },
  {
    rules: {
      'vue/multi-word-component-names': 'off',
      'vue/prop-name-casing': 'off',
      'vue/attribute-hyphenation': 'off',
      'vue/v-on-event-hyphenation': 'off',
      '@typescript-eslint/no-explicit-any': 'warn',
      // `{ description, ...rest }` is how a field is dropped from an object;
      // the pulled-out name is the point, not a leftover.
      '@typescript-eslint/no-unused-vars': [
        'warn',
        { ignoreRestSiblings: true },
      ],
      'no-undef': 'error',
      // The telephony components shipped every inbound caller's phone number
      // and the full call payload to the browser console of every rep's
      // machine, where a console-forwarding error tracker or a screen
      // recording picks it up. Those calls are gone; this stops the next one.
      // warn/error stay allowed -- a bundle that cannot report a real failure
      // is worse than a chatty one.
      'no-console': ['error', { allow: ['warn', 'error', 'info'] }],
    },
  },
  {
    // frappe-ui's Dialog runs each action as `onClick({ close })`. A handler
    // written `(close) => { ...; close() }` receives the whole object, so the
    // action runs and then throws "close is not a function" with the dialog
    // still open. Two rounds of fixes covered 4 then 17 call sites by hand;
    // this keeps the two signatures from drifting apart again. Form-script
    // actions (src/doctypes/**, rendered by CustomActions.vue) legitimately
    // take a bare close function and are excluded.
    files: ['src/**/*.vue', 'src/**/*.js', 'src/**/*.ts'],
    ignores: ['src/doctypes/**'],
    rules: {
      'no-restricted-syntax': [
        'error',
        {
          selector:
            'Property[key.name="onClick"] > :function[params.length=1] > Identifier.params[name="close"]',
          message:
            'Dialog actions are called as onClick({ close }); destructure the object.',
        },
      ],
    },
  },
  configPrettier,
]
