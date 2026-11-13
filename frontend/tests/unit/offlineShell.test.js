import { readFileSync } from 'node:fs'
import { join } from 'node:path'
import { describe, expect, it } from 'vitest'
import { shellFromIndex } from '../../offlineShell.js'
import {
  BOOT_KEYS,
  BOOT_SNAPSHOT_KEY,
  loadOfflineBoot,
  OFFLINE_OWNER_KEY,
  saveBootSnapshot,
  shellLoaderScript,
  takeBootSnapshot,
} from '@/offline/bootSnapshot'

const JINJA = `
          <script>
              {% for key in boot %}
              window["{{ key }}"] = {{ boot[key] | tojson }};
              {% endfor %}
          </script>
          </body>`

function memoryStorage(initial = {}) {
  const map = new Map(Object.entries(initial))
  return {
    getItem: (key) => (map.has(key) ? map.get(key) : null),
    setItem: (key, value) => map.set(key, String(value)),
    removeItem: (key) => map.delete(key),
  }
}

describe('the offline shell', () => {
  const index = `<html><head><script>var a = 1</script></head><body><div id="app"></div>${JINJA}</html>`

  it('carries no template syntax, so it can be served unrendered', () => {
    const shell = shellFromIndex(index)
    expect(shell).not.toMatch(/\{%/)
    expect(shell).not.toContain('| tojson')
    expect(shell).toContain('__crm_offline_shell')
    expect(shell).toContain('<div id="app"></div>')
  })

  it('fails the build when the boot block is not where it expects', () => {
    expect(() => shellFromIndex('<html><body></body></html>')).toThrow(
      /boot block was not found/,
    )
  })

  it('fails the build when other template syntax would be left in', () => {
    expect(() =>
      shellFromIndex(index.replace('<div id="app">', '<div id="{{ x }}">')),
    ).toThrow(/template syntax remains/)
  })

  it('the loader it inlines is valid on its own', () => {
    const win = {
      localStorage: memoryStorage({
        [OFFLINE_OWNER_KEY]: 'rep@example.com',
        [BOOT_SNAPSHOT_KEY]: JSON.stringify({
          user: 'rep@example.com',
          boot: { site_name: 'vectora' },
        }),
      }),
    }
    // exactly the text the page runs, with the page's two globals supplied
    new Function('window', 'document', shellLoaderScript())(win, { cookie: '' })
    expect(win.__crm_offline_user).toBe('rep@example.com')
    expect(win.site_name).toBe('vectora')
  })
})

describe('the boot a shell starts from', () => {
  const snapshot = (user) =>
    JSON.stringify({ user, boot: { site_name: 'vectora', timezone: {} } })
  const load = (cookie, stored) => {
    const win = {}
    loadOfflineBoot(
      win,
      cookie,
      memoryStorage(stored),
      BOOT_SNAPSHOT_KEY,
      OFFLINE_OWNER_KEY,
    )
    return win
  }

  it('restores the boot for the user the cookie names', () => {
    const win = load('sid=x; user_id=rep%40example.com', {
      [BOOT_SNAPSHOT_KEY]: snapshot('rep@example.com'),
    })
    expect(win.__crm_offline_shell).toBe(true)
    expect(win.__crm_offline_user).toBe('rep@example.com')
    expect(win.site_name).toBe('vectora')
  })

  it('falls back to the device’s offline owner when the session cookie is gone', () => {
    const win = load('', {
      [OFFLINE_OWNER_KEY]: 'rep@example.com',
      [BOOT_SNAPSHOT_KEY]: snapshot('rep@example.com'),
    })
    expect(win.__crm_offline_user).toBe('rep@example.com')
  })

  it('gives another user nothing of the last one', () => {
    const win = load('user_id=other%40example.com', {
      [OFFLINE_OWNER_KEY]: 'rep@example.com',
      [BOOT_SNAPSHOT_KEY]: snapshot('rep@example.com'),
    })
    expect(win.__crm_offline_user).toBeUndefined()
    expect(win.site_name).toBeUndefined()
  })

  it('honours a Guest cookie as logged out', () => {
    const win = load('user_id=Guest', {
      [OFFLINE_OWNER_KEY]: 'rep@example.com',
      [BOOT_SNAPSHOT_KEY]: snapshot('rep@example.com'),
    })
    expect(win.__crm_offline_user).toBeUndefined()
  })

  it('survives storage that throws or holds rubbish', () => {
    const win = {}
    loadOfflineBoot(
      win,
      '',
      {
        getItem() {
          throw new Error('blocked')
        },
      },
      BOOT_SNAPSHOT_KEY,
      OFFLINE_OWNER_KEY,
    )
    expect(win.__crm_offline_shell).toBe(true)
    expect(
      load('user_id=rep', { [BOOT_SNAPSHOT_KEY]: '{not json' })
        .__crm_offline_user,
    ).toBeUndefined()
  })

  it('never keeps the CSRF token at rest', () => {
    const taken = takeBootSnapshot(
      { site_name: 'vectora', csrf_token: 'secret', timezone: { system: 'x' } },
      'rep@example.com',
    )
    expect(taken.boot).toEqual({
      site_name: 'vectora',
      timezone: { system: 'x' },
    })
    expect(BOOT_KEYS).not.toContain('csrf_token')
  })

  it('saves nothing for a page that has no boot or no user', () => {
    const storage = memoryStorage()
    expect(saveBootSnapshot(null, { site_name: 'vectora' }, storage)).toBe(
      false,
    )
    expect(saveBootSnapshot('rep@example.com', {}, storage)).toBe(false)
    expect(storage.getItem(BOOT_SNAPSHOT_KEY)).toBeNull()
  })

  it('drops the translations rather than the whole boot when storage is full', () => {
    const map = new Map()
    const storage = {
      getItem: (key) => map.get(key) ?? null,
      setItem(key, value) {
        if (value.includes('translated_messages')) throw new Error('quota')
        map.set(key, value)
      },
    }
    const saved = saveBootSnapshot(
      'rep@example.com',
      { site_name: 'vectora', translated_messages: { a: 'b' } },
      storage,
    )
    expect(saved).toBe(true)
    expect(JSON.parse(storage.getItem(BOOT_SNAPSHOT_KEY)).boot).toEqual({
      site_name: 'vectora',
    })
  })

  it('names exactly the keys the server boots with, minus the token', () => {
    const source = readFileSync(
      join(process.cwd(), '..', 'crm', 'www', 'crm.py'),
      'utf8',
    )
    const body = source.slice(
      source.indexOf('def get_boot():'),
      source.indexOf('def get_state_options'),
    )
    const serverKeys = [...body.matchAll(/^\t{3}"([a-z_]+)":/gm)].map(
      (match) => match[1],
    )
    expect(serverKeys).toContain('csrf_token')
    expect([...BOOT_KEYS].sort()).toEqual(
      serverKeys.filter((key) => key !== 'csrf_token').sort(),
    )
  })
})
