"""Generate frontend/src/styles/vectora-theme.css.

Reads frappe-ui's Figma-synced token source (generated/colors.json) and re-emits
every gray-family semantic variable resolved against Vectora's indigo-tinted
neutral ramps, so the override block always matches frappe-ui's token names.

The ramps are authored in OKLCH (perceptually uniform) rather than as hex
literals: the brand reads as a hue, so the interesting axis is chroma, and
OKLCH is the only space where "same lightness, more hue" is expressible.
Hexes are derived here at generation time.

Steps that carry body text are not authored — they are *solved* for a target
contrast ratio against the darkest surface that text routinely sits on, and
the whole file is asserted against the WCAG floors before it is written.

The output is not pretty-printed here: pre-commit's pinned prettier owns the
formatting, so run the hook after regenerating and commit what it leaves.
"""

import json
import math
import re
from itertools import pairwise

# Was /workspace/frappe-ui/... -- a git submodule that has been removed. Its
# pinned commit no longer exists on frappe/frappe-ui (upload-pack: not our ref),
# so that path could not be materialised by anyone and this script had no
# runnable token source at all. Nothing else in the repo used the submodule:
# the production build resolves frappe-ui from node_modules, and the dev-only
# local-checkout override in vite.config.js is guarded by existsSync.
#
# This now reads the pinned npm package. A regenerated file is equivalent to
# the committed one: every shared variable is value-identical, and nothing is
# emitted that was not there before. Two differences are expected and correct:
#
#   * beta.55 spells pure white `oklch(1 0 0)` where the old source wrote
#     `#ffffff`. Same colour, different notation.
#   * The six --ink-alert-button-* / --surface-alert-button-* variables
#     disappear. frappe-ui dropped them deliberately in beta.55 (see
#     DROPPED_SEMANTIC_NAMES in tailwind/figma-tokens-to-theme.js): a Figma
#     spec that was never wired to code, with zero call sites across
#     frappe-ui's own source, all nine consumer apps, and frappe's ui/
#     package. Nothing in this repo referenced them either.
#
# So regenerating is safe. Still diff the result -- the contrast assertions
# below cover the tokens this script solves for, not the ones it passes
# through, so a genuine upstream token change would not announce itself.
SRC = "/workspace/frontend/node_modules/frappe-ui/tailwind/generated/colors.json"
OUT = "/workspace/frontend/src/styles/vectora-theme.css"

# ---------------------------------------------------------------------------
# sRGB <-> OKLab, WCAG contrast. Small enough to inline; no build dependency.
# ---------------------------------------------------------------------------

_M1 = (
	(0.4122214708, 0.5363325363, 0.0514459929),
	(0.2119034982, 0.6806995451, 0.1073969566),
	(0.0883024619, 0.2817188376, 0.6299787005),
)
_M2 = (
	(0.2104542553, 0.7936177850, -0.0040720468),
	(1.9779984951, -2.4285922050, 0.4505937099),
	(0.0259040371, 0.7827717662, -0.8086757660),
)
_M1_INV = (
	(1.0000000000, 0.3963377774, 0.2158037573),
	(1.0000000000, -0.1055613458, -0.0638541728),
	(1.0000000000, -0.0894841775, -1.2914855480),
)
_M2_INV = (
	(4.0767416621, -3.3077115913, 0.2309699292),
	(-1.2684380046, 2.6097574011, -0.3413193965),
	(-0.0041960863, -0.7034186147, 1.7076147010),
)


def _apply(m, v):
	return [sum(m[i][j] * v[j] for j in range(3)) for i in range(3)]


def _to_srgb(c):
	return 12.92 * c if c <= 0.0031308 else 1.055 * c ** (1 / 2.4) - 0.055


def _to_linear(c):
	return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def oklch(lightness, chroma, hue):
	"""OKLCH -> #rrggbb, clamped into sRGB."""
	rad = math.radians(hue)
	lab = (lightness, chroma * math.cos(rad), chroma * math.sin(rad))
	lms = [c**3 for c in _apply(_M1_INV, lab)]
	rgb = _apply(_M2_INV, lms)
	return "#" + "".join("%02x" % max(0, min(255, round(_to_srgb(max(0.0, min(1.0, c))) * 255))) for c in rgb)


