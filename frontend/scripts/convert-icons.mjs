// One-shot conversion of the legacy hand-drawn icons to Phosphor wrappers.
// Committed rather than run-and-deleted so the mapping is reviewable and the
// conversion is reproducible if the icon set is revisited.
import fs from 'node:fs'
import path from 'node:path'

const MAP = {
  ActivityIcon: 'PhPulse',
  AddressIcon: 'PhMapPinLine',
  AppsIcon: 'PhSquaresFour',
  ArrowUpRightIcon: 'PhArrowUpRight',
  AscendingIcon: 'PhSortAscending',
  AttachmentIcon: 'PhPaperclip',
  AvatarIcon: 'PhUserCircle',
  BellIcon: 'PhBell',
  CalendarIcon: 'PhCalendarBlank',
  CameraIcon: 'PhCamera',
  CertificateIcon: 'PhCertificate',
  CheckCircleIcon: 'PhCheckCircle',
  CheckIcon: 'PhCheck',
  CollapseSidebar: 'PhSidebarSimple',
  ColumnsIcon: 'PhColumns',
  CommentIcon: 'PhChatCircle',
  ContactIcon: 'PhUser',
  ContactsIcon: 'PhAddressBook',
  ConvertIcon: 'PhArrowsLeftRight',
  DashboardIcon: 'PhSquaresFour',
  DealsIcon: 'PhHandshake',
  DeclinedCallIcon: 'PhPhoneX',
  DescriptionIcon: 'PhTextAlignLeft',
  DesendingIcon: 'PhSortDescending',
  DetailsIcon: 'PhInfo',
  DialpadIcon: 'PhDotsNine',
  DocumentIcon: 'PhFileText',
  DoubleCheckIcon: 'PhChecks',
  DragIcon: 'PhDotsSixVertical',
  DragVerticalIcon: 'PhDotsSixVertical',
  DuplicateIcon: 'PhCopy',
  DurationIcon: 'PhTimer',
  EditIcon: 'PhPencilSimple',
  Email2Icon: 'PhEnvelopeSimple',
  EmailAtIcon: 'PhAt',
  EmailIcon: 'PhEnvelope',
  EmailTemplateIcon: 'PhEnvelopeSimple',
  EventIcon: 'PhCalendarCheck',
  ExportIcon: 'PhDownloadSimple',
  ExternalLinkIcon: 'PhArrowSquareOut',
  FileAudioIcon: 'PhMusicNote',
  FileIcon: 'PhFile',
  FileImageIcon: 'PhImage',
  FileSpreadsheetIcon: 'PhFileXls',
  FileTextIcon: 'PhFileText',
  FileTypeIcon: 'PhFile',
  FileVideoIcon: 'PhVideo',
  GroupByIcon: 'PhStack',
  HelpIcon: 'PhQuestion',
  InboxIcon: 'PhTray',
  KanbanIcon: 'PhKanban',
  LightningIcon: 'PhLightning',
  ListIcon: 'PhListBullets',
  MapIcon: 'PhMapTrifold',
  MarkAsDoneIcon: 'PhCheckCircle',
  MaximizeIcon: 'PhCornersOut',
  MenuIcon: 'PhList',
  MinimizeIcon: 'PhCornersIn',
  MissedCallIcon: 'PhPhoneSlash',
  MoneyIcon: 'PhCurrencyDollar',
  MuteIcon: 'PhSpeakerSlash',
  NoteIcon: 'PhNote',
  NotificationsIcon: 'PhBell',
  OrganizationsIcon: 'PhBuildings',
  OutboundCallIcon: 'PhPhoneOutgoing',
  PauseIcon: 'PhPause',
  PeopleIcon: 'PhUsers',
  PhoneIcon: 'PhPhone',
  PinIcon: 'PhPushPin',
  PlannerIcon: 'PhCalendarDots',
  PlayIcon: 'PhPlay',
  PlaybackSpeedIcon: 'PhGauge',
  QuickFilterIcon: 'PhFunnel',
  ReactIcon: 'PhSmiley',
  RefreshIcon: 'PhArrowsClockwise',
  ReloadIcon: 'PhArrowCounterClockwise',
  ReplyAllIcon: 'PhArrowBendDoubleUpLeft',
  ReplyIcon: 'PhArrowBendUpLeft',
  ReportsIcon: 'PhChartBar',
  RightSideLayoutIcon: 'PhSidebarSimple',
  SelectIcon: 'PhSelection',
  SettingsIcon: 'PhGear',
  SettingsIcon2: 'PhGear',
  ShieldIcon: 'PhShield',
  SlidersIcon: 'PhSlidersHorizontal',
  SmileIcon: 'PhSmiley',
  SortIcon: 'PhArrowsDownUp',
  SparkleIcon: 'PhSparkle',
  SquareAsterisk: 'PhAsterisk',
  StepsIcon: 'PhSteps',
  SuccessIcon: 'PhCheckCircle',
  SuggestionsIcon: 'PhLightning',
  TaskIcon: 'PhListChecks',
  TerritoryIcon: 'PhGlobe',
  UnpinIcon: 'PhPushPinSlash',
  VolumnHighIcon: 'PhSpeakerHigh',
  VolumnLowIcon: 'PhSpeakerLow',
  WebsiteIcon: 'PhGlobe',
  FilterIcon: 'PhFunnelSimple',
  GenderIcon: 'PhGenderIntersex',
  HeartIcon: 'PhHeart',
  InboundCallIcon: 'PhPhoneIncoming',
  InviteIcon: 'PhUserPlus',
  LeadsIcon: 'PhTarget',
  LinkIcon: 'PhLink',
  LocationIcon: 'PhMapPin',
}

