/* A function rather than a const, because the labels are translated and this is
   a plain module: `__` is installed on window by the translation plugin during
   app creation, which happens after every module in the import graph has been
   evaluated. A `__()` at module scope here would run before the function exists.
   These appear in the filter and sort field pickers. */
export function getStandardFieldsMeta() {
  return [
    {
      fieldname: 'name',
      label: __('Name'),
      fieldtype: 'Data',
    },
    {
      fieldname: 'creation',
      label: __('Created On'),
      fieldtype: 'Datetime',
    },
    {
      fieldname: 'modified',
      label: __('Last Modified'),
      fieldtype: 'Datetime',
    },
    {
      fieldname: 'modified_by',
      label: __('Modified By'),
      fieldtype: 'Link',
      options: 'User',
    },
    { label: __('Assigned To'), fieldtype: 'Text', fieldname: '_assign' },
    {
      label: __('Owner'),
      fieldtype: 'Link',
      fieldname: 'owner',
      options: 'User',
    },
    { label: __('Like'), fieldtype: 'Data', fieldname: '_liked_by' },
  ]
}

export const noValueFieldTypes = [
  'Section Break',
  'Column Break',
  'Tab Break',
  'Table',
  'Table MultiSelect',
  'Button',
  'Image',
]