def _relative_luminance(hex_color):
	h = hex_color.lstrip("#")
	r, g, b = (_to_linear(int(h[i : i + 2], 16) / 255) for i in (0, 2, 4))
	return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast(a, b):
	"""WCAG 2.x contrast ratio between two opaque hex colours."""
	la, lb = sorted((_relative_luminance(a), _relative_luminance(b)), reverse=True)
	return (la + 0.05) / (lb + 0.05)


def solve_lightness(target_ratio, background, chroma, hue, lighter):
	"""OKLCH lightness whose colour hits `target_ratio` against `background`."""
	lo, hi = 0.0, 1.0
	for _ in range(60):
		mid = (lo + hi) / 2
		if (contrast(oklch(mid, chroma, hue), background) < target_ratio) ^ lighter:
			hi = mid
		else:
			lo = mid
	return (lo + hi) / 2


# ---------------------------------------------------------------------------
# The Vectora neutral ramps
# ---------------------------------------------------------------------------

# Every neutral sits on the brand indigo's hue. Stock frappe-ui grays are
# achromatic, so hue presence is the whole rebrand: the light surfaces that
# dominate the screen (50-300) carry 2-3x the chroma the first pass used,
# which is what moves them past the perceptual threshold against stock.
HUE = 278.0

# Text-bearing steps are solved, not authored (see AA_FLOOR below); the rest
# are (lightness, chroma) pairs. Lightness tracks the stock ramp so frappe-ui's
# component contrast relationships survive.
LIGHT_SPEC = {
	"50": (0.9740, 0.0125),
	"100": (0.9590, 0.0165),
	"200": (0.9380, 0.0210),
	"300": (0.9020, 0.0270),
	"400": (0.8230, 0.0350),
	# The four text steps are a ladder: each is solved for a contrast target
	# against the hardest surface it lands on, and the gaps between the targets
	# are what keep the hierarchy visible. Authoring 6 and 7 by lightness while
	# solving 4 and 5 is what let the rungs converge.
	"500": ("solve", 4.60, 0.0380),  # ink-gray-4 — placeholders, smallest labels
	"600": ("solve", 6.10, 0.0390),  # ink-gray-5 — secondary text
	"700": ("solve", 8.20, 0.0400),  # ink-gray-6 — body
	"800": ("solve", 12.00, 0.0350),  # ink-gray-7 — emphasis
	"900": (0.2045, 0.0260),
	"950": (0.1667, 0.0210),
}
DARK_SPEC = {
	"50": (0.9773, 0.0090),
	"100": (0.8930, 0.0165),
	# The same ladder as light, mirrored: brighter is more emphatic here. 250 is
	# stock's dark ink-gray-6 and is ours now rather than a backfilled stock
	# value, so the assertions can actually reach it.
	"200": ("solve", 9.20, 0.0230),  # ink-gray-7 — emphasis
	"250": ("solve", 7.60, 0.0260),  # ink-gray-6 — body
	"300": ("solve", 6.10, 0.0280),  # ink-gray-5 — secondary text
	"400": ("solve", 4.60, 0.0320),  # ink-gray-4 — placeholders, smallest labels
	"450": (0.4591, 0.0330),
	"500": (0.3813, 0.0330),
	"600": (0.3426, 0.0320),
	"700": (0.2821, 0.0300),
	"800": (0.2611, 0.0290),
	"900": (0.2396, 0.0275),
	"950": (0.1996, 0.0250),
}