// BellIcon was already converted in Task 3 (the pilot for this codemod), so
// its file is already a Phosphor wrapper with no width/height/viewBox left
// to scrape. Fall back to the size Task 3 recorded for it in _phosphor.js.
const PRE_CONVERTED_SIZES = { BellIcon: [16, 16] }

const DIR = new URL('../src/components/Icons/', import.meta.url).pathname
const sizes = {}

// Pass 1: read every size BEFORE overwriting anything. Keeping the read and
// write passes separate means a bad mapping fails loudly before any file is
// touched, rather than leaving the run half-converted (and unreadable on a
// retry, since the already-converted files no longer carry a width/height).
for (const [name] of Object.entries(MAP)) {
  const file = path.join(DIR, `${name}.vue`)
  const src = fs.readFileSync(file, 'utf8')
  const w = src.match(/width="(\d+)"/)
  const h = src.match(/height="(\d+)"/)
  // Fall back to the viewBox when the svg carried no explicit width/height.
  const vb = src.match(/viewBox="0 0 (\d+) (\d+)"/)
  const pre = PRE_CONVERTED_SIZES[name]
  const width = Number(w?.[1] ?? vb?.[1] ?? pre?.[0])
  const height = Number(h?.[1] ?? vb?.[2] ?? pre?.[1])
  if (!width || !height) throw new Error(`No size found for ${name}`)
  sizes[name] = [width, height]
}

// Pass 2: now that every size is captured, write all the wrappers.
for (const [name, phosphor] of Object.entries(MAP)) {
  const file = path.join(DIR, `${name}.vue`)
  fs.writeFileSync(
    file,
    `<template>\n  <${phosphor} v-bind="intrinsicProps('${name}')" />\n` +
      `</template>\n\n<script setup>\n` +
      `import { ${phosphor} } from '@phosphor-icons/vue'\n` +
      `import { intrinsicProps } from './_phosphor'\n</script>\n`,
  )
}

const entries = Object.entries(sizes)
  .map(([k, [w, h]]) => `  ${k}: [${w}, ${h}],`)
  .join('\n')
console.log(`Converted ${Object.keys(sizes).length} icons.`)
fs.writeFileSync(
  path.join(DIR, '_sizes.generated.js'),
  `// Generated by scripts/convert-icons.mjs — do not hand-edit.\n` +
    `export const INTRINSIC_SIZE = {\n${entries}\n}\n`,
)
