/**
 * Which built chunks the service worker leaves out of its precache.
 *
 * The worker precached every file of the build -- 2 MB over the wire on a
 * phone's first visit, and again for each chunk a release changes -- to have
 * a handful of them ready offline. What offline needs is the boot and field
 * mode (router.js: the routes marked `offline`); the dashboard's charts, the
 * rich-text editor, the phone SDK and the maps are fetched by pages that need
 * the server anyway. Those are left to the runtime cache: fetched the first
 * time a page asks, kept after that (vite.config.js).
 *
 * The rule is written to fail safe. A chunk is left out only when it holds
 * one of the named heavy libraries AND nothing offline can reach it:
 *
 *  - everything the entry imports statically is kept;
 *  - everything the offline pages reach, statically or on demand, is kept;
 *  - everything the boot reaches on demand is kept too, except through the
 *    modules named `serverOnly` -- the route table, the app shell's layouts
 *    and the record form, each of which opens only with a server behind it.
 *
 * So a heavy library that field mode starts to use stays precached without
 * anyone remembering this file, and a chunk nobody listed is never left out.
 *
 * It works on the chunks rollup wrote, not on the source's import graph: a
 * barrel import reaches every module of a package on paper, and only the
 * chunks say what tree-shaking left. The source graph is used for one thing,
 * to tell which module of a chunk asked for an on-demand import.
 *
 * Pure, so it can be tested without a build: the vite plugin hands it
 * rollup's output.
 *
 * @param {Array<{
 *   fileName: string,
 *   isEntry: boolean,
 *   imports: string[],
 *   modules: Array<{id: string, dynamicImports: string[]}>,
 * }>} chunks  each chunk with the chunks it imports statically (file names)
 *   and the modules rendered into it, each with the module ids it imports on
 *   demand
 * @param {object} rules
 * @param {RegExp[]} rules.heavy        module ids of the libraries to leave out
 * @param {RegExp[]} rules.offlineRoots module ids of the pages that run offline
 * @param {RegExp[]} rules.serverOnly   modules whose on-demand imports need a server
 * @returns {{lazy: Set<string>, kept: Array<{fileName: string, via: string[]}>}}
 *   file names left out of the precache, and the heavy ones kept in it with
 *   the chain of chunks, nearest first, by which offline reaches them
 */
export function planPrecache(chunks, rules) {
  const matches = (patterns, id) => patterns.some((p) => p.test(id))
  const byName = new Map(chunks.map((chunk) => [chunk.fileName, chunk]))
  const chunkOf = new Map()
  for (const chunk of chunks) {
    for (const module of chunk.modules) chunkOf.set(module.id, chunk.fileName)
  }

  // chunk -> the chunk that led to it (null for a root)
  const needed = new Map()
  const queue = []
  const visit = (fileName, from) => {
    if (!byName.has(fileName) || needed.has(fileName)) return
    needed.set(fileName, from)
    queue.push(fileName)
  }

  for (const chunk of chunks) {
    const offline = chunk.modules.some((m) => matches(rules.offlineRoots, m.id))
    if (chunk.isEntry || offline) visit(chunk.fileName, null)
  }
  while (queue.length) {
    const chunk = byName.get(queue.shift())
    for (const dep of chunk.imports) visit(dep, chunk.fileName)
    for (const module of chunk.modules) {
      const offline = matches(rules.offlineRoots, module.id)
      const serverOnly = !offline && matches(rules.serverOnly, module.id)
      for (const dep of module.dynamicImports) {
        // the route table and the shell: only the offline pages are followed
        if (serverOnly && !matches(rules.offlineRoots, dep)) continue
        visit(chunkOf.get(dep), chunk.fileName)
      }
    }
  }
  const chainTo = (fileName) => {
    const chain = []
    for (let at = fileName; at; at = needed.get(at)) chain.push(at)
    return chain
  }

  const lazy = new Set()
  const kept = []
  for (const chunk of chunks) {
    if (!chunk.modules.some((m) => matches(rules.heavy, m.id))) continue
    if (needed.has(chunk.fileName)) {
      kept.push({ fileName: chunk.fileName, via: chainTo(chunk.fileName) })
    } else {
      lazy.add(chunk.fileName)
    }
  }
  return { lazy, kept }
}

/** The libraries worth leaving out: each is tens to hundreds of KB gzipped. */
export const HEAVY_LIBRARIES = [
  /\/node_modules\/(echarts|zrender)\//, // the dashboard's charts
  /\/node_modules\/(@tiptap|prosemirror-[\w-]+|lowlight|highlight\.js)\//, // the editor
  /\/node_modules\/@twilio\//,
  /\/node_modules\/leaflet[\w.-]*\//,
  /\/node_modules\/lucide-static\/sprite\.svg/,
]

/** Field mode: the pages router.js marks `offline`, and what they are built on. */
export const OFFLINE_ROOTS = [
  /\/src\/pages\/Field\.vue/,
  /\/src\/components\/Field\//,
  /\/src\/offline\//,
]

/** Modules whose on-demand imports open only with a server behind them. */
export const SERVER_ONLY = [
  /\/src\/router\.js$/,
  /\/src\/App\.vue/,
  /\/src\/components\/Modals\/DoctypeModals\.vue/,
]