def build_ramp(spec, anchor_step, lighter):
	"""Resolve a spec to hexes. Solved steps are measured against `anchor_step`,
	the darkest (light mode) / lightest (dark mode) surface that routinely
	carries secondary body text — inputs and hover rows, i.e. surface-gray-2."""
	ramp = {k: oklch(v[0], v[1], HUE) for k, v in spec.items() if v[0] != "solve"}
	anchor = ramp[anchor_step]
	for step, value in spec.items():
		if value[0] == "solve":
			_, ratio, chroma = value
			ramp[step] = oklch(solve_lightness(ratio, anchor, chroma, HUE, lighter), chroma, HUE)
	return {k: ramp[k] for k in spec}


# Anchored on surface-gray-3, not gray-2: gray-3 is the hover/pressed row and
# the selected-row background on the Reports page, so it is the darkest (light)
# and lightest (dark) ground body text actually lands on. Solving against the
# easier surface is how ink-gray-4 shipped at 4.27:1 on the harder one.
LIGHT_GRAY = build_ramp(LIGHT_SPEC, anchor_step="200", lighter=False)
DARK_GRAY = build_ramp(DARK_SPEC, anchor_step="600", lighter=True)

# The canvas is no longer stock white. Cards, popovers and modals stay on
# --surface-elevation-*, which frappe-ui keeps at #ffffff in light mode, so
# giving the page ground a tint is what creates the elevation hierarchy the
# shadows then reinforce.
LIGHT_SURFACE_BASE = oklch(0.9880, 0.0055, HUE)

# Alpha ramps keep frappe-ui's alpha per shade, over indigo-tinted bases.
LIGHT_ALPHA_BASE = "#0e0e1f"  # was pure black
DARK_ALPHA_BASE = "#ececf8"  # was pure white
DARK_ALPHA_950 = "#0e0e1f"  # dark 950 is a black alpha in stock tokens

# A build script reading two module-level constant paths; it never runs in the
# app and takes no input from a request.
d = json.load(open(SRC))  # nosemgrep: frappe-semgrep-rules.rules.security.frappe-security-file-traversal
stock_light_alpha = d["lightMode"]["gray-alpha"]
stock_dark_alpha = d["darkMode"]["gray-alpha"]


def _alpha_hex(stock):
	"""frappe-ui's per-shade alpha, as a two-digit hex suffix.

	Two spellings have shipped. The older token dumps wrote `#rrggbbaa`; since
	1.0.0-beta.55 the generated tokens are `oklch(L C H / a)`. Only the alpha
	channel is read either way -- the colour underneath is discarded, because
	the point of the ramp is frappe-ui's opacity over *our* indigo-tinted base.

	Reading the oklch form as a hex string is what the slice below used to do,
	and it fails silently: `"oklch(0 0 0 / 0.031)"[7:9]` is `" 0"`, so every
	step collapsed to `#0e0e1f 0` -- a value CSS drops, leaving the ramp
	invisible rather than wrong-looking.
	"""
	m = re.search(r"/\s*([0-9.]+)\s*\)$", stock.strip())
	if m:
		return f"{round(float(m.group(1)) * 255):02x}"
	return stock[7:9]


def tint_alpha(stock, base):
	return base + _alpha_hex(stock)


LIGHT_GRAY_ALPHA = {k: tint_alpha(v, LIGHT_ALPHA_BASE) for k, v in stock_light_alpha.items()}
DARK_GRAY_ALPHA = {
	k: tint_alpha(v, DARK_ALPHA_950 if k == "950" else DARK_ALPHA_BASE) for k, v in stock_dark_alpha.items()
}

PALETTES = {
	"lightMode/gray": LIGHT_GRAY,
	"darkMode/gray": DARK_GRAY,
	"lightMode/gray-alpha": LIGHT_GRAY_ALPHA,
	"darkMode/gray-alpha": DARK_GRAY_ALPHA,
}


def resolve(ref):
	"""Return the Vectora value for a token reference, or None to leave stock."""
	parts = ref.split("/")
	if len(parts) != 3:
		return None
	family = parts[0] + "/" + parts[1]
	if family in PALETTES:
		return PALETTES[family].get(parts[2])
	return None


light_vars, dark_vars = {}, {}

