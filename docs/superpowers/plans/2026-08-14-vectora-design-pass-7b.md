# Vectora Design Pass (Phase 7B/7C) — Design Record

Executed 2026-08-14 on branch `vectora-rebrand`, verified live against the dev bench
(light + dark, list/kanban/detail/modal/empty surfaces). This documents the design
system so later phases extend it instead of diverging from it.

## Design system

**Subject.** Vectora is a proactive sales CRM — a precision instrument reps live in
all day. The design reads calm and technical; the brand's directional energy (a
vector) appears exactly where direction matters: *where you are now*.

**Palette.**
- Neutrals: cool graphite ramps (hue ≈ 243, low chroma) replacing frappe-ui's pure
  grays — same lightness per shade, so every component contrast pairing is preserved.
- `--brand-indigo #5b5fe8`: focus ring, selection, active accents. Never body text.
- `--brand-sky #21abfb` / `--brand-magenta #df5feb`: gradient endpoints only.
- Primary buttons stay graphite (now indigo-tinted near-black) — premium restraint,
  not bright accent buttons.

**Signature — the position rail.** One gradient, one meaning: "you are here."
A 2.5px vertical gradient rail marks the active sidebar item; the same gradient is
the selected-tab underline. The gradient appears nowhere else except the V mark.

**Type.** Body stays Inter (frappe-ui metrics). Space Grotesk Variable
(@fontsource-variable) is the display face, applied systematically: every
`text-2xl-*`/`text-3xl-*` utility (record titles, panel + modal headings) and the
page-header title cluster (`header .text-lg-medium`). Tabular numerals globally —
digits align in every table and currency cell.

**Details.** Slim token-colored scrollbars (hidden on tab strips — the indicator
already signals position); empty states say "No X yet" + a direct action, never
"It appears that…".

## Mechanism (the part that will bite you if you forget it)

`frontend/src/styles/vectora-theme.css` is **generated** — regenerate with
`python3 frontend/scripts/generate_vectora_theme.py` after any frappe-ui token sync.
It reads `frappe-ui/tailwind/generated/colors.json` and re-emits every gray-family
semantic variable against the Vectora ramps, keeping frappe-ui's own light/dark
mapping tables authoritative for which shade goes where.

**Cascade constraint:** the file is imported after frappe-ui's stylesheet, and
`:root` ties `[data-theme="dark"]` on specificity, so later-in-order wins. Any token
the theme sets in one mode must be set in **both** modes — the generator backfills
stock values for asymmetric tokens (e.g. `surface-sidebar` is gray-50 in light but
`neutral/transparent` in dark; missing that painted the dark sidebar light).

## 7C coherence audit — result

- Swept Leads/Deals/Contacts/Notes/Tasks/Dashboard + kanban + detail + create modal
  + empty states, light and dark. All inherit the system through tokens.
- Fixed 6 hardcoded `bg-white` in Settings components → `bg-surface-elevation-2`
  (they broke dark mode). Legitimate exceptions kept: ThemeSwitcher swatches,
  AudioPlayer overlay.
- Empty-state copy pattern fixed once in `ListViews/EmptyState.vue` (all modules
  inherit).

**Deferred to backlog:** a discoverable keyboard-shortcut sheet (7C item — feature
work, not styling); skeleton-loading redesign (frappe-ui defaults inherit the new
tokens and look correct).
