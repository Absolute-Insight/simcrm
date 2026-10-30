const SCORE = {
  prefix: 1000,
  word: 850,
  substring: 700,
  subsequence: 400,
}

export const RECENT_LIMIT = 5

// What a record's list is called in the nav. Access Control hides a surface for a
// role, and a hidden surface must not come back through search.
const RECORD_SURFACE = {
  Lead: 'Leads',
  Deal: 'Deals',
  Contact: 'Contacts',
  Organization: 'Organizations',
}

function normalize(value) {
  return String(value || '')
    .trim()
    .toLocaleLowerCase()
}

function escapeRegExp(value) {
  return value.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
}

function wordBoundaryIndex(text, term) {
  const match = text.match(new RegExp(`(?:^|\\s)${escapeRegExp(term)}`))
  return match?.index ?? -1
}

function subsequenceGap(text, term) {
  let lastIndex = -1
  let gap = 0
  for (const character of term) {
    const index = text.indexOf(character, lastIndex + 1)
    if (index < 0) return -1
    gap += index - lastIndex - 1
    lastIndex = index
  }
  return gap
}

export function fuzzyScore(value, query) {
  const text = normalize(value)
  const term = normalize(query)
  if (!term) return 0
  if (text.startsWith(term)) return SCORE.prefix - (text.length - term.length)
  const wordIndex = wordBoundaryIndex(text, term)
  if (wordIndex >= 0) return SCORE.word - wordIndex
  const substringIndex = text.indexOf(term)
  if (substringIndex >= 0) return SCORE.substring - substringIndex
  const gap = subsequenceGap(text, term)
  return gap < 0 ? -1 : SCORE.subsequence - gap
}

export function scoreCommand(command, query) {
  if (command.rank != null) return command.rank
  const titleScore = fuzzyScore(command.title, query)
  const keywordScore = fuzzyScore(command.keywords, query) * 0.75
  return Math.max(titleScore, keywordScore) * (command.weight ?? 1)
}

export function groupCommands(commands, query = '') {
  const groups = new Map()
  for (const command of rankedCommands(commands, query)) {
    const group = command.group || ''
    if (!groups.has(group)) groups.set(group, [])
    groups.get(group).push(command)
  }
  return [...groups].map(([title, items]) => ({ title, items }))
}

function rankedCommands(commands, query) {
  return commands
    .map((command, index) => ({
      command,
      index,
      score: scoreCommand(command, query),
    }))
    .filter(({ score }) => score >= 0)
    .sort((a, b) => b.score - a.score || a.index - b.index)
    .map(({ command }) => command)
}

export function isRecordVisible(record, surfaces) {
  return surfaces.has(RECORD_SURFACE[record.route])
}

/** A due item shows only if its row and the place it opens are both visible. */
export function isDueItemVisible(item, surfaces) {
  if (item.kind === 'task' && !surfaces.has('Tasks')) return false
  return surfaces.has(RECORD_SURFACE[item.route] ?? item.route)
}

/** "Deal · QT103406": a customer's deals all carry the customer's name. */
export function recordSubtitle(record) {
  const type = record.doctype.replace('CRM ', '')
  return [__(type), record.detail].filter(Boolean).join(' · ')
}

/** Newest first across doctypes, e.g. [{ doctype: 'CRM Deal', name: 'D-1' }]. */
export function addRecent(recent, record) {
  const { doctype, name } = record
  return [
    { doctype, name },
    ...recent.filter((item) => item.doctype !== doctype || item.name !== name),
  ].slice(0, RECENT_LIMIT)
}

export function recentNamesByDoctype(recent) {
  const names = {}
  for (const { doctype, name } of recent) {
    names[doctype] = [...(names[doctype] || []), name]
  }
  return names
}

export function sortByRecency(records, recent) {
  const position = (record) =>
    recent.findIndex(
      (item) => item.doctype === record.doctype && item.name === record.name,
    )
  return [...records].sort((a, b) => position(a) - position(b))
}