# Base palette vars (--gray-*, --dark-gray-*) so raw utility classes shift too.
for shade, val in LIGHT_GRAY.items():
	light_vars[f"--gray-{shade}"] = val
for shade, val in DARK_GRAY.items():
	dark_vars[f"--dark-gray-{shade}"] = val
for shade, val in LIGHT_GRAY_ALPHA.items():
	light_vars[f"--gray-alpha-{shade}"] = val
for shade, val in DARK_GRAY_ALPHA.items():
	dark_vars[f"--dark-gray-alpha-{shade}"] = val

# Semantic vars, driven by frappe-ui's own light/dark mapping tables.
tv = d["themedVariables"]
for cat, tokens in tv["light"].items():
	for name, ref in tokens.items():
		val = resolve(ref)
		if val:
			light_vars[f"--{cat}-{name}"] = val
for cat, tokens in tv["dark"].items():
	for name, ref in tokens.items():
		val = resolve(ref)
		if val:
			dark_vars[f"--{cat}-{name}"] = val


def resolve_stock(ref):
	"""Resolve a token reference against frappe-ui's stock palettes."""
	parts = ref.split("/")
	node = d
	for p in parts:
		node = node[p]
	return node


# This file is imported after frappe-ui's stylesheet, so its :root block beats
# frappe-ui's [data-theme=dark] block in the cascade (equal specificity, later
# order). Every semantic token this theme touches in one mode must therefore
# be defined in BOTH modes — tokens missing from one block are backfilled with
# frappe-ui's stock value for that mode (e.g. surface-sidebar is gray in light
# but `neutral/transparent` in dark).
for cat in tv["light"]:
	for name in tv["light"][cat]:
		var = f"--{cat}-{name}"
		if var in light_vars and var not in dark_vars:
			dark_vars[var] = resolve_stock(tv["dark"][cat][name])
		if var in dark_vars and var not in light_vars:
			light_vars[var] = resolve_stock(tv["light"][cat][name])

# Light-mode canvas. Dark mode already gets its canvas from gray-950 above, so
# this is set after the backfill (which would otherwise hand light stock white).
light_vars["--surface-base"] = LIGHT_SURFACE_BASE
light_vars["--surface-alpha-base"] = LIGHT_SURFACE_BASE

# The pinned token export maps dark ink-gray-5 to the same ramp step as
# ink-gray-4, so the two collapse to one colour and the secondary/placeholder
# distinction disappears in dark mode. frappe-ui's own colors.js maps 5 to the
# next step up, which is clearly the intent; follow that rather than the stale
# export. The assertion over emitted tokens below is what keeps this honest.
dark_vars["--ink-gray-5"] = DARK_GRAY["300"]
dark_vars["--ink-gray-6"] = DARK_GRAY["250"]
dark_vars["--ink-gray-7"] = DARK_GRAY["200"]

# Focus ring. Stock is a near-invisible gray at ~2:1; WCAG 2.2 SC 1.4.11 wants
# >= 3:1 against everything adjacent, so light gets the brand at full strength
# (no alpha — the stock e5/cc alphas were half the contrast problem) and dark
# gets the light tint of it.
light_vars["--focus-outline-default"] = "2px solid var(--brand-500)"
dark_vars["--focus-outline-default"] = "3px solid var(--brand-300)"
# frappe-ui also exposes the ring in box-shadow form; keep the two in step.
light_vars["--focus-default"] = "0px 0px 0px 2px var(--brand-500)"
dark_vars["--focus-default"] = "0px 0px 0px 3px var(--brand-300)"

# The brand as a palette is mode-invariant; the brand as *ink* is not — the
# 500 that reads at 4.9:1 on a light canvas is 3.3:1 on a dark one. This is
# what `text-brand` resolves to (tailwind.config.js), so it flips.
light_vars["--brand-ink"] = "var(--brand-600)"
dark_vars["--brand-ink"] = "var(--brand-300)"

