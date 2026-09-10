import { io } from 'socket.io-client'
import { getCachedListResource, getCachedResource } from 'frappe-ui'

export function initSocket() {
  let siteName = window.site_name

  // In production the socket goes back to the origin the page came from, and
  // nginx proxies /socket.io to the websocket service. The old code switched to
  // `http://<host>:<socketio_port>` whenever the URL carried a port -- but the
  // stack publishes no 9000, so a customer proxying the app on, say, :8443 got
  // a cross-origin call to a closed port, blocked as mixed content: no
  // suggestion badge, no notification popups, no live list refreshes, and
  // nothing in the UI to say so. It also meant the localhost:8090 rehearsal in
  // the runbook could never prove realtime worked.
  //
  // Only the vite dev server needs the direct port, because nothing proxies for
  // it there.
  let url = `${window.location.origin}/${siteName}`
  if (import.meta.env.DEV) {
    let socketio_port = window.socketio_port || 9000
    url = `http://${window.location.hostname}:${socketio_port}/${siteName}`
  }

  // socket.io's default is to keep retrying with backoff. The previous cap of
  // five attempts (~20 s) meant a laptop that slept through a coffee break came
  // back with realtime silently dead for the rest of the tab's life: no new
  // suggestion badge, no notification popups, no list refreshes.
  let socket = io(url, {
    withCredentials: true,
    reconnectionAttempts: Infinity,
  })
  socket.on('refetch_resource', (data) => {
    if (data.cache_key) {
      let resource =
        getCachedResource(data.cache_key) ||
        getCachedListResource(data.cache_key)
      if (resource) {
        resource.reload()
      }
    }
  })
  return socket
}
