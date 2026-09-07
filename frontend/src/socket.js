import { io } from 'socket.io-client'
import { getCachedListResource, getCachedResource } from 'frappe-ui'

export function initSocket() {
  let socketio_port = window.socketio_port || 9000
  let host = window.location.hostname
  let siteName = window.site_name
  let port = window.location.port ? `:${socketio_port}` : ''
  let protocol = port ? 'http' : 'https'
  let url = `${protocol}://${host}${port}/${siteName}`

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