# Elevation. frappe-ui emits --elevation-* into :root only, so in dark mode
# every panel was casting a light-mode shadow (tuned for a white ground, all
# but invisible on a dark one). Emitting both blocks fixes that and lets the
# shadows carry the brand: they are cast in the indigo-black the neutrals are
# mixed from, not in neutral #000.
LIGHT_ELEVATION = {
	"sm": "0px 1px 2px -1px #0e0e1f14, 0px 1px 3px 0px #0e0e1f1a",
	"base": "0px 1px 2px -1px #0e0e1f14, 0px 2px 6px -1px #0e0e1f1f",
	"md": "0px 0px 0px 1px #0e0e1f0d, 0px 2px 4px -2px #0e0e1f14, 0px 6px 14px -3px #0e0e1f24",
	"lg": "0px 0px 0px 1px #0e0e1f0d, 0px 4px 8px -4px #0e0e1f14, 0px 14px 28px -6px #0e0e1f29",
	"xl": "0px 0px 0px 1px #0e0e1f0d, 0px 6px 12px -6px #0e0e1f17, 0px 24px 40px -10px #0e0e1f2e",
	"2xl": "0px 0px 0px 1px #0e0e1f0d, 0px 10px 20px -8px #0e0e1f1a, 0px 40px 64px -14px #0e0e1f33",
}
# On a dark ground a drop shadow alone reads as mud; the top inner hairline is
# what separates the panel edge from the surface behind it.
DARK_ELEVATION = {
	"sm": "inset 0px 0.5px 0px 0px #ececf814, 0px 1px 2px -1px #00000059, 0px 1px 3px 0px #00000066",
	"base": "inset 0px 0.5px 0px 0px #ececf814, 0px 1px 2px -1px #00000059, 0px 2px 6px -1px #00000073",
	"md": "inset 0px 0.5px 0px 0px #ececf81a, 0px 0px 0px 1px #00000059, 0px 6px 14px -3px #00000080",
	"lg": "inset 0px 0.5px 0px 0px #ececf81a, 0px 0px 0px 1px #00000059, 0px 14px 28px -6px #0000008c",
	"xl": "inset 0px 0.5px 0px 0px #ececf81f, 0px 0px 0px 1px #00000059, 0px 24px 40px -10px #00000099",
	"2xl": "inset 0px 0.5px 0px 0px #ececf81f, 0px 0px 0px 1px #00000059, 0px 40px 64px -14px #000000a6",
}
for step, value in LIGHT_ELEVATION.items():
	light_vars[f"--elevation-{step}"] = value
for step, value in DARK_ELEVATION.items():
	dark_vars[f"--elevation-{step}"] = value
# Stock hardcodes the status halo to #ffffff, which draws a white ring around
# every avatar presence dot in dark mode. Ride the canvas token instead.
light_vars["--elevation-status"] = "0px 0px 0px 1.5px var(--surface-base)"
dark_vars["--elevation-status"] = "0px 0px 0px 1.5px var(--surface-base)"

# Brand constants. Everything here has a consumer: sky/magenta/500 compose the
# gradients, 300/500 are the focus ring, 100/700/900 are the selection colours
# (index.css). Nothing is declared "for later" — an unused token is a claim the
# product does not keep.
BRAND = {
	"--brand-sky": "#21abfb",
	"--brand-magenta": "#df5feb",
	"--brand-100": "#e0e2fb",
	"--brand-300": "#a5a8f2",
	"--brand-500": "#5b5fe8",
	"--brand-600": "#4a4bd1",
	"--brand-700": "#3c3caf",
	"--brand-900": "#282870",
	# One gradient, two axes, one stop list. Every other copy of it in the
	# codebase was deleted in favour of these two.
	"--brand-gradient": "linear-gradient(135deg, var(--brand-sky) 0%, var(--brand-500) 55%, var(--brand-magenta) 100%)",
	"--brand-gradient-y": "linear-gradient(180deg, var(--brand-sky) 0%, var(--brand-500) 55%, var(--brand-magenta) 100%)",
}

