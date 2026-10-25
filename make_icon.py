#!/usr/bin/env python3
"""Generate icon-512.png — brand §6: eclipse motif on navy
(#0d1b2a), one per-product glyph. Ledger's glyph is an open
ledger book — ruled columns, a sober page of records — inside the
gradient eclipse ring. PIL only; deterministic."""
from PIL import Image, ImageDraw

S = 512
NAVY = (13, 27, 42, 255)
STOPS = [(15, 246, 247), (0, 212, 255), (123, 44, 191)]


def lerp(a, b, t):
    return tuple(int(a[i] + (b[i] - a[i]) * t) for i in range(3)) \
        + (255,)


def grad(t):
    return lerp(STOPS[0], STOPS[1], t * 2) if t < 0.5 else \
        lerp(STOPS[1], STOPS[2], (t - 0.5) * 2)


def main():
    img = Image.new("RGBA", (S, S), NAVY)
    d = ImageDraw.Draw(img)
    ring = [54, 54, 458, 458]
    for i in range(72):
        t = i / 72
        d.arc(ring, start=i * 5, end=i * 5 + 6, fill=grad(t),
              width=13)
    d.ellipse([126, 126, 386, 386], fill=NAVY)
    # The open ledger: two pages and a spine.
    d.rounded_rectangle([168, 168, 344, 344], radius=12,
                        fill=(8, 12, 20, 255),
                        outline=(254, 254, 254, 255), width=5)
    d.line([(256, 174), (256, 338)], fill=grad(0.5), width=5)
    # Ruled entries on both pages.
    for i, y in enumerate((206, 240, 274, 308)):
        d.line([(188, y), (238, y)], fill=grad(0.2 + 0.15 * i),
               width=6)
        d.line([(274, y), (324, y)], fill=grad(0.45 + 0.12 * i),
               width=6)
    # The totals rule — double line at the foot of the left page.
    d.line([(188, 330), (238, 330)], fill=grad(0.85), width=4)
    d.line([(188, 338), (238, 338)], fill=grad(0.85), width=4)
    img.save("icon-512.png")
    print("wrote icon-512.png", img.size, img.mode)


if __name__ == "__main__":
    main()
