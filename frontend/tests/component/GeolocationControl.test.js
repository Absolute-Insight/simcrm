import {
  afterAll,
  beforeAll,
  beforeEach,
  describe,
  expect,
  it,
  vi,
} from 'vitest'
import { mount } from './mount.js'

const geolocation = vi.hoisted(() => ({
  watchPosition: vi.fn(() => 7),
  clearWatch: vi.fn(),
  getCurrentPosition: vi.fn(),
}))
const map = vi.hoisted(() => ({ setView: vi.fn() }))

vi.mock('frappe-ui', async () => {
  const { defineComponent, h } = await import('vue')
  return {
    Dialog: defineComponent({
      props: { open: Boolean },
      emits: ['update:open'],
      setup:
        (props, { emit }) =>
        () =>
          h('div', { class: 'dialog', 'data-open': String(props.open) }, [
            h('button', {
              class: 'dialog-close',
              onClick: () => emit('update:open', false),
            }),
          ]),
    }),
    Button: defineComponent({ render: () => h('button') }),
  }
})

// Just enough Leaflet for initMap() to build an empty map.
vi.mock('leaflet', () => {
  const layer = () => ({ addTo: () => layer() })
  class FeatureGroup {
    addTo() {
      return this
    }
    clearLayers() {}
    getLayers() {
      return []
    }
  }
  const L = {
    Icon: { Default: { prototype: {}, mergeOptions: () => {} } },
    Circle: { prototype: { toGeoJSON: () => ({}) }, include: () => {} },
    CircleMarker: { include: () => {} },
    map: () => ({ ...map, on: () => {}, remove: () => {} }),
    tileLayer: layer,
    control: { layers: layer },
    FeatureGroup,
    Control: {
      Draw: class {
        addTo() {}
      },
    },
  }
  return { default: L }
})
vi.mock('leaflet-draw', () => ({}))
vi.mock('leaflet.locatecontrol', () => ({
  locate: () => ({ addTo: () => {} }),
}))

const GeolocationControl = (
  await import('@/components/Controls/GeolocationControl.vue')
).default

const point = JSON.stringify({
  type: 'FeatureCollection',
  features: [
    {
      type: 'Feature',
      properties: {},
      geometry: { type: 'Point', coordinates: [28.04, -26.2] },
    },
  ],
})

const translate = {
  install: (app) => (app.config.globalProperties.__ = globalThis.__),
}
const open = (props) =>
  mount(GeolocationControl, { props, plugins: [translate] })
const dialogOpen = (el) => el.querySelector('.dialog').dataset.open

// Installed for the whole file, not per test: mount.js unmounts whatever a
// failed test left behind after this file's afterEach hooks, and unmounting
// clears the watch through navigator.geolocation.
const realGeolocation = Object.getOwnPropertyDescriptor(
  globalThis.navigator,
  'geolocation',
)
beforeAll(() => {
  Object.defineProperty(globalThis.navigator, 'geolocation', {
    value: geolocation,
    configurable: true,
  })
})
afterAll(() => {
  if (realGeolocation)
    Object.defineProperty(globalThis.navigator, 'geolocation', realGeolocation)
  else delete globalThis.navigator.geolocation
})
beforeEach(() => vi.clearAllMocks())

// initMap() lazy-loads Leaflet and ends by centring the map once.
const mapBuilt = () => vi.waitFor(() => expect(map.setView).toHaveBeenCalled())

describe('GeolocationControl', () => {
  it('Clear clears the value without opening the map dialog', async () => {
    const w = open({ value: point })
    w.el.querySelector('button[title="Clear"]').click()
    await w.nextTick()
    expect(w.emitted.change).toEqual([[null]])
    expect(dialogOpen(w.el)).toBe('false')
    w.unmount()
  })

  it('does not start a GPS watch just by rendering', async () => {
    const controls = [
      open({ value: point, disabled: true }),
      open({ value: point }),
      open({}),
    ]
    await controls[0].nextTick()
    expect(geolocation.watchPosition).not.toHaveBeenCalled()
    controls.forEach((w) => w.unmount())
  })

  it('locates the device when an empty map opens, until the first fix', async () => {
    const w = open({})
    w.el.querySelector('.cursor-pointer').click()
    await w.nextTick()
    expect(dialogOpen(w.el)).toBe('true')
    expect(geolocation.watchPosition).toHaveBeenCalledTimes(1)
    await mapBuilt()

    // The first fix centres the still-empty map and ends the watch.
    const [onPosition] = geolocation.watchPosition.mock.calls[0]
    onPosition({ timestamp: 1, coords: { latitude: -26.2, longitude: 28.04 } })
    await w.nextTick()
    expect(map.setView).toHaveBeenLastCalledWith([-26.2, 28.04], 13)
    expect(geolocation.clearWatch).toHaveBeenCalledWith(7)
    w.unmount()
  })

  it('stops locating the device when the map closes before a fix', async () => {
    const w = open({})
    w.el.querySelector('.cursor-pointer').click()
    await w.nextTick()
    await mapBuilt()
    expect(geolocation.clearWatch).not.toHaveBeenCalled()

    w.el.querySelector('.dialog-close').click()
    await w.nextTick()
    expect(dialogOpen(w.el)).toBe('false')
    expect(geolocation.clearWatch).toHaveBeenCalledWith(7)
    w.unmount()
  })

  it('never asks for the device location for a read-only map', async () => {
    const w = open({ value: point, disabled: true })
    w.el.querySelector('.cursor-pointer').click()
    await w.nextTick()
    expect(dialogOpen(w.el)).toBe('true')
    expect(geolocation.watchPosition).not.toHaveBeenCalled()
    w.unmount()
  })
})
