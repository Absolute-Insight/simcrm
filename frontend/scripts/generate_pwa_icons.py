#!/usr/bin/env python3
"""Regenerate the PWA home-screen icons and iOS splash screens from the mark.

Committed rather than run-and-deleted because the icons are derived art: the
mark has been replaced three times and each time the hand-made icons in
crm/public/manifest/ were left behind, so an installed app kept showing a
logo the rest of the product had stopped using. Run this after any change to
crm/public/images/logo.png and the icons follow.

    python3 frontend/scripts/generate_pwa_icons.py

Two things this fixes beyond the stale art:

*Background.* The old icons were transparent PNGs. Neither platform composites
a launcher icon over the wallpaper -- iOS fills transparency with black, which
is why the installed app showed a silver tick floating on a black square. Every
icon written here is fully opaque on the brand white, the same ground the
wordmark lockup and the splash screens use.

*Splash screens.* iOS paints one of these while the installed app boots.
They are keyed to exact device resolutions, so the set is a fixed list that
index.html's media queries must keep matching -- this script rewrites the
artwork of whatever files are already there and never invents or drops one.

*Safe zone.* Android masks a `maskable` icon to whatever shape the launcher
prefers (circle, squircle, teardrop), keeping only a centre circle of 80% of
the icon's width -- everything outside that is liable to be cut. So the two
roles need two different crops, not one file declared twice: `any` is shown
unmasked and wants the mark large, `maskable` must keep the mark's whole
bounding box inside that circle. Sharing one file makes one of the two wrong.
"""

import sys
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "crm" / "public" / "images" / "logo.png"
OUT = ROOT / "crm" / "public" / "manifest"

BACKGROUND = (255, 255, 255, 255)

# Fraction of the icon's width the mark's longest side may occupy on an opaque
# tile. 0.78 leaves the ~11% breathing room either side that reads as
# deliberate padding rather than a mark cropped to its own bounds.
FULL_BLEED_SCALE = 0.78

# A transparent icon carries padding badly: with no tile edge for the gap to
# belong to, it just renders the mark smaller than the space it was given. So
# these fill the canvas, less a sliver to keep the antialiased edge off the
# boundary.
TRANSPARENT_SCALE = 0.96

CLEAR = (0, 0, 0, 0)

# A transparent icon fills its canvas, so when the canvas is larger than the
# mark's own pixels the choice is a softer mark or a smaller one -- and these
# files are consumed downscaled (a taskbar button, a shortcut, a window
# corner), where fill shows and a 1.2x resample does not. Opaque tiles take no
# such licence: their padding means they never need it. The ceiling is here so
# that a genuinely undersized source still fails loudly rather than shipping
# mush.
MAX_UPSCALE = 1.5

# Android's maskable safe zone is the centre circle of diameter 0.8 * width.
# The constraint is on the mark's *diagonal*, not its width: a wide-and-short
# bounding box sized by width alone still pushes its corners outside the
# circle. 0.95 keeps a little clearance inside the circle itself.
SAFE_ZONE_DIAMETER = 0.80
SAFE_ZONE_FILL = 0.95

# (filename, pixel size, mode). Three modes, because the consumers disagree
# about what transparency means:
#
#   "tile"         opaque and padded. apple-icon-180 only: iOS composites a
#                  home-screen icon over black, not over the wallpaper, and
#                  applies its own squircle with no bleed allowance.
#   "maskable"     opaque, mark held inside Android's centre-circle safe zone.
#   "transparent"  the `any` icons. Chrome dresses the installed app's window,
#                  its taskbar button and the desktop shortcut from these, and
#                  each of those has a ground of its own -- so an opaque tile
#                  reads as a white card stuck behind the mark. Android takes
#                  the maskable pair for the launcher and never shows these
#                  bare, which is what makes dropping the tile here safe.
TARGETS = [
	("apple-icon-180.png", 180, "tile"),
	("manifest-icon-192.png", 192, "transparent"),
	("manifest-icon-512.png", 512, "transparent"),
	("manifest-icon-192.maskable.png", 192, "maskable"),
	("manifest-icon-512.maskable.png", 512, "maskable"),
]

