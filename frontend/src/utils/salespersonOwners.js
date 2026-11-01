// CRM Acumatica Settings.salesperson_owners holds {"<salesperson ID>": "<user>"}
// as JSON; the settings panel edits it as rows. The server validates it again on
// save (crm/integrations/acumatica/quotes.py:parse_owner_map), so these only shape it.

/** Rows for the editor; anything unreadable starts as no rows rather than throwing. */
export function parseOwnerMap(raw) {
  if (!raw) return []
  let data = raw
  if (typeof raw === 'string') {
    try {
      data = JSON.parse(raw)
    } catch {
      return []
    }
  }
  if (!data || typeof data !== 'object' || Array.isArray(data)) return []
  return Object.entries(data).map(([code, user]) => ({
    code: String(code),
    user: typeof user === 'string' ? user : '',
  }))
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
