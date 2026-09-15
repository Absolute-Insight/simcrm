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

# Fraction of the icon's width the mark's longest side may occupy when the
# icon is shown whole. 0.78 leaves the ~11% breathing room either side that
# reads as deliberate padding rather than a mark cropped to its own bounds.
FULL_BLEED_SCALE = 0.78

# Android's maskable safe zone is the centre circle of diameter 0.8 * width.
# The constraint is on the mark's *diagonal*, not its width: a wide-and-short
# bounding box sized by width alone still pushes its corners outside the
# circle. 0.95 keeps a little clearance inside the circle itself.
SAFE_ZONE_DIAMETER = 0.80
SAFE_ZONE_FILL = 0.95

# (filename, pixel size, maskable) -- apple-icon-180 is iOS, which applies its
# own squircle with no bleed allowance and so takes the full-bleed crop.
TARGETS = [
	("apple-icon-180.png", 180, False),
	("manifest-icon-192.png", 192, False),
	("manifest-icon-512.png", 512, False),
	("manifest-icon-192.maskable.png", 192, True),
	("manifest-icon-512.maskable.png", 512, True),
]

# The mark's longest side as a fraction of the splash's *short* edge, which is
# what keeps it the same physical size in portrait and landscape. Matches the
# proportion the previous splash set used, so only the artwork changes.
SPLASH_SCALE = 0.198
SPLASH_QUALITY = 90

# The browser-tab favicon is the one icon that keeps its transparency: a tab
# strip *does* composite over its own ground, in light and dark, and a white
# tile there reads as a sticker. At 16px every pixel of padding is mark lost, so
# it fills the canvas, less a sliver so the antialiased edge is not clipped.
FAVICON = ROOT / "frontend" / "public" / "favicon.png"
FAVICON_SIZE = 256
FAVICON_SCALE = 0.96


def trimmed_mark() -> Image.Image:
	"""The mark cropped to its own ink, so padding is set here and not by
	whatever transparent margin the source file happens to carry."""
	mark = Image.open(SOURCE).convert("RGBA")
	box = mark.getchannel("A").getbbox()
	if box is None:
		sys.exit(f"{SOURCE} is fully transparent")
	return mark.crop(box)


def target_size(mark: Image.Image, size: int, maskable: bool) -> tuple[int, int]:
	w, h = mark.size
	if maskable:
		diagonal = (w**2 + h**2) ** 0.5
		scale = (size * SAFE_ZONE_DIAMETER * SAFE_ZONE_FILL) / diagonal
	else:
		scale = (size * FULL_BLEED_SCALE) / max(w, h)
	return max(1, round(w * scale)), max(1, round(h * scale))


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
	scale = (FAVICON_SIZE * FAVICON_SCALE) / max(mark.size)
	w, h = max(1, round(mark.width * scale)), max(1, round(mark.height * scale))
	canvas = Image.new("RGBA", (FAVICON_SIZE, FAVICON_SIZE), (0, 0, 0, 0))
	canvas.alpha_composite(
		mark.resize((w, h), Image.LANCZOS),
		((FAVICON_SIZE - w) // 2, (FAVICON_SIZE - h) // 2),
	)
	canvas.save(FAVICON, "PNG", optimize=True)
	print(f"{FAVICON.name:34} {FAVICON_SIZE}x{FAVICON_SIZE}  mark {w}x{h}  transparent")


def main() -> None:
	mark = trimmed_mark()
	for name, size, maskable in TARGETS:
		w, h = target_size(mark, size, maskable)
		if w > mark.width or h > mark.height:
			sys.exit(
				f"{name} needs the mark at {w}x{h} but the source is only "
				f"{mark.width}x{mark.height}; upscaling would soften it. "
				f"Replace {SOURCE.name} with a larger export."
			)
		canvas = Image.new("RGBA", (size, size), BACKGROUND)
		resized = mark.resize((w, h), Image.LANCZOS)
		canvas.alpha_composite(resized, ((size - w) // 2, (size - h) // 2))
		# Flatten to RGB: an opaque icon has no use for an alpha channel, and
		# keeping one invites the transparency this script exists to remove.
		canvas.convert("RGB").save(OUT / name, "PNG", optimize=True)
		print(f"{name:34} {size}x{size}  mark {w}x{h}")
	print(f"{write_splashes(mark)} splash screens repainted")
	write_favicon(mark)


if __name__ == "__main__":
	main()
