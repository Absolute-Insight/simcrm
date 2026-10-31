import { describe, expect, it, vi } from 'vitest'
import { mount } from '../mount.js'
import { Button, field, flush } from './standIns.js'

// stores/settings.js against frappe-ui's real document resource: the defect is
// in which object the store keeps after the resource replaces its doc.
const backend = vi.hoisted(() => ({ handlers: {}, log: [], toasts: [] }))
vi.mock('frappe-ui', async (importOriginal) =>
  (await import('./standIns.js')).frappeUi(importOriginal, backend),
)
vi.mock('@/components/Controls/ImageUploader.vue', () => ({
  default: { render: () => null },
}))

const db = {
  doctype: 'FCRM Settings',
  name: 'FCRM Settings',
  brand_name: 'Vectora',
  brand_logo: '',
  favicon: '',
  currency: 'ZAR',
}
backend.handlers['frappe.client.get'] = () => structuredClone(db)
backend.handlers['frappe.client.set_value'] = ({ fieldname }) => {
  Object.assign(db, fieldname)
  return structuredClone(db)
}

const { getSettings } = await import('@/stores/settings')
const { default: BrandSettings } = await import(
  '@/components/Settings/BrandSettings.vue'
)

async function typeName(el, value) {
  const input = el.querySelector('input')
  input.value = value
  input.dispatchEvent(new Event('input'))
  await flush()
}

describe('FCRM Settings readers', () => {
  it('follow every save, and no unsaved edit', async () => {
    await flush()
    const { brand, settings } = getSettings()
    expect(brand.name).toBe('Vectora')

    // main.js registers Button globally, and BrandSettings relies on that
    const { el } = mount(BrandSettings, { stubs: { Button } })
    await flush()

    await typeName(el, 'Vectora ZA')
    // typed but not saved: nothing outside the pane may see it yet
    expect(settings.value.brand_name).toBe('Vectora')
    field(el, 'Update').click()
    await flush()
    expect(brand.name).toBe('Vectora ZA')
    expect(settings.value.brand_name).toBe('Vectora ZA')

    await typeName(el, 'Vectora MBP')
    field(el, 'Update').click()
    await flush()
    expect(db.brand_name).toBe('Vectora MBP')
    expect(brand.name).toBe('Vectora MBP')
    expect(settings.value.brand_name).toBe('Vectora MBP')
    expect(settings.value.currency).toBe('ZAR')
  })
})
