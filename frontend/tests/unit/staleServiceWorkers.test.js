import { describe, it, expect, vi, afterEach } from 'vitest'
import {
  selectSupersededRegistrations,
  selectOrphanedCaches,
  cleanUpSupersededWorkers,
} from '@/utils/staleServiceWorkers'

const SCRIPT = '/assets/crm/frontend/sw.js'
const SCOPE = '/crm'
const OLD_SCOPE = '/assets/crm/frontend/'
const ORIGIN = 'https://crm.example.com'

const registration = (
  scope,
  { scriptURL = ORIGIN + SCRIPT, slot = 'active' } = {},
) => ({
  scope: ORIGIN + scope,
  [slot]: { scriptURL },
})

describe('selectSupersededRegistrations', () => {
  it('drops our worker sitting at the scope we moved away from', () => {
    const stale = registration(OLD_SCOPE)
    expect(
      selectSupersededRegistrations([stale], {
        scriptPath: SCRIPT,
        scope: SCOPE,
      }),
    ).toEqual([stale])
  })

  it('keeps our worker at the scope we now use', () => {
    expect(
      selectSupersededRegistrations([registration(SCOPE)], {
        scriptPath: SCRIPT,
        scope: SCOPE,
      }),
    ).toEqual([])
  })

  it('leaves a worker that is not ours alone, whatever its scope', () => {
    // The origin is shared with Frappe's desk and website.
    const foreign = registration('/app', {
      scriptURL: ORIGIN + '/assets/other/sw.js',
    })
    expect(
      selectSupersededRegistrations([foreign], {
        scriptPath: SCRIPT,
        scope: SCOPE,
      }),
    ).toEqual([])
  })

  it.each(['installing', 'waiting'])(
    'recognises our script in the %s slot, not only active',
    (slot) => {
      const stale = registration(OLD_SCOPE, { slot })
      expect(
        selectSupersededRegistrations([stale], {
          scriptPath: SCRIPT,
          scope: SCOPE,
        }),
      ).toEqual([stale])
    },
  )

  it('ignores a registration with no worker in any slot', () => {
    expect(
      selectSupersededRegistrations([{ scope: ORIGIN + OLD_SCOPE }], {
        scriptPath: SCRIPT,
        scope: SCOPE,
      }),
    ).toEqual([])
  })
})

describe('selectOrphanedCaches', () => {
  const retired = ORIGIN + OLD_SCOPE
  const live = ORIGIN + SCOPE

  it('picks the precache named after the retired scope', () => {
    const names = [
      `workbox-precache-v2-${retired}`,
      `workbox-precache-v2-${live}`,
    ]
    expect(
      selectOrphanedCaches(names, {
        supersededScopes: [retired],
        currentScope: live,
      }),
    ).toEqual([`workbox-precache-v2-${retired}`])
  })

  it('leaves caches belonging to nobody we retired', () => {
    expect(
      selectOrphanedCaches(['some-unrelated-cache'], {
        supersededScopes: [retired],
        currentScope: live,
      }),
    ).toEqual([])
  })

  it('keeps the live cache when the retired scope is a prefix of it', () => {
    // A later move from /crm to /crm/app: the retired scope is a substring of
    // the live one, so a plain `includes` would bin the running precache.
    const nested = ORIGIN + '/crm/app'
    expect(
      selectOrphanedCaches([`workbox-precache-v2-${nested}`], {
        supersededScopes: [live],
        currentScope: nested,
      }),
    ).toEqual([])
  })
})

describe('cleanUpSupersededWorkers', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('resolves empty where the browser has no service workers', async () => {
    vi.stubGlobal('navigator', {})
    await expect(
      cleanUpSupersededWorkers({ scriptPath: SCRIPT, scope: SCOPE }),
    ).resolves.toEqual([])
  })

  it('unregisters the stale registration and deletes its cache, sparing the live one', async () => {
    const origin = location.origin
    const staleScope = origin + OLD_SCOPE
    const liveScope = origin + SCOPE

    const unregister = vi.fn().mockResolvedValue(true)
    const liveUnregister = vi.fn().mockResolvedValue(true)
    vi.stubGlobal('navigator', {
      serviceWorker: {
        getRegistrations: async () => [
          {
            scope: staleScope,
            active: { scriptURL: origin + SCRIPT },
            unregister,
          },
          {
            scope: liveScope,
            active: { scriptURL: origin + SCRIPT },
            unregister: liveUnregister,
          },
        ],
      },
    })

    const deleted = []
    vi.stubGlobal('caches', {
      keys: async () => [
        `workbox-precache-v2-${staleScope}`,
        `workbox-precache-v2-${liveScope}`,
      ],
      delete: async (name) => deleted.push(name),
    })

    await expect(
      cleanUpSupersededWorkers({ scriptPath: SCRIPT, scope: SCOPE }),
    ).resolves.toEqual([staleScope])
    expect(unregister).toHaveBeenCalledOnce()
    expect(liveUnregister).not.toHaveBeenCalled()
    expect(deleted).toEqual([`workbox-precache-v2-${staleScope}`])
  })

  it('swallows a browser that refuses to enumerate registrations', async () => {
    vi.stubGlobal('navigator', {
      serviceWorker: {
        getRegistrations: async () => {
          throw new Error('storage disabled')
        },
      },
    })
    await expect(
      cleanUpSupersededWorkers({ scriptPath: SCRIPT, scope: SCOPE }),
    ).resolves.toEqual([])
  })
})
