"""Generate frontend/src/styles/vectora-theme.css.

Reads frappe-ui's Figma-synced token source (generated/colors.json) and re-emits
every gray-family semantic variable resolved against Vectora's indigo-tinted
neutral ramps, so the override block always matches frappe-ui's token names.
"""

import json

SRC = "/workspace/frappe-ui/tailwind/generated/colors.json"
OUT = "/workspace/frontend/src/styles/vectora-theme.css"

# Indigo-tinted neutrals (hue ~243, low chroma), lightness matched to the
# stock frappe-ui gray ramps so contrast relationships are preserved.
LIGHT_GRAY = {
	"50": "#f7f7fb",
	"100": "#f2f2f8",
	"200": "#ebebf3",
	"300": "#dfdfeb",
	"400": "#c4c4d6",
	"500": "#9695ab",
	"600": "#7a7990",
	"700": "#504f65",
	"800": "#373647",
	"900": "#16161f",
	"950": "#0e0e14",
}
DARK_GRAY = {
	"50": "#f7f7fb",
	"100": "#d8d8e1",
	"200": "#aeaebc",
	"300": "#9898a8",
	"400": "#79798a",
	"450": "#565666",
	"500": "#414150",
	"600": "#373745",
	"700": "#282834",
	"800": "#23232e",
	"900": "#1e1e28",
	"950": "#15151d",
}
# Alpha ramps keep frappe-ui's alpha per shade, over indigo-tinted bases.
LIGHT_ALPHA_BASE = "#0e0e1f"  # was pure black
DARK_ALPHA_BASE = "#ececf8"  # was pure white
DARK_ALPHA_950 = "#0e0e1f"  # dark 950 is a black alpha in stock tokens

d = json.load(open(SRC))
stock_light_alpha = d["lightMode"]["gray-alpha"]
stock_dark_alpha = d["darkMode"]["gray-alpha"]


def tint_alpha(stock_hex, base):
	return base + stock_hex[7:9]


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

# Focus ring: brand indigo instead of gray.
light_vars["--focus-outline-default"] = "2px solid #a5a8f2e5"
dark_vars["--focus-outline-default"] = "3px solid #3c3cafcc"

# Brand constants for component use.
BRAND_BLOCK = """
  /* Vectora brand */
  --brand-sky: #21abfb;
  --brand-indigo: #5b5fe8;
  --brand-magenta: #df5feb;
  --brand-gradient: linear-gradient(135deg, #21abfb 0%, #5b5fe8 55%, #df5feb 100%);
"""

header = """/* Vectora theme — generated, do not hand-edit values.
 *
 * Regenerate with: python3 frontend/scripts/generate_vectora_theme.py
 * It reads frappe-ui/tailwind/generated/colors.json and re-emits
 * every gray-family semantic token against Vectora's indigo-tinted neutral ramps,
 * so this file survives frappe-ui token syncs by construction.
 *
 * Design system: cool graphite neutrals (hue ~243), brand indigo reserved for
 * focus/selection/active states, gradient reserved for the mark and the
 * position rail. Lightness matches stock frappe-ui ramps, so every contrast
 * relationship (and WCAG pairing) in frappe-ui components is preserved.
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


css = (
	header
	+ "\n"
	+ block(":root", light_vars, BRAND_BLOCK)
	+ "\n\n"
	+ block('[data-theme="dark"]', dark_vars)
	+ "\n"
)

with open(OUT, "w") as f:
	f.write(css)

print(f"wrote {OUT}: {len(light_vars)} light vars, {len(dark_vars)} dark vars")
