import { readdirSync, readFileSync, statSync } from 'node:fs'
import { join } from 'node:path'
import { describe, expect, it } from 'vitest'

function sourceFiles(dir) {
  return readdirSync(dir).flatMap((name) => {
    const path = join(dir, name)
    if (statSync(path).isDirectory()) return sourceFiles(path)
    return /\.(vue|js)$/.test(name) ? [path] : []
  })
}

describe('createListResource page length', () => {
  it('is never 0, which frappe-ui reads as unset and loads 20 rows', () => {
    const offenders = sourceFiles(join(process.cwd(), 'src')).filter((file) =>
      /\bpageLength:\s*0\b/.test(readFileSync(file, 'utf8')),
    )

    expect(offenders).toEqual([])
  })
})