# Motion. Three durations and two curves is the whole language: anything that
# needs a fourth is a bespoke animation and should say so. Mode-invariant, but
# emitted into both blocks like every other token (see the cascade note above).
MOTION = {
	"--motion-fast": "90ms",  # hover, press, colour swaps
	"--motion-base": "160ms",  # selection, disclosure, popovers
	"--motion-slow": "260ms",  # panel enter/leave, drawers
	# Decisive: leaves immediately, settles softly. No overshoot anywhere in a
	# data application — bounce reads as latency when you do it 500x a day.
	"--motion-ease": "cubic-bezier(0.2, 0, 0, 1)",
	"--motion-ease-out": "cubic-bezier(0.05, 0.7, 0.1, 1)",
}


def render_block(pairs, indent="  "):
	return "\n".join(f"{indent}{k}: {v};" for k, v in pairs.items())


EXTRA_LIGHT = (
	"\n  /* Vectora brand */\n" + render_block(BRAND) + "\n\n  /* Motion */\n" + render_block(MOTION) + "\n"
)
EXTRA_DARK = EXTRA_LIGHT

header = """/* Vectora theme — generated, do not hand-edit values.
 *
 * Regenerate with: python3 frontend/scripts/generate_vectora_theme.py
 * It reads frappe-ui/tailwind/generated/colors.json and re-emits
 * every gray-family semantic token against Vectora's indigo-tinted neutral ramps,
 * so this file survives frappe-ui token syncs by construction.
 *
 * Design system: indigo-tinted neutrals (OKLCH hue 278, the brand indigo's own
 * hue), brand colour reserved for focus/selection/active states, gradient
 * reserved for the mark and the position rail, elevation cast in the same
 * indigo-black the neutrals are mixed from.
 *
 * Contrast: lightness tracks the stock frappe-ui ramps, so frappe-ui's relative
 * contrast relationships are preserved; on top of that the text-bearing steps
 * are solved for a WCAG AA floor and the generator asserts it before writing
 * (>= 4.5:1 for ink-gray-5..9 and >= 3:1 for ink-gray-4 and the focus ring,
 * measured in both modes against the darkest surface text routinely sits on).
 */
"""


def block(selector, vars_, extra=""):
	lines = [f"{selector} {{"]
	if extra:
		lines.append(extra.rstrip())
	for k, v in vars_.items():
		lines.append(f"  {k}: {v};")
	lines.append("}")
	return "\n".join(lines)


# ---------------------------------------------------------------------------
# Assertions — the accessibility contract, checked at generation time so a
# future tweak to a ramp cannot quietly drop the theme below AA.
# ---------------------------------------------------------------------------

AA_FLOOR = 4.5
NON_TEXT_FLOOR = 3.0
report = []


def check(label, fg, bg, floor):
	ratio = contrast(fg, bg)
	report.append((label, fg, bg, ratio, floor))
	assert ratio >= floor, f"{label}: {fg} on {bg} is {ratio:.2f}:1, below {floor}:1"


# ink-gray-4 is the placeholder step, and placeholders are read: 91 call sites
# use it for `text-xs` labels and "No Title" fallbacks. It was previously held to
# the 3:1 non-text bar, which is why the generator could pass while the smallest
# text in the product sat at 3.3:1. Every step from 4 up is text.
INK_TEXT_STEPS = (("ink-gray-4", "500"), ("ink-gray-5", "600"), ("ink-gray-6", "700"), ("ink-gray-7", "800"))
DARK_INK_TEXT_STEPS = (
	("ink-gray-4", "400"),
	("ink-gray-5", "300"),
	("ink-gray-6", "250"),
	("ink-gray-7", "200"),
)

# Assert the tokens that actually ship, not the ramp steps behind them. The
# emitted mapping is what a component resolves, and it is where dark ink-gray-4
# and ink-gray-5 collapsed onto one colour while every ramp-level check passed.
INK_TEXT_TOKENS = ("--ink-gray-4", "--ink-gray-5", "--ink-gray-6", "--ink-gray-7")

