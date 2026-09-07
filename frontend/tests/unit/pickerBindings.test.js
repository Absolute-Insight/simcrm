/**
 * frappe-ui 1.0.0-beta.55's DatePicker, DateTimePicker and TimePicker are
 * v-model components: they read `modelValue` and emit `update:modelValue` /
 * `change`. Before beta.55 the app bound them with `:value=`, which the new
 * components silently ignore -- Vue passes the unknown prop through as a DOM
 * attribute -- so every stored date rendered as its placeholder while the
 * `@change` handlers kept working. A deal with an expected closure date showed
 * "Add Expected Closure Date..." and a task's due date looked blank in its own
 * edit dialog. This scans the source so the binding cannot regress.
 */
import { describe, expect, it } from 'vitest'
import { readdirSync, readFileSync, statSync } from 'node:fs'
import { join, relative } from 'node:path'

const SRC = join(__dirname, '..', '..', 'src')
const PICKERS = ['DatePicker', 'DateTimePicker', 'TimePicker']

function vueFiles(dir) {
  const out = []
  for (const entry of readdirSync(dir)) {
    const path = join(dir, entry)
    if (statSync(path).isDirectory()) out.push(...vueFiles(path))
    else if (entry.endsWith('.vue')) out.push(path)
  }
  return out
}

/** Every opening tag of a picker component, with its attribute block. */
function pickerTags(source) {
  const tags = []
  const re = new RegExp(`<(${PICKERS.join('|')})\\b([^>]*)>`, 'g')
  let match
  while ((match = re.exec(source))) tags.push({ component: match[1], attrs: match[2] })
  return tags
}

describe('date and time pickers are bound with modelValue', () => {
  const files = vueFiles(SRC)

  it('finds the pickers it is guarding', () => {
    const total = files.reduce((n, f) => n + pickerTags(readFileSync(f, 'utf8')).length, 0)
    expect(total).toBeGreaterThan(5)
  })

  it('never binds a picker with :value=', () => {
    const offenders = []
    for (const file of files) {
      for (const tag of pickerTags(readFileSync(file, 'utf8'))) {
        if (/(^|\s):value=/.test(tag.attrs)) {
          offenders.push(`${relative(SRC, file)} <${tag.component} ... :value=>`)
        }
      }
    }
    expect(offenders).toEqual([])
  })
})