# The mark's longest side as a fraction of the splash's *short* edge, which is
# what keeps it the same physical size in portrait and landscape. Matches the
# proportion the previous splash set used, so only the artwork changes.
SPLASH_SCALE = 0.198
SPLASH_QUALITY = 90

# The browser-tab favicon. A tab strip composites over its own ground, in light
# and dark, so this is transparent on the same terms as the `any` icons above.
FAVICON = ROOT / "frontend" / "public" / "favicon.png"
FAVICON_SIZE = 256


def trimmed_mark() -> Image.Image:
	"""The mark cropped to its own ink, so padding is set here and not by
	whatever transparent margin the source file happens to carry."""
	mark = Image.open(SOURCE).convert("RGBA")
	box = mark.getchannel("A").getbbox()
	if box is None:
		sys.exit(f"{SOURCE} is fully transparent")
	return mark.crop(box)


def target_size(mark: Image.Image, size: int, mode: str) -> tuple[int, int]:
	w, h = mark.size
	if mode == "maskable":
		diagonal = (w**2 + h**2) ** 0.5
		scale = (size * SAFE_ZONE_DIAMETER * SAFE_ZONE_FILL) / diagonal
	elif mode == "transparent":
		scale = (size * TRANSPARENT_SCALE) / max(w, h)
	else:
		scale = (size * FULL_BLEED_SCALE) / max(w, h)
	return max(1, round(w * scale)), max(1, round(h * scale))


def centred(mark: Image.Image, size: int, box: tuple[int, int], ground) -> Image.Image:
	w, h = box
	canvas = Image.new("RGBA", (size, size), ground)
	canvas.alpha_composite(mark.resize((w, h), Image.LANCZOS), ((size - w) // 2, (size - h) // 2))
	return canvas


def write_splashes(mark: Image.Image) -> int:
	"""Repaint every apple-splash-*.jpg in place, at its existing size."""
	count = 0
	for path in sorted(OUT.glob("apple-splash-*.jpg")):
		with Image.open(path) as existing:
			width, height = existing.size
		scale = (min(width, height) * SPLASH_SCALE) / max(mark.size)
		w, h = max(1, round(mark.width * scale)), max(1, round(mark.height * scale))
		canvas = Image.new("RGBA", (width, height), BACKGROUND)
		canvas.alpha_composite(
			mark.resize((w, h), Image.LANCZOS),
			((width - w) // 2, (height - h) // 2),
		)
		canvas.convert("RGB").save(path, "JPEG", quality=SPLASH_QUALITY, optimize=True)
		count += 1
	return count


def write_favicon(mark: Image.Image) -> None:
	w, h = target_size(mark, FAVICON_SIZE, "transparent")
	centred(mark, FAVICON_SIZE, (w, h), CLEAR).save(FAVICON, "PNG", optimize=True)
	print(f"{FAVICON.name:34} {FAVICON_SIZE}x{FAVICON_SIZE}  mark {w}x{h}  transparent")


def main() -> None:
	mark = trimmed_mark()
	for name, size, mode in TARGETS:
		w, h = target_size(mark, size, mode)
		upscale = max(w / mark.width, h / mark.height)
		if upscale > 1 and (mode != "transparent" or upscale > MAX_UPSCALE):
			sys.exit(
				f"{name} needs the mark at {w}x{h} but the source is only "
				f"{mark.width}x{mark.height}; upscaling would soften it. "
				f"Replace {SOURCE.name} with a larger export."
			)
		transparent = mode == "transparent"
		canvas = centred(mark, size, (w, h), CLEAR if transparent else BACKGROUND)
		# Flatten the opaque ones to RGB: a tile has no use for an alpha channel,
		# and keeping one invites transparency back into the icons that must not
		# have it.
		if not transparent:
			canvas = canvas.convert("RGB")
		canvas.save(OUT / name, "PNG", optimize=True)
		note = f"  upscaled {upscale:.2f}x" if upscale > 1 else ""
		print(f"{name:34} {size}x{size}  mark {w}x{h}  {mode}{note}")
	print(f"{write_splashes(mark)} splash screens repainted")
	write_favicon(mark)


if __name__ == "__main__":
	main()
