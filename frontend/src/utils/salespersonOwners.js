// CRM Acumatica Settings.salesperson_owners holds {"<salesperson ID>": "<user>"}
// and salesperson_branches {"<salesperson ID>": "<branch ID>"}, both as JSON; the
// settings panel edits them as one set of rows. The server validates both again on
// save (crm/integrations/acumatica/quotes.py), so these only shape them.

/**
 * Rows for the editor; [] when nothing is stored. null when what is stored cannot
 * be read as a mapping: the panel then shows the raw value to fix, because rows
 * started empty would overwrite it with the first edit.
 */
export function parseOwnerMap(raw, rawBranches) {
  const data = readObject(raw)
  if (data === null) return null
  // an unreadable branch map is dropped, not shown: the server refuses to save one
  const branches = readObject(rawBranches) || {}
  return Object.entries(data || {}).map(([code, user]) => ({
    code: String(code),
    user: typeof user === 'string' ? user : '',
    branch: typeof branches[code] === 'string' ? branches[code] : '',
  }))
}

// {} for nothing stored, null for something that is not a JSON object
function readObject(raw) {
  if (!raw) return {}
  let data = raw
  if (typeof raw === 'string') {
    try {
      data = JSON.parse(raw)
    } catch {
      return null
    }
  }
  if (!data || typeof data !== 'object' || Array.isArray(data)) return null
  return data
}

/** The field's value: complete rows only, trimmed, the last of a repeated ID winning. */
export function serialiseOwnerMap(rows) {
  const out = {}
  for (const row of rows || []) {
    const code = (row?.code || '').trim()
    const user = (row?.user || '').trim()
    if (code && user) out[code] = user
  }
  return Object.keys(out).length ? JSON.stringify(out, null, 1) : ''
}

/** Salesperson Branches: the branch of each complete row that has one. */
export function serialiseBranchMap(rows) {
  const out = {}
  for (const row of rows || []) {
    const code = (row?.code || '').trim()
    const user = (row?.user || '').trim()
    const branch = (row?.branch || '').trim()
    if (code && user && branch) out[code] = branch
  }
  return Object.keys(out).length ? JSON.stringify(out, null, 1) : ''
}
