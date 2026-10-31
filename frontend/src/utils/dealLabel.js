/**
 * What a deal is called on the board and the list.
 *
 * They lead with its organization, which a deal need not have: it read
 * "No Title" on a card and left a blank first cell, which is the link into the
 * record. The deal's own name is always there.
 *
 * @param {{ name: string, organization?: string }} deal
 */
export function dealLabel(deal) {
  return deal.organization || deal.name
}
