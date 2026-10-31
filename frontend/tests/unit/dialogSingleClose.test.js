import { readdirSync, readFileSync } from 'node:fs'
import { join } from 'node:path'
import { parse } from '@vue/compiler-sfc'
import { describe, expect, it } from 'vitest'

/**
 * A source guard, because the defect is a shape that spans every dialog:
 * frappe-ui's Dialog draws its own close button unless it is `bare`, so a
 * close button written into a `#title` slot shows as a second X beside it.
 */
const SRC = join(process.cwd(), 'src')
const CLOSE = /lucide-x\b|LucideX|CloseIcon/

const vueFiles = (dir) =>
  readdirSync(dir, { withFileTypes: true }).flatMap((entry) => {
    const path = join(dir, entry.name)
    if (entry.isDirectory()) return vueFiles(path)
    return entry.name.endsWith('.vue') ? [path] : []
  })

function dialogsIn(node, found = []) {
  if (node.type === 1 && node.tag === 'Dialog') found.push(node)
  for (const child of node.children || []) dialogsIn(child, found)
  return found
}

const isBare = (dialog) =>
  dialog.props.some((p) => p.name === 'bare' || p.arg?.content === 'bare')
const titleSlot = (dialog) =>
  dialog.children.find(
    (c) =>
      c.type === 1 &&
      c.tag === 'template' &&
      c.props.some((p) => p.arg?.content === 'title'),
  )

describe('dialog close buttons', () => {
  it('no dialog adds a second one in its title', () => {
    const offenders = vueFiles(SRC).flatMap((file) => {
      const source = readFileSync(file, 'utf8')
      if (!source.includes('<Dialog')) return []
      const { template } = parse(source).descriptor
      if (!template) return []
      return dialogsIn(template.ast)
        .filter((d) => !isBare(d) && CLOSE.test(titleSlot(d)?.loc.source))
        .map(() => file.replace(`${SRC}/`, ''))
    })
    expect(offenders).toEqual([])
  })
})
