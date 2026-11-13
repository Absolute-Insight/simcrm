import { readFileSync } from 'node:fs'
import { join } from 'node:path'
import { describe, expect, it } from 'vitest'
import { shellFromIndex } from '../../offlineShell.js'
import {
  BOOT_KEYS,
  BOOT_SNAPSHOT_KEY,
  FIELD_USER_COOKIE,
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
    new Function('window', 'document', shellLoaderScript())(win, {
      cookie: `${FIELD_USER_COOKIE}=rep%40example.com`,
    })
    expect(win.__crm_offline_user).toBe('rep@example.com')
    expect(win.site_name).toBe('vectora')
  })
})

describe('the boot a shell starts from', () => {
  const snapshot = (user) =>
    JSON.stringify({ user, boot: { site_name: 'vectora', timezone: {} } })
  const FIELD = `${FIELD_USER_COOKIE}=rep%40example.com`
  const load = (cookie, stored) => {
    const win = {}
    loadOfflineBoot(
      win,
      cookie,
      memoryStorage(stored),
      BOOT_SNAPSHOT_KEY,
      OFFLINE_OWNER_KEY,
      FIELD_USER_COOKIE,
      BOOT_KEYS,
    )
    return win
  }
  const held = {
    [OFFLINE_OWNER_KEY]: 'rep@example.com',
    [BOOT_SNAPSHOT_KEY]: snapshot('rep@example.com'),
  }

  it('restores the boot for the user the cookie names', () => {
    const win = load('sid=x; user_id=rep%40example.com', {
      [BOOT_SNAPSHOT_KEY]: snapshot('rep@example.com'),
    })
    expect(win.__crm_offline_shell).toBe(true)
    expect(win.__crm_offline_user).toBe('rep@example.com')
    expect(win.site_name).toBe('vectora')
  })

  it('opens for the signed-in user when the phone dropped the session cookie', () => {
    expect(load(`sid=x; ${FIELD}`, held).__crm_offline_user).toBe(
      'rep@example.com',
    )
  })

  it('does not open on the stores alone: a logout deletes the cookie', () => {
    // logged out from the desk, app closed before /crm was loaded again
    const win = load('', held)
    expect(win.__crm_offline_user).toBeUndefined()
    expect(win.site_name).toBeUndefined()
  })

  it('does not open for a signed-in user whose stores these are not', () => {
    const win = load(`${FIELD_USER_COOKIE}=other%40example.com`, held)
    expect(win.__crm_offline_user).toBeUndefined()
  })

  it('gives another user nothing of the last one', () => {
    const win = load('user_id=other%40example.com', held)
    expect(win.__crm_offline_user).toBeUndefined()
    expect(win.site_name).toBeUndefined()
  })

  it('honours a Guest cookie as logged out', () => {
    expect(load(`user_id=Guest; ${FIELD}`, held).__crm_offline_user).toBe(
      undefined,
    )
  })

  it('restores only the boot keys, whatever the snapshot holds', () => {
    const win = load('user_id=rep%40example.com', {
      [BOOT_SNAPSHOT_KEY]: JSON.stringify({
        user: 'rep@example.com',
        boot: { site_name: 'vectora', csrf_token: 'planted', location: 'x' },
      }),
    })
    expect(win.site_name).toBe('vectora')
    expect(win.csrf_token).toBeUndefined()
    expect(win.location).toBeUndefined()
  })

  it('survives storage that throws or holds rubbish', () => {
    const win = {}
    loadOfflineBoot(
      win,
      FIELD,
      {
        getItem() {
          throw new Error('blocked')
        },
      },
      BOOT_SNAPSHOT_KEY,
      OFFLINE_OWNER_KEY,
      FIELD_USER_COOKIE,
      BOOT_KEYS,
    )
    expect(win.__crm_offline_shell).toBe(true)
    expect(win.__crm_offline_user).toBeUndefined()
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

  it('names the cookie the server sets', () => {
    const source = readFileSync(
      join(process.cwd(), '..', 'crm', 'api', 'offline.py'),
      'utf8',
    )
    expect(source).toContain(`FIELD_USER_COOKIE = "${FIELD_USER_COOKIE}"`)
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
