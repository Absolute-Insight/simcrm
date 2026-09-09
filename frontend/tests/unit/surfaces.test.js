import { readFileSync } from 'node:fs'
import path from 'node:path'
import { describe, it, expect } from 'vitest'
import {
  ADMIN_ROLE,
  MANAGER_ROLE,
  SURFACES,
  canSee,
  editableBy,
  isAtFloor,
  surfacesByGroup,
} from '@/utils/surfaces'

const KEY_SHAPE = /^(nav|settings)\.[a-z0-9_]{1,48}$/

// --- registry-vs-shell cross-check -----------------------------------------
//
// Everything above this line tests the registry in isolation. None of it
// notices if the registry drifts from the two files it claims to describe --
// a key renamed in Settings.vue, or a `condition:` deleted from it, leaves
// SURFACES's own shape checks green. So these tests read the two shells as
// text and check the registry against what they actually say. It is a
// string-matching test on purpose: the whole point is that it breaks loudly
// when someone edits a gate without updating this file to match.

const settingsSrc = readFileSync(
  path.resolve(
    import.meta.dirname,
    '../../src/components/Settings/Settings.vue',
  ),
  'utf8',
)
const sidebarSrc = readFileSync(
  path.resolve(
    import.meta.dirname,
    '../../src/components/Layouts/AppSidebar.vue',
  ),
  'utf8',
)

/** `key: '<prefix>.foo'` literals in `src`, in source order, with where each
 * one starts -- the position is what lets `itemGates` below slice out just
 * that item's own block. */
function keyOccurrences(src, prefix) {
  const re = new RegExp(`key:\\s*'(${prefix}\\.[a-z0-9_]+)'`, 'g')
  const found = []
  let m
  while ((m = re.exec(src))) found.push({ key: m[1], index: m.index })
  return found
}

function keySet(src, prefix) {
  return new Set(keyOccurrences(src, prefix).map((o) => o.key))
}

/**
 * Map of key -> that item's own `condition:` text, or `null` if it has none.
 *
 * Slices from one `key:` occurrence to the next (or to the end of `src` for
 * the last one). Both shells always write an item's fields in the same
 * order -- label, key, icon, component, then an optional condition -- last,
 * right before the item's closing brace. So an item's own condition, when it
 * has one, is always inside its own slice and never inside its neighbour's,
 * even though the slice also drags in the start of the next item.
 */
function itemGates(src, prefix) {
  const occurrences = keyOccurrences(src, prefix)
  const gates = new Map()
  occurrences.forEach(({ key, index }, i) => {
    const end =
      i + 1 < occurrences.length ? occurrences[i + 1].index : src.length
    const condition = src.slice(index, end).match(/condition:\s*([^\n]*)/)
    gates.set(key, condition ? condition[1] : null)
  })
  return gates
}

/**
 * Every `settings.*` key's effective gate: its own `condition:` if it has
 * one, else the enclosing group's.
 *
 * Settings.vue's tabs are each shaped
 * `{ label: __(...), items: [ ...items... ] (, condition: <group gate>)? }`.
 * No item field is itself an array, so the first `]` after `items: [`
 * reliably closes that group's own items and cannot be confused with a
 * later group's.
 */
function settingsGates(src) {
  const GROUP_RE =
    /label:\s*__\([^)]*\)\s*,\s*items:\s*\[([\s\S]*?)\n\s*\](\s*,\s*condition:\s*([^\n]*))?/g
  const gates = new Map()
  let group
  while ((group = GROUP_RE.exec(src))) {
    const [, itemsSrc, , rawGroupCondition] = group
    const groupCondition = rawGroupCondition
      ? rawGroupCondition.replace(/,\s*$/, '').trim()
      : null
    for (const [key, ownCondition] of itemGates(itemsSrc, 'settings')) {
      gates.set(key, ownCondition || groupCondition)
    }
  }
  return gates
}

/** Every `nav.*` key's own condition. AppSidebar has no group nesting --
 * every link's gate, canSee included, lives on the link itself. */
function navGates(src) {
  const links = src.match(/const links = \[([\s\S]*?)\n\]/)?.[1]
  if (!links) throw new Error("could not find AppSidebar.vue's `links` array")
  return itemGates(links, 'nav')
}

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

describe('the registry against the shells it describes', () => {
  // (a) & (b): the registry's key set is exactly what each shell renders --
  // not a superset (a stale entry for a deleted pane) and not a subset (a
  // pane with no row in the matrix, silently unhideable from anyone).
  it('lists exactly the settings.* keys Settings.vue renders', () => {
    const registryKeys = [
      ...surfacesByGroup('settings').map((s) => s.key),
    ].sort()
    const shellKeys = [...keySet(settingsSrc, 'settings')].sort()
    expect(shellKeys).toEqual(registryKeys)
  })

  it('lists exactly the nav.* keys AppSidebar.vue renders', () => {
    const registryKeys = [...surfacesByGroup('nav').map((s) => s.key)].sort()
    const shellKeys = [...keySet(sidebarSrc, 'nav')].sort()
    expect(shellKeys).toEqual(registryKeys)
  })

  // (c): every nav surface actually consults the shared visibility store,
  // not just a role check that happens to look similar.
  it('gates every nav key with its own canSee() call', () => {
    for (const surface of surfacesByGroup('nav')) {
      expect(sidebarSrc, surface.key).toContain(`canSee('${surface.key}')`)
    }
  })

  // (d): every surface the registry claims is already unreachable below a
  // floor actually is, in the shell, right now -- on the item itself or, for
  // Settings.vue, on the group it falls back to when the item carries no
  // condition of its own. This is what the pane's "—, Manager only" cell
  // promises, and it is exactly what deleting Settings.vue's
  // `condition: () => isManager()` from the Email > Templates item breaks:
  // that item has no group condition to fall back to (the Email group has
  // none), so its effective gate goes from `isManager()` to `null` and this
  // test fails. Covers every floored surface in both nav and settings --
  // there is no partial-coverage carve-out here, because the group-fallback
  // case turned out to parse just as reliably as the item-only case.
  it('backs every floor with the matching role gate, on the item or its group', () => {
    const gates = new Map([
      ...settingsGates(settingsSrc),
      ...navGates(sidebarSrc),
    ])
    const requiredCall = {
      [MANAGER_ROLE]: 'isManager()',
      [ADMIN_ROLE]: 'isAdmin()',
    }
    for (const surface of SURFACES.filter((s) => s.floor)) {
      expect(gates.get(surface.key) || '', surface.key).toContain(
        requiredCall[surface.floor],
      )
    }
  })
})
