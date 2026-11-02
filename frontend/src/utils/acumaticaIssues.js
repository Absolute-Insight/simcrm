// What the settings panel offers on a "Possible Duplicate" sync issue. The server
// (crm/integrations/acumatica/outbound.py) stores the customers the organization may
// already be as `candidates`; crm.integrations.acumatica.api checks every action again,
// so these only decide which buttons to draw.

const SAME_VAT = 'same VAT number'

/**
 * The customers to offer, deduplicated by code. `canLink` is false for one another
 * organization here already holds: linking a second organization to it is refused,
 * and the fix is moving the deal to `organization` instead.
 */
export function duplicateCandidates(issue) {
  if (issue?.kind !== 'Possible Duplicate') return []
  const seen = new Set()
  const out = []
  for (const c of Array.isArray(issue.candidates) ? issue.candidates : []) {
    const customerId = typeof c?.customer_id === 'string' ? c.customer_id : ''
    if (!customerId || seen.has(customerId)) continue
    seen.add(customerId)
    out.push({
      customerId,
      organization: c.organization || null,
      name: c.organization_name || c.organization || customerId,
      reasons: Array.isArray(c.reasons) ? c.reasons : [],
      canLink: !c.organization,
    })
  }
  return out
}

/**
 * Whether "Create as new" may be offered. One taxpayer is one customer, so a match
 * on the VAT number cannot be confirmed past -- the server refuses it as well.
 */
export function canConfirmNew(issue) {
  if (issue?.kind !== 'Possible Duplicate') return false
  return !duplicateCandidates(issue).some((c) => c.reasons.includes(SAME_VAT))
}
