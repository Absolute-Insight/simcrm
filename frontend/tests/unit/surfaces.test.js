import { describe, it, expect } from 'vitest'
import {
  SURFACES,
  canSee,
  editableBy,
  isAtFloor,
  surfacesByGroup,
} from '@/utils/surfaces'

const KEY_SHAPE = /^(nav|settings)\.[a-z0-9_]{1,48}$/

describe('SURFACES', () => {
  it('gives every surface a key the server will accept', () => {
    for (const surface of SURFACES) {
      expect(surface.key, surface.key).toMatch(KEY_SHAPE)
    }
  })

  it('has no duplicate keys', () => {
    const keys = SURFACES.map((s) => s.key)
    expect(new Set(keys).size).toBe(keys.length)
  })

  it('groups every surface as nav or settings', () => {
    for (const surface of SURFACES) {
      expect(['nav', 'settings']).toContain(surface.group)
    }
  })

  it('labels every surface', () => {
    for (const surface of SURFACES) {
      expect(surface.label, surface.key).toBeTruthy()
    }
  })

  it('gives every settings surface a section, and no nav surface one', () => {
    // The matrix renders `section · label` for settings rows, because
    // "Accounts" and "Templates" mean nothing on their own.
    for (const surface of surfacesByGroup('settings')) {
      expect(surface.section, surface.key).toBeTruthy()
    }
    for (const surface of surfacesByGroup('nav')) {
      expect(surface.section, surface.key).toBeUndefined()
    }
  })

  it('uses only section names that exist in Settings.vue', () => {
    const real = [
      'User Configuration',
      'System Configuration',
      'User Management',
      'Email',
      'Automation & Rules',
      'Customization',
      'Integrations',
    ]
    for (const surface of surfacesByGroup('settings')) {
      expect(real, surface.key).toContain(surface.section)
    }
  })

  it('covers the nav links and the settings panes', () => {
    expect(surfacesByGroup('nav').length).toBe(13)
    expect(surfacesByGroup('settings').length).toBe(27)
  })
})

describe('canSee', () => {
  it('shows a surface nobody has hidden', () => {
    expect(canSee('nav.notes', [])).toBe(true)
  })

  it('hides a surface in the hidden set', () => {
    expect(canSee('nav.notes', ['nav.notes'])).toBe(false)
  })

  it('treats a missing hidden set as nothing hidden', () => {
    expect(canSee('nav.notes', undefined)).toBe(true)
    expect(canSee('nav.notes', null)).toBe(true)
  })

  it('ignores an unrecognised key in the hidden set', () => {
    expect(canSee('nav.notes', ['nav.nonsense'])).toBe(true)
  })

  it('fails open instead of throwing when hidden is a truthy non-array', () => {
    // `{} || []` short-circuits to `{}`, so a naive `(hidden || []).includes`
    // throws TypeError on anything object-shaped. Not reachable from the
    // server today, but a loading/error transient in the store is exactly
    // the kind of thing that could produce this -- and a throw here must not
    // blank the whole shell's nav.
    expect(() => canSee('nav.notes', {})).not.toThrow()
    expect(canSee('nav.notes', {})).toBe(true)
  })
})

describe('editableBy', () => {
  it('lets an admin edit both configurable roles', () => {
    expect(editableBy('System Manager', 'Sales Manager')).toBe(true)
    expect(editableBy('System Manager', 'Sales User')).toBe(true)
  })

  it('lets a manager edit only the rep row', () => {
    expect(editableBy('Sales Manager', 'Sales User')).toBe(true)
    expect(editableBy('Sales Manager', 'Sales Manager')).toBe(false)
  })

  it('lets a rep edit nothing', () => {
    expect(editableBy('Sales User', 'Sales User')).toBe(false)
    expect(editableBy('Sales User', 'Sales Manager')).toBe(false)
  })

  it('refuses the admin row to everyone, admins included', () => {
    expect(editableBy('System Manager', 'System Manager')).toBe(false)
  })
})

describe('isAtFloor', () => {
  const analyst = {
    key: 'nav.analyst',
    group: 'nav',
    label: 'Analyst',
    floor: 'System Manager',
  }
  const targets = {
    key: 'settings.sales_targets',
    group: 'settings',
    label: 'Sales Targets',
    floor: 'Sales Manager',
  }
  const notes = { key: 'nav.notes', group: 'nav', label: 'Notes' }

  it('is at floor when the role already cannot reach it', () => {
    expect(isAtFloor(analyst, 'Sales User')).toBe(true)
    expect(isAtFloor(analyst, 'Sales Manager')).toBe(true)
    expect(isAtFloor(targets, 'Sales User')).toBe(true)
  })

  it('is not at floor when the role can reach it', () => {
    expect(isAtFloor(targets, 'Sales Manager')).toBe(false)
    expect(isAtFloor(notes, 'Sales User')).toBe(false)
  })

  it('is never at floor for a surface with no floor', () => {
    expect(isAtFloor(notes, 'Sales Manager')).toBe(false)
  })

  it('reads an unrecognised role as at-floor, not editable', () => {
    // `RANK[role]` is undefined for a role the matrix doesn't know, and
    // `undefined < N` is always false -- so the naive comparison reported
    // "not at floor", i.e. a live toggle, for a role that cannot be ranked
    // at all. Fixed is the safe direction: reading strays into "editable"
    // for a role nobody vetted, not the reverse.
    expect(isAtFloor(analyst, 'Some Unknown Role')).toBe(true)
    expect(isAtFloor(targets, 'Some Unknown Role')).toBe(true)
  })
})