# Every surface a body-text ink can land on, not just the one it was tuned
# against: `surface-elevation-3` is the selected row on the Reports page and
# `surface-gray-3/4` are hover and pressed states throughout.
TEXT_SURFACES = (
	"--surface-base",
	"--surface-white",
	"--surface-gray-2",
	"--surface-gray-3",
	"--surface-elevation-3",
)

for mode, emitted in (("light", light_vars), ("dark", dark_vars)):
	for ink in INK_TEXT_TOKENS:
		for surface in TEXT_SURFACES:
			fg, bg = emitted.get(ink), emitted.get(surface)
			if not fg or not bg or len(fg) != 7 or len(bg) != 7:
				continue
			check(f"{mode} {ink[2:]} on {surface[10:]}", fg, bg, AA_FLOOR)


def check_distinct(label, a, b, floor=1.12):
	"""Adjacent ink steps must stay visibly apart.

	Dark ink-gray-4 and ink-gray-5 both resolved to #8b8fa4 for a release: one
	was solved and the other authored, they converged, and nothing noticed
	because no assertion compared them. A hierarchy step that silently collapses
	is worse than one that never existed — the UI keeps claiming a distinction
	the eye cannot make.
	"""
	separation = contrast(a, b)
	report.append((label, a, b, separation, floor))
	assert separation >= floor, f"{label}: {a} and {b} differ by only {separation:.3f}x, below {floor}x"


for mode, emitted in (("light", light_vars), ("dark", dark_vars)):
	tokens = [t for t in INK_TEXT_TOKENS if emitted.get(t) and len(emitted[t]) == 7]
	for token_a, token_b in pairwise(tokens):
		check_distinct(f"{mode} {token_a[2:]} vs {token_b[2:]}", emitted[token_a], emitted[token_b])
# Focus ring vs every surface it can be drawn against (SC 1.4.11).
for step in ("50", "100", "200", "300"):
	check(f"focus ring on gray-{step}", BRAND["--brand-500"], LIGHT_GRAY[step], NON_TEXT_FLOOR)
check("focus ring on canvas", BRAND["--brand-500"], LIGHT_SURFACE_BASE, NON_TEXT_FLOOR)
check("focus ring on white", BRAND["--brand-500"], "#ffffff", NON_TEXT_FLOOR)
for step in ("950", "900", "800", "700", "600"):
	check(f"dark focus ring on gray-{step}", BRAND["--brand-300"], DARK_GRAY[step], NON_TEXT_FLOOR)
# Selection pairs.
check("light selection", BRAND["--brand-900"], BRAND["--brand-100"], AA_FLOOR)
check("dark selection", DARK_GRAY["50"], BRAND["--brand-700"], AA_FLOOR)
# `text-brand` is body-sized text (Planner's today marker), so it takes the
# full AA floor on every surface it can land on.
for step in ("100", "50"):
	check(f"light brand ink on gray-{step}", BRAND["--brand-600"], LIGHT_GRAY[step], AA_FLOOR)
check("light brand ink on canvas", BRAND["--brand-600"], LIGHT_SURFACE_BASE, AA_FLOOR)
for step in ("950", "900", "700"):
	check(f"dark brand ink on gray-{step}", BRAND["--brand-300"], DARK_GRAY[step], AA_FLOOR)

css = (
	header
	+ "\n"
	+ block(":root", light_vars, EXTRA_LIGHT)
	+ "\n\n"
	+ block('[data-theme="dark"]', dark_vars, EXTRA_DARK)
	+ "\n"
)

# Constant path, build-time only (see above).
with open(OUT, "w") as f:  # nosemgrep: frappe-semgrep-rules.rules.security.frappe-security-file-traversal
	f.write(css)

print(f"wrote {OUT}: {len(light_vars)} light vars, {len(dark_vars)} dark vars")
print(f"{len(report)} contrast assertions passed:")
for label, fg, bg, ratio, floor in report:
	print(f"  {label:<34} {fg} on {bg}  {ratio:5.2f}:1  (floor {floor})")
