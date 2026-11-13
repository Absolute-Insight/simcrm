/**
 * Build the page the service worker serves when the server cannot be reached.
 *
 * The built index.html is a Jinja template: Frappe renders it as /crm with the
 * session's boot inlined. That is why it is never precached (see the VitePWA
 * block in vite.config.js) -- and why the app, until now, could not open
 * offline at all. `shell.html` is the same page with the Jinja boot block
 * swapped for a loader that restores the boot from the last online visit
 * (src/offline/bootSnapshot.js). It contains no template syntax and nothing
 * from any session, so it is safe to precache and identical for every user.
 *
 * Written in `writeBundle`, which runs before VitePWA globs the output
 * directory for its precache manifest in `closeBundle`.
 */
import fs from 'node:fs'
import path from 'node:path'
import { shellLoaderScript } from './src/offline/bootSnapshot.js'

/* What frappe-ui's jinjaBootData plugin injects before </body>. */
const JINJA_BOOT =
  /<script>\s*\{%\s*for key in boot\s*%\}[\s\S]*?\{%\s*endfor\s*%\}\s*<\/script>/

export const SHELL_FILE = 'shell.html'

/** index.html with the Jinja boot block replaced by the offline loader. */
export function shellFromIndex(html) {
  if (!JINJA_BOOT.test(html)) {
    throw new Error(
      'offline shell: the Jinja boot block was not found in index.html. ' +
        'frappe-ui changed what jinjaBootData injects; update JINJA_BOOT.',
    )
  }
  const shell = html.replace(
    JINJA_BOOT,
    () => `<script>${shellLoaderScript()}</script>`,
  )
  // Anything Jinja left in the page would be served raw: the failure that
  // took production down when index.html itself was precached.
  if (/\{%|\{\{/.test(shell.replace(/<script>[\s\S]*?<\/script>/g, ''))) {
    throw new Error(
      'offline shell: template syntax remains outside the boot block; ' +
        'the shell would be served unrendered.',
    )
  }
  return shell
}

export function offlineShell() {
  return {
    name: 'offline-shell',
    apply: 'build',
    enforce: 'post',
    writeBundle(options, bundle) {
      const index = bundle['index.html']
      if (!index) this.error('offline shell: the build emitted no index.html')
      let shell
      try {
        shell = shellFromIndex(String(index.source))
      } catch (error) {
        this.error(error.message)
      }
      fs.writeFileSync(path.join(options.dir, SHELL_FILE), shell)
    },
  }
}
