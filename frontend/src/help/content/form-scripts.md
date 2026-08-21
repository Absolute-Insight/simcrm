# Form scripts

A form script attaches JavaScript behaviour to a record form — validation,
defaults, conditional fields, dialogs, custom buttons — without changing any
source code and without a build step.

**Settings → Automation & Rules → Forms.**

## The shape of one

A script is an ES class whose name is the DocType with the spaces removed:
`CRM Lead` → `CRMLead`. Inside it, methods are hooks.

```js
class CRMLead {
  onValidate() {
    if (!this.doc.email && !this.doc.mobile_no) {
      this.throw('A lead needs an email address or a phone number')
    }
  }

  status() {
    if (this.value === 'Qualified') {
      this.setFieldProperty('deal_value', 'reqd', 1)
    }
  }
}
```

Create the record, set the DocType, tick **Enabled**, save. It takes effect on
the next page load.

## What you get

| | |
|---|---|
| **Lifecycle hooks** | `onLoad`, `onRender`, `onValidate`, `onSave`, `onError`, `onBeforeCreate`, and on leads `onCreateLead` and `convertToDeal`. |
| **Field change hooks** | A method named after a field runs when that field changes, with `this.value` and `this.oldValue` in scope. |
| **Field properties** | `setFieldProperty` for required, hidden, read-only, options and the rest. |
| **Dialogs** | `createDialog` for a message or a confirmation, `formDialog` for a form that returns what the user entered. |
| **Page actions and statuses** | Add buttons to the header and entries to the status dropdown. |
| **Child tables** | Row added, row removed and per-row field changes, and scripts on the child DocType itself. |
| **Backend calls** | Call your own whitelisted methods. |

## Notes worth having up front

- Both naming styles work: `onValidate` and `on_validate` are the same hook.
- Child DocTypes get their own scripts, and a parent can call into them.
- Nothing here is transpiled. What you write is what runs, so write for the
  browsers your team uses.

These APIs are a stable contract: they are added to, never silently renamed, and
anything on the way out is deprecated with a warning first. The full reference,
including every hook signature and the complete `formDialog` API, ships with the
source in `.pi/SPEC.md` and `.pi/feats/form-scripting/`.
